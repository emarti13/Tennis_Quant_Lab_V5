"""Market price store: open/close/checkpoints, stale closes, main lines, append-only, queue."""
from __future__ import annotations

import pandas as pd
import pytest

from v5_market_history import (
    FIXTURE_COLUMNS, LOG_COLUMNS, POINT_COLUMNS, append_pull_log, append_store, close_cutoff, fixture_record,
    load_pull_log, main_lines, pending_fixtures, price_points,
)

META = [
    {"marketId": 121, "marketName": "Winner", "period": "fulltime",
     "outcomes": [{"outcomeId": 121, "outcomeName": "Player 1"}, {"outcomeId": 122, "outcomeName": "Player 2"}]},
    {"marketId": 1225, "marketName": "Total Games", "period": "fulltime", "handicap": 21.5,
     "outcomes": [{"outcomeId": 1225, "outcomeName": "Over"}, {"outcomeId": 1226, "outcomeName": "Under"}]},
    {"marketId": 1227, "marketName": "Total Games", "period": "fulltime", "handicap": 23.5,
     "outcomes": [{"outcomeId": 1227, "outcomeName": "Over"}, {"outcomeId": 1228, "outcomeName": "Under"}]},
    {"marketId": 999, "marketName": "Set 1 Winner", "period": "set1", "outcomes": []},
]
FX = {"fixture_id": "f1", "start_time_utc": "2026-10-10T12:00:00Z", "true_start_time_utc": "2026-10-10T12:20:00Z",
      "tournament_id": "10", "tournament_name": "ATP Somewhere", "participant1_id": "1", "participant2_id": "2"}


def q(t, price, active=True):
    return {"createdAt": t, "price": price, "limit": None, "active": active, "exchangeMeta": None}


def payload(books):
    return {"fixtureId": "f1", "bookmakers": {
        b: {"markets": {str(m): {"outcomes": {str(o): {"players": {"0": qs}} for o, qs in outs.items()}}
                        for m, outs in markets.items()}} for b, markets in books.items()}}


def test_open_close_checkpoints_and_true_start_cutoff():
    pts = price_points(payload({"pinnacle": {121: {
        121: [q("2026-10-09T08:00:00Z", 1.80), q("2026-10-10T06:00:00Z", 1.70), q("2026-10-10T12:10:00Z", 1.65),
              q("2026-10-10T12:30:00Z", 1.20)],          # in play: after the true start
        122: [q("2026-10-09T08:00:00Z", 2.05), q("2026-10-10T12:10:00Z", 2.30)]}}}), FX, META)
    p1 = pts[(pts["side"] == "p1")].iloc[0]
    assert (p1["open_price"], p1["close_price"]) == (1.80, 1.65)
    assert p1["close_utc"] == "2026-10-10T12:10:00Z"
    assert fixture_record(FX)["cutoff_source"] == "true_start"
    assert p1["t24h_price"] == 1.80 and p1["t6h_price"] == 1.70 and p1["t1h_price"] == 1.70
    assert p1["close_gap_min"] == 0 and not p1["close_stale"]
    assert set(pts["market_group"]) == {"moneyline"}       # set-1 market is not stored


def test_scheduled_start_is_used_and_flagged_when_true_start_unknown():
    assert close_cutoff({**FX, "true_start_time_utc": ""})[1] == "scheduled_start"
    with pytest.raises(ValueError):
        close_cutoff({"fixture_id": "x", "start_time_utc": "", "true_start_time_utc": ""})


def test_close_set_early_but_standing_is_not_stale_and_a_withdrawn_one_is():
    pts = price_points(payload({"betrivers": {121: {
        121: [q("2026-10-10T01:00:00Z", 1.75)],                                   # stood until the start
        122: [q("2026-10-10T01:00:00Z", 2.10), q("2026-10-10T02:00:00Z", 2.10, active=False)]}}}), FX, META)
    p1, p2 = (pts[pts["side"] == s].iloc[0] for s in ("p1", "p2"))
    assert not p1["close_stale"]
    assert p2["close_price"] == 2.10 and p2["close_stale"] and p2["close_gap_min"] == pytest.approx(620)
    assert p2["t1h_price"] is None or pd.isna(p2["t1h_price"])               # withdrawn by then


