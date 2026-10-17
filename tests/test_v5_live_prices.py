"""Live pre-match prices: same code as the close, cut at the fetch time; the freshness rule."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from v5_live_prices import LIVE_COLUMNS, append_live, has_started, is_actionable, live_quotes

META = [{"marketId": 121, "marketName": "Winner", "period": "fulltime",
         "outcomes": [{"outcomeId": 121, "outcomeName": "Player 1"}, {"outcomeId": 122, "outcomeName": "Player 2"}]}]
FX = {"fixture_id": "f1", "start_time_utc": "2026-10-17T18:00:00Z", "true_start_time_utc": ""}


def q(t, price, active=True):
    return {"createdAt": t, "price": price, "limit": None, "active": active, "exchangeMeta": None}


def payload(p1, p2, book="pinnacle"):
    return {"fixtureId": "f1", "bookmakers": {book: {"markets": {"121": {"outcomes": {
        "121": {"players": {"0": p1}}, "122": {"players": {"0": p2}}}}}}}}


def test_started_means_true_start_reported_or_scheduled_start_passed_and_no_start_is_started():
    assert not has_started(FX, "2026-10-17T12:00:00Z")
    assert has_started(FX, "2026-10-17T18:00:00Z")
    assert has_started({**FX, "true_start_time_utc": "2026-10-17T11:50:00Z"}, "2026-10-17T12:00:00Z")
    assert has_started({"fixture_id": "x", "start_time_utc": "", "true_start_time_utc": ""}, "2026-10-17T12:00:00Z")


def test_live_quote_is_the_price_standing_at_the_fetch_and_a_withdrawn_one_is_flagged():
    body = payload([q("2026-10-17T08:00:00Z", 1.80), q("2026-10-17T11:00:00Z", 1.72), q("2026-10-17T12:30:00Z", 1.60)],
                   [q("2026-10-17T08:00:00Z", 2.10), q("2026-10-17T10:00:00Z", 2.10, active=False)])
    live = live_quotes(body, FX, META, "2026-10-17T12:00:00Z").set_index("side")
    assert set(live.reset_index().columns) == set(LIVE_COLUMNS)
    assert live.loc["p1", "price"] == 1.72 and live.loc["p1", "quote_utc"] == "2026-10-17T11:00:00Z"   # 12:30 is later
    assert not live.loc["p1", "withdrawn"] and live.loc["p2", "withdrawn"]
    assert live.loc["p1", "minutes_to_start"] == 360.0
    assert live_quotes(body, FX, META, "2026-10-17T18:05:00Z").empty          # started: no live price


def test_freshness_rule():
    row = {"fetched_utc": "2026-10-17T12:00:00Z", "price": 1.72, "withdrawn": False}
    assert is_actionable(row, FX, "2026-10-17T12:30:00Z") == (True, "OK")
    assert is_actionable(row, FX, "2026-10-17T13:30:00Z") == (False, "STALE_SNAPSHOT")
    assert is_actionable(row, FX, "2026-10-17T18:00:00Z") == (False, "STARTED")
    assert is_actionable(row, {**FX, "true_start_time_utc": "2026-10-17T12:10:00Z"}, "2026-10-17T12:20:00Z") == (False, "STARTED")
    assert is_actionable({**row, "withdrawn": True}, FX, "2026-10-17T12:30:00Z") == (False, "WITHDRAWN")
    assert is_actionable({**row, "price": None}, FX, "2026-10-17T12:30:00Z") == (False, "NO_PRICE")
    assert is_actionable({**row, "fetched_utc": ""}, FX, "2026-10-17T12:30:00Z") == (False, "MISSING_TIMESTAMP")


def test_live_store_is_append_only(tmp_path):
    body = payload([q("2026-10-17T08:00:00Z", 1.8)], [q("2026-10-17T08:00:00Z", 2.1)])
    live = live_quotes(body, FX, META, "2026-10-17T12:00:00Z")
    assert append_live(live, tmp_path) == 2 and append_live(live, tmp_path) == 0
    assert len(pd.read_csv(tmp_path / "market_history" / "live" / "2026-10.csv")) == 2


def test_live_workflow_pulls_and_commits_live_prices_even_without_a_fresh_quota_snapshot():
    text = Path(".github/workflows/oddspapi_normalized_daily_v2.yml").read_text(encoding="utf-8")
    step = text.split("Live pre-match prices (free", 1)[1].split("- name:", 1)[0]
    assert "python scripts/pull_live_prices.py" in step and "fresh_snapshot" not in step
    commit = text.split("Commit live pre-match prices", 1)[1].split("- name:", 1)[0]
    assert "git add -A market_history/live" in commit and "--autostash" in commit
