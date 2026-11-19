"""The in-play maker replay: quotes only strictly inside the market, fills only from real trades."""
import pandas as pd
import pytest

from scripts import track_inplay_maker as M


def test_quotes_are_strictly_better_than_the_market_and_respect_the_position_cap():
    assert M.quotes_for(0.50, 0.45, 0.55, 0) == (0.48, 0.52)
    assert M.quotes_for(0.50, 0.48, 0.52, 0) == (None, None)          # would only join the market
    assert M.quotes_for(0.50, 0.45, 0.55, 45) == (None, 0.52)         # long 45: no more buying
    assert M.quotes_for(0.97, 0.90, 0.99, 0) == (None, None)          # outside 5-95c


def test_fills_come_only_from_trades_at_or_through_our_price():
    t0 = pd.Timestamp("2026-11-20T10:00:00Z")
    tr = pd.DataFrame([{"t": t0 + pd.Timedelta(seconds=2), "yes_price": 0.47, "count": 4.0, "taker_side": "no"},   # sells through our bid
                       {"t": t0 + pd.Timedelta(seconds=3), "yes_price": 0.50, "count": 9.0, "taker_side": "no"},   # above our bid: no fill
                       {"t": t0 + pd.Timedelta(seconds=4), "yes_price": 0.53, "count": 20.0, "taker_side": "yes"},  # buys through our ask
                       {"t": t0 + pd.Timedelta(seconds=12), "yes_price": 0.40, "count": 5.0, "taker_side": "no"}])  # after the interval
    f = M.fills_in(tr, t0, t0 + pd.Timedelta(seconds=10), 0.48, 0.52, 10.0, 10.0)
    assert [(s, p, q) for s, p, q, _ in f] == [("buy", 0.48, 4.0), ("sell", 0.52, 10.0)]
