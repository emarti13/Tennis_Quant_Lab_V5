"""Registration 2026-11-03 (season end) tracker: window, ranks, flag, side and settlement."""
from __future__ import annotations

import pandas as pd

import scripts.track_season_end_rule as tr

REG = pd.Timestamp("2026-11-03T15:00:00Z")
START = pd.Timestamp("2026-11-05T12:00:00Z")
RANKS = pd.DataFrame({"key": ["aplayer", "bplayer", "cplayer", "dplayer"],
                      "date": pd.to_datetime(["2026-10-26"] * 4), "rank": [45.0, 150.0, 200.0, 20.0]})


def _q(ev, t, a, b, start=START, series="KXATPCHALLENGERMATCH"):
    return [{"polled_utc": pd.Timestamp(t), "series": series, "event_ticker": ev, "ticker": f"{ev}-{s}", "start_date": start,
             "bid": bid, "ask": ask} for s, (bid, ask) in (("A", a), ("B", b))]


def test_backs_the_opponent_of_the_one_player_ranked_31_to_90_at_the_cheaper_side():
    q = pd.DataFrame(_q("E1", "2026-11-05T09:00Z", (0.58, 0.60), (0.40, 0.43)))
    names = {"E1-A": "A Player", "E1-B": "B Player"}
    d, _ = tr.decisions(q, {}, REG, names, RANKS)
    r = d.iloc[0]
    assert r["flagged_name"] == "A Player" and r["opponent_rank"] == 150
    assert r["bet"] == "NO on flagged" and r["price"] == 0.42             # 1 - 0.58 < 0.43


def test_skips_outside_the_season_window_unknown_ranks_and_no_or_two_flags():
    early = pd.Timestamp("2026-10-10T12:00Z")
    rows = (_q("OLD", "2026-10-10T09:00Z", (0.5, 0.52), (0.47, 0.5), start=early)
            + _q("NONE", "2026-11-05T09:00Z", (0.5, 0.52), (0.47, 0.5))
            + _q("UNK", "2026-11-05T09:00Z", (0.5, 0.52), (0.47, 0.5)))
    names = {"OLD-A": "A Player", "OLD-B": "B Player", "NONE-A": "B Player", "NONE-B": "C Player", "UNK-A": "A Player", "UNK-B": "Who Ever"}
    d, skipped = tr.decisions(pd.DataFrame(rows), {}, REG, names, RANKS)
    assert d.empty and skipped["not_flagged"] == 1 and skipped["no_rank"] == 1


def test_uses_the_rank_known_by_the_decision_day_and_settles():
    ranks = pd.concat([RANKS, pd.DataFrame({"key": ["bplayer"], "date": pd.to_datetime(["2026-11-06"]), "rank": [60.0]})])
    q = pd.DataFrame(_q("E2", "2026-11-05T09:00Z", (0.58, 0.60), (0.40, 0.43)))
    d, _ = tr.decisions(q, {}, REG, {"E2-A": "A Player", "E2-B": "B Player"}, ranks)
    assert d.iloc[0]["opponent_rank"] == 150                              # the later rank (60) is not used
    s = tr.settle(d, pd.DataFrame(), lambda p: {"market": {"result": "no"}})
    assert abs(s.iloc[0]["pnl_per_contract"] - (1 - 0.42 - s.iloc[0]["fee_per_contract"])) < 1e-12
    assert tr.summary(s, {})["settled"] == 1