def test_only_the_main_total_line_is_kept_per_book():
    pts = price_points(payload({"pinnacle": {
        1225: {1225: [q("2026-10-10T11:00:00Z", 1.90)], 1226: [q("2026-10-10T11:00:00Z", 1.92)]},
        1227: {1227: [q("2026-10-10T11:00:00Z", 2.60)], 1228: [q("2026-10-10T11:00:00Z", 1.48)]}}}), FX, META)
    assert set(pts["market_id"]) == {"1225"} and set(pts["side"]) == {"Over", "Under"}
    assert set(pts["line"]) == {21.5}


def test_store_is_append_only(tmp_path):
    pts = price_points(payload({"pinnacle": {121: {121: [q("2026-10-10T11:00:00Z", 1.9)],
                                                   122: [q("2026-10-10T11:00:00Z", 1.9)]}}}), FX, META)
    ident = {"edition_key": "ATP|x", "player1_id": "M-1", "player2_id": "M-2", "resolution": "ok"}
    assert append_store(pts, [fixture_record(FX, identity=ident)], tmp_path) == 2
    assert append_store(pts.assign(close_price=9.9), [fixture_record(FX, identity={})], tmp_path) == 0
    stored = pd.read_csv(tmp_path / "market_history" / "price_points" / "2026-10.csv")
    assert list(stored.columns) == POINT_COLUMNS and set(stored["close_price"]) == {1.9}
    fx = pd.read_csv(tmp_path / "market_history" / "fixtures" / "2026-10.csv", dtype=str)
    assert list(fx.columns) == FIXTURE_COLUMNS and list(fx["edition_key"]) == ["ATP|x"]


def _registry(rows):
    base = {"true_start_time_utc": "", "category_name": "ATP", "category_slug": "atp", "tournament_slug": "",
            "participant1_name": "A, A", "participant2_name": "B, B", "historical_status": ""}
    return pd.DataFrame([{**base, **r} for r in rows])


def test_queue_is_oldest_first_and_skips_done_unstarted_irrelevant_and_exhausted(tmp_path):
    reg = _registry([
        {"fixture_id": "old", "start_time_utc": "2026-09-02T10:00:00Z", "tournament_name": "ATP Challenger X"},
        {"fixture_id": "new", "start_time_utc": "2026-10-14T10:00:00Z", "tournament_name": "WTA Y",
         "true_start_time_utc": "2026-10-14T10:40:00Z"},
        {"fixture_id": "future", "start_time_utc": "2026-10-16T18:00:00Z", "tournament_name": "WTA Y"},
        {"fixture_id": "itf", "start_time_utc": "2026-10-14T10:00:00Z", "tournament_name": "ITF M15 Z"},
        {"fixture_id": "done", "start_time_utc": "2026-10-13T10:00:00Z", "tournament_name": "ATP Z"},
        {"fixture_id": "tried", "start_time_utc": "2026-10-13T10:00:00Z", "tournament_name": "ATP Z"},
        {"fixture_id": "stored", "start_time_utc": "2026-08-13T10:00:00Z", "tournament_name": "ATP Z",
         "historical_status": "CACHED"},
    ])
    from pull_oddspapi_quota_aware import relevant_fixture
    books = "pinnacle,bet365,betrivers"
    append_pull_log([{"fixture_id": "done", "books": books, "status": "ok"}]
                    + [{"fixture_id": "tried", "books": books, "status": "error"}] * 3, tmp_path)
    log = load_pull_log(tmp_path)
    assert list(log.columns) == LOG_COLUMNS
    got = pending_fixtures(reg, log, now="2026-10-16T12:00:00Z", since="2026-01-01", books=books,
                           relevant=relevant_fixture, skip_stored=True)
    assert list(got["fixture_id"]) == ["old", "new"]
    # Without a reported true start, a fixture waits up to 3 days for it.
    unknown = reg.assign(true_start_time_utc="")
    assert pending_fixtures(unknown, log, now="2026-10-16T12:00:00Z", since="2026-10-01",
                            books=books, relevant=relevant_fixture).empty
    later = pending_fixtures(unknown, log, now="2026-10-18T12:00:00Z", since="2026-10-01", books=books,
                             relevant=relevant_fixture)
    assert list(later["fixture_id"]) == ["new"]     # 3 days on, pulled anyway (flagged scheduled_start)


def test_main_lines_handles_empty():
    assert main_lines(pd.DataFrame(columns=POINT_COLUMNS)).empty


