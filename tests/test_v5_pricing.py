"""The pricing function: fail-closed reasons, minimum history, stage, freshness and edges."""
from __future__ import annotations

import pandas as pd
import pytest

import v5_baseline_elo as be
import v5_pricing as vp
from v5_fixture_resolution import FixtureResolutionError, ResolvedFixture, ResolvedPlayer

NOW = pd.Timestamp("2026-03-16T10:00:00Z")
START = "2026-03-16T14:00:00Z"


def history():
    """A and B have 20 matches each (A wins them all); C has 2."""
    rows = []
    for i in range(20):
        week = pd.Timestamp("2025-06-02") + pd.Timedelta(weeks=i)
        rows.append({"tid": f"h{i}", "date": week, "w": "A", "l": f"x{i}"})
        rows.append({"tid": f"h{i}", "date": week, "w": f"y{i}", "l": "B"})
    rows += [{"tid": "h0", "date": pd.Timestamp("2025-06-02"), "w": "C", "l": "z1"},
             {"tid": "h1", "date": pd.Timestamp("2025-06-09"), "w": "C", "l": "z2"}]
    return pd.DataFrame([{"tour": "MEN", "tid": r["tid"], "tourney_name": r["tid"], "level": "A", "date": r["date"],
                          "stage": 1, "rank": 12.0, "round": "R32", "winner_key": r["w"], "loser_key": r["l"],
                          "surface": "Hard", "walkover": False, "key": f"k{i:03d}", "tourney_id_raw": r["tid"]}
                         for i, r in enumerate(rows)])


class FakeResolver:
    def __init__(self, players, error=None):
        self.players, self.error = players, error
        self.fixtures = pd.DataFrame([{"fixture_id": "f1", "start_time_utc": START, "true_start_time_utc": ""}]).set_index("fixture_id")

    def resolve(self, fid):
        if self.error:
            raise FixtureResolutionError(self.error)
        p1, p2 = (ResolvedPlayer(str(i), n or "?", n, "auto" if n else "no_history", None) for i, n in enumerate(self.players))
        return ResolvedFixture("f1", "ATP|2026-03-16|x|x", "MEN", "ATP", "X", "Hard", "Outdoor", 3, {}, {}, p1, p2)


def quotes(book, p1, p2, fetched="2026-03-16T09:30:00Z", withdrawn=False):
    return pd.DataFrame([{"fetched_utc": fetched, "fixture_id": "f1", "bookmaker": book, "market_group": "moneyline",
                          "side": s, "price": p, "withdrawn": withdrawn} for s, p in (("p1", p1), ("p2", p2))])


def price(players, error=None, **kw):
    live = be.run(history(), be.EloParams(), live=True)
    return vp.price_fixture("f1", resolver=FakeResolver(players, error), live_elo=live, events={},
                            stages={"f1": ("main", "after_start")}, now=NOW, **kw)


def test_resolver_failures_are_no_price_with_the_code():
    p = price(("A", "B"), error="TOURNAMENT_UNRESOLVED")
    assert p.status == "no_price" and p.reason == "TOURNAMENT_UNRESOLVED" and p.model_p1 is None


def test_no_history_unknown_rating_and_thin_history_give_no_model_price():
    assert price((None, "B")).reason == "NO_HISTORY"
    assert price(("A", "nobody")).reason == "NO_RATING"
    thin = price(("A", "C"))
    assert thin.reason == "THIN_HISTORY" and thin.model_p1 is None and thin.rated_matches == (20, 2)


def test_priced_fixture_with_market_edges_and_freshness():
    q = pd.concat([quotes("bet365", 1.30, 3.60), quotes("pinnacle", 1.33, 3.55),
                   quotes("betrivers", 1.30, 3.60, fetched="2026-03-16T08:00:00Z")])     # 2 h old: stale
    p = price(("A", "B"), quotes=q)
    assert p.status == "priced" and p.model_p1 > 0.5 and p.official_eligible
    rows = {(b["book"], b["side"]): b for b in p.books}
    b365 = rows[("bet365", "p1")]
    assert b365["actionable"] and b365["cautious_edge"] is not None and b365["expected_value"] is not None
    assert rows[("pinnacle", "p1")]["role"] == "information" and rows[("pinnacle", "p1")]["cautious_edge"] is None
    assert rows[("betrivers", "p1")]["reason"] == "STALE_SNAPSHOT" and rows[("betrivers", "p1")]["cautious_edge"] is None


def test_a_withdrawn_side_blocks_the_pair():
    q = pd.concat([quotes("bet365", 1.30, 3.60).iloc[[0]], quotes("bet365", 1.30, 3.60, withdrawn=True).iloc[[1]]])
    rows = {b["side"]: b for b in price(("A", "B"), quotes=q).books}
    assert rows["p2"]["reason"] == "WITHDRAWN" and rows["p1"]["reason"] == "PAIR_NOT_ACTIONABLE"


def test_qualifying_is_priced_but_not_official():
    live = be.run(history(), be.EloParams(), live=True)
    p = vp.price_fixture("f1", resolver=FakeResolver(("A", "B")), live_elo=live, events={},
                         stages={"f1": ("qualifying", "played_before")}, now=NOW)
    assert p.status == "priced" and not p.official_eligible


def test_quotes_without_a_time_to_judge_them_raise():
    live = be.run(history(), be.EloParams(), live=True)
    with pytest.raises(ValueError):
        vp.price_fixture("f1", resolver=FakeResolver(("A", "B")), live_elo=live, events={}, quotes=quotes("bet365", 1.3, 3.6))


def test_the_saved_rating_states_price_exactly_as_the_live_ratings():
    # The app re-prices from the states the daily batch saved (it has no history files).
    live = be.run(history(), be.EloParams(), live=True)
    p = vp.price_fixture("f1", resolver=FakeResolver(("A", "B")), live_elo=live, events={},
                         stages={"f1": ("main", "after_start")}, now=NOW)
    stored = vp.StoredElo(vp.rating_state_rows([p]), be.EloParams())
    q = vp.price_fixture("f1", resolver=FakeResolver(("A", "B")), live_elo=stored, events={},
                         stages={"f1": ("main", "after_start")}, now=NOW)
    assert q.model_p1 == p.model_p1 and q.rated_matches == p.rated_matches
