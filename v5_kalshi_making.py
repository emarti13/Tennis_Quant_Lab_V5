"""Quote and fill rules for the Kalshi market-making study (roadmap Phase 4).

One code path for the offline replay (scripts/simulate_kalshi_making.py) and the paper run
(scripts/paper_kalshi_making.py): both turn the best bid/ask standing before a trade into
our quotes, and decide from the trade itself whether we were filled.

- Fair price: Kalshi's own mid, only when the book is two-sided and no wider than 20 cents.
- Quotes: buy at fair - h rounded down to the cent, sell at fair + h rounded up, never
  crossing the standing best bid/ask (that would be a taker trade).
- Fills, conservatively: a taker buying YES at x fills our sell at s when x > s, or x == s and
  s was strictly better than the standing best ask (we were first in line); takers selling
  likewise for our buy. Each trade fills at most its own size and SIZE; a side stops once
  the net position reaches LIMIT. Takers our better price might have attracted are not
  counted.
- Everything stops one minute before the start (STOP_BEFORE).
- Fees: the taker pays the taker fee, not us. Maker fee: none, or Kalshi's maker schedule
  (MAKER_FEE_RATE * contracts * P * (1 - P)) as a check, since the fee on tennis markets
  is not confirmed.

Nothing here sends an order.
"""
from __future__ import annotations

import math
from bisect import bisect_right

import pandas as pd

SIZE = 100                  # contracts per quote
LIMIT = 300                 # net contracts per market before a side stops quoting
MAX_SPREAD = 0.20           # wider books give no fair price
MAKER_FEE_RATE = 0.0175
STOP_BEFORE = pd.Timedelta(minutes=1)


def kalshi_mid(best_bid: float | None, best_ask: float | None) -> float | None:
    """Kalshi's mid, or None when the book is one-sided, crossed or wider than MAX_SPREAD."""
    if best_bid and best_ask and 0 < best_bid < best_ask < 1 and best_ask - best_bid <= MAX_SPREAD:
        return (best_bid + best_ask) / 2
    return None


def quotes(fair: float, h: float, best_bid: float | None, best_ask: float | None,
           lean: float = 0.0) -> tuple[float, float]:
    """Our resting (buy, sell) prices for half-width h around fair (+ lean)."""
    f = min(max(fair + lean, 0.02), 0.98)
    bid, ask = math.floor(round((f - h) * 100, 6)) / 100, math.ceil(round((f + h) * 100, 6)) / 100
    if best_ask is not None:
        bid = min(bid, round(best_ask - 0.01, 2))
    if best_bid is not None:
        ask = max(ask, round(best_bid + 0.01, 2))
    return bid, ask


def fill(x: float, count: float, taker: str, bid: float, ask: float, best_bid: float | None,
         best_ask: float | None, pos: float) -> tuple[str, float, float] | None:
    """(side 'buy'/'sell', price, contracts) if this trade fills one of our quotes, else None."""
    if taker == "yes" and pos > -LIMIT and 0 < ask < 1:              # taker buys YES: our sell
        first = best_ask is None or ask < best_ask
        if x > ask or (x == ask and first):
            return "sell", ask, min(count, SIZE, LIMIT + pos)
    elif taker == "no" and pos < LIMIT and 0 < bid < 1:              # taker sells YES: our buy
        first = best_bid is None or bid > best_bid
        if x < bid or (x == bid and first):
            return "buy", bid, min(count, SIZE, LIMIT - pos)
    return None


def signed(side: str, q: float) -> float:
    return q if side == "buy" else -q


def pnl(fills: list, won: float, maker_fee: bool) -> tuple[float, float, float]:
    """(profit, contracts traded, net position) of fills [(side, price, contracts)]. `won` is
    the settlement (1/0), or a mark price (Kalshi's last mid) to value the fills without the
    match result."""
    total, vol, pos = 0.0, 0.0, 0.0
    for side, price, q in fills:
        total += q * ((won - price) if side == "buy" else (price - won))
        if maker_fee:
            total -= MAKER_FEE_RATE * q * price * (1 - price)
        vol += q
        pos += signed(side, q)
    return total, vol, pos


class MarketBook:
    """One market's book snapshots, positions and fills, fed in time order.

    The paper run feeds live snapshots and trades; the replay feeds 1-minute candles and the
    stored trades. Both get the same fills from the same rules. A trade uses the latest
    snapshot taken at or before it; with `max_age`, a snapshot older than that gives no
    quote (fail closed on a feed gap)."""

    def __init__(self, start: pd.Timestamp | None, half_widths, max_age: pd.Timedelta | None = None):
        # No start: the caller moves `stop` (the paper run, from Kalshi's live match status).
        self.stop = start - STOP_BEFORE if start is not None else pd.Timestamp.max.tz_localize("UTC")
        self.half_widths = tuple(half_widths)
        self.max_age = max_age
        self.snaps: list[tuple[pd.Timestamp, float | None, float | None]] = []
        self._times: list[pd.Timestamp] = []
        self.pos = {h: 0.0 for h in self.half_widths}
        self.fills: dict[float, list] = {h: [] for h in self.half_widths}

    def snapshot(self, ts: pd.Timestamp, best_bid: float | None, best_ask: float | None) -> None:
        if ts > self.stop:
            return
        if self.snaps and ts < self.snaps[-1][0]:
            raise ValueError("snapshots must arrive in time order")
        self.snaps.append((ts, best_bid, best_ask))
        self._times.append(ts)

    def standing(self, ts: pd.Timestamp):
        i = bisect_right(self._times, ts) - 1
        return self.snaps[i] if i >= 0 else None

    def trade(self, ts: pd.Timestamp, x: float, count: float, taker: str) -> tuple[str, list]:
        """Evaluate one taker trade: (status, [(h, side, price, contracts, position after)])."""
        if ts > self.stop:
            return "after_stop", []
        snap = self.standing(ts)
        if snap is None:
            return "no_book", []
        if self.max_age is not None and ts - snap[0] > self.max_age:
            return "stale_book", []
        _, best_bid, best_ask = snap
        fair = kalshi_mid(best_bid, best_ask)
        if fair is None:
            return "no_fair", []
        out = []
        for h in self.half_widths:
            bid, ask = quotes(fair, h, best_bid, best_ask)
            f = fill(x, count, taker, bid, ask, best_bid, best_ask, self.pos[h])
            if f is not None:
                self.fills[h].append(f)
                self.pos[h] += signed(f[0], f[2])
                out.append((h, *f, self.pos[h]))
        return "evaluated", out

    def last_mid(self) -> float | None:
        """Kalshi's mid standing at the stop (the mark)."""
        for ts, b, a in reversed(self.snaps):
            if ts <= self.stop and b and a and b < a:
                return (b + a) / 2
        return None
