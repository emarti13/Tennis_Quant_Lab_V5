"""The market-following in-play maker: 1c inside the market on calm points, filled only by real trades."""
import pandas as pd
import pytest

from research_kit import inplay as ip
from scripts import track_inplay_maker as M


def test_quotes_improve_the_market_by_a_cent_and_respect_the_cap_and_spread():
    assert M.quotes_for(0.45, 0.50, 0) == (0.46, 0.49)
    assert M.quotes_for(0.48, 0.50, 0) == (None, None)               # spread under 3c
    assert M.quotes_for(0.45, 0.50, 45) == (None, 0.49)              # long 45: no more buying


def test_next_point_swing_is_small_early_and_large_on_big_points():
    pa, pb = ip.solve_serve(0.5, 0.64)
    early = M.next_point_swing(pa, pb, (0, 0, 0, 0, 0, 0, True), 3, 7)       # 0-0, first point of the match
    bp_deciding = M.next_point_swing(pa, pb, (1, 1, 5, 5, 2, 3, True), 3, 7)  # deciding set 5-5, 30-40
    assert early < 0.04 < bp_deciding
    tb = M.next_point_swing(pa, pb, (1, 1, 6, 6, 5, 6, True), 3, 7)           # match point in the tie-break
    assert tb > 0.4


def test_fills_come_only_from_trades_at_or_through_our_price():
    t0 = pd.Timestamp("2026-11-20T10:00:00Z")
    tr = pd.DataFrame([{"t": t0 + pd.Timedelta(seconds=2), "yes_price": 0.46, "count": 4.0, "taker_side": "no"},
                       {"t": t0 + pd.Timedelta(seconds=3), "yes_price": 0.47, "count": 9.0, "taker_side": "no"},
                       {"t": t0 + pd.Timedelta(seconds=4), "yes_price": 0.49, "count": 20.0, "taker_side": "yes"},
                       {"t": t0 + pd.Timedelta(seconds=12), "yes_price": 0.40, "count": 5.0, "taker_side": "no"}])
    f = M.fills_in(tr, t0, t0 + pd.Timedelta(seconds=10), 0.46, 0.49, 10.0, 10.0)
    assert [(s, p, q) for s, p, q, _ in f] == [("buy", 0.46, 4.0), ("sell", 0.49, 10.0)]