def test_workflow_is_one_daily_run_serialized_with_production_and_keeps_raw_out_of_git():
    from pathlib import Path
    text = Path(".github/workflows/v5_market_history.yml").read_text(encoding="utf-8")
    trigger = text.split("permissions:", 1)[0]
    assert trigger.count("cron:") == 1 and "workflow_dispatch:" in trigger and "\n  push:" not in trigger
    assert "group: v5-production-writer" in text
    assert "gh release upload" in text
    commit = text.split("Commit price store", 1)[1]
    assert "git add -A market_history" in commit and "git add -f" not in commit
    assert "market_history/raw/" in Path(".gitignore").read_text(encoding="utf-8")


def test_bet365_is_added_only_to_the_fixtures_the_stored_backfill_holds(tmp_path):
    from pull_oddspapi_quota_aware import relevant_fixture
    reg = _registry([
        {"fixture_id": "stored", "start_time_utc": "2026-05-02T10:00:00Z", "tournament_name": "ATP Z",
         "true_start_time_utc": "2026-05-02T10:10:00Z", "historical_status": "CACHED"},
        {"fixture_id": "gap", "start_time_utc": "2026-05-01T10:00:00Z", "tournament_name": "ATP Z",
         "true_start_time_utc": "2026-05-01T10:10:00Z"},
    ])
    log = load_pull_log(tmp_path)
    got = pending_fixtures(reg, log, now="2026-10-16T12:00:00Z", since="2026-01-01", books="bet365",
                           relevant=relevant_fixture, only_stored=True)
    assert list(got["fixture_id"]) == ["stored"]
    append_pull_log([{"fixture_id": "stored", "books": "bet365", "status": "ok"}], tmp_path)
    assert pending_fixtures(reg, load_pull_log(tmp_path), now="2026-10-16T12:00:00Z", since="2026-01-01",
                            books="bet365", relevant=relevant_fixture, only_stored=True).empty


def _pm(monkeypatch):
    import sys
    sys.path.insert(0, "scripts")
    import pull_market_history as pm
    monkeypatch.setattr(pm, "COOLDOWN", 0)
    return pm


class _DatedApi:
    """History exists from `first` on; `missing` fixtures are absent anyway; `errors` fail."""
    def __init__(self, first, missing=(), errors=()):
        self.first, self.missing, self.errors, self.calls = first, set(missing), set(errors), []

    def get(self, endpoint, **params):
        fid = params["fixtureId"]
        self.calls.append(fid)
        if fid in self.errors:
            return 500, {}
        return (404 if fid < self.first or fid in self.missing else 200), {}


def _queue(n, books="b"):
    # fixture ids sort like their start times: d000, d001, ...
    return [("backfill", {"fixture_id": f"d{i:03d}", "start_time_utc": f"2026-04-01T00:00:00Z+{i:03d}"}, books)
            for i in range(n)]


def test_history_expired_before_a_date_is_skipped_with_a_few_calls(monkeypatch):
    pm = _pm(monkeypatch)
    api = _DatedApi(first="d137", missing={"d140", "d150"})     # boundary inside a month; a few gaps
    keep, expired = pm.skip_expired(api, _queue(300))
    # Never drops a fixture that has history; may keep up to window-1 expired ones before it.
    assert all(e["fixture_id"] < "d137" for e in expired) and 137 - pm.PROBE_WINDOW < len(expired)
    assert len(keep) + len(expired) == 300 and all(e["status"] == "not_found" for e in expired)
    assert len(api.calls) < 40                                    # not one call per fixture


def test_nothing_is_dropped_when_the_oldest_still_has_history_or_on_errors(monkeypatch):
    pm = _pm(monkeypatch)
    api = _DatedApi(first="d000")
    keep, expired = pm.skip_expired(api, _queue(50))
    assert not expired and len(keep) == 50 and len(api.calls) == 1
    api = _DatedApi(first="d999", errors={"d000"})              # an error is never read as "expired"
    keep, expired = pm.skip_expired(api, _queue(50))
    assert not expired and len(keep) == 50


def test_each_book_set_has_its_own_boundary_and_all_expired_drops_all(monkeypatch):
    pm = _pm(monkeypatch)
    api = _DatedApi(first="d020")
    keep, expired = pm.skip_expired(api, _queue(30, "a") + _queue(10, "b"))
    assert {e["books"] for e in expired} == {"a", "b"}
    a = [e["fixture_id"] for e in expired if e["books"] == "a"]
    assert all(f < "d020" for f in a) and len(a) > 20 - pm.PROBE_WINDOW
    assert len([e for e in expired if e["books"] == "b"]) == 10   # all expired
    assert {k[2] for k in keep} == {"a"}
