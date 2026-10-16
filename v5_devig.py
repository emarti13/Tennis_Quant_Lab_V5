"""Margin removal (de-vig) and the cautious edge rule: one function for every caller.

Rebuild plan Step 3 (user decision 2026-10-13); spec docs/superpowers/specs/
2026-10-16-market-data-layer-design.md §2.5.

A book's decimal prices imply probabilities p_i = 1/price_i that sum to more than 1 (the
margin). `devig(prices, lam)` removes it on one scale, the Box-Cox family: every implied
probability is moved by the same amount c in the transformed space
    g(q) = g(p) - c,   g(x) = (x**lam - 1) / lam   (log x when lam = 0),
with c chosen so the fair probabilities q_i sum to 1.
lam = 0 is "same share off each side" (multiplicative); lam = 1 is "same amount off each
side" (additive); larger lam takes more of the margin from the longshot. The "power"
method (q_i = p_i**k) is offered separately; for two-way prices it sits near lam = 1.5.
Each book's lam is measured on our own closing prices (scripts/measure_devig.py).

Cautious edge rule (approved 2026-10-13): an edge is judged against the least favourable of
the multiplicative, additive and power fair probabilities for the side being bet (and the
book's own lam, when given), so the method choice can never create an edge.

Exchanges (Kalshi): the fair price is the bid-ask midpoint; expected value uses the price
paid plus Kalshi's taker fee (CLAUDE.md: include fees).
Everything fails closed: an invalid price or an impossible fit raises ValueError.
"""
from __future__ import annotations

import math
from typing import Sequence

LAM_MAX = 5.0
KALSHI_TAKER_FEE_RATE = 0.07   # fee per contract = ceil(rate * P * (1 - P), to the cent); check Kalshi's schedule


def implied(prices: Sequence[float]) -> list[float]:
    out = []
    for x in prices:
        x = float(x)
        if not math.isfinite(x) or x <= 1.0:
            raise ValueError(f"invalid decimal price {x}")
        out.append(1.0 / x)
    if len(out) < 2:
        raise ValueError("need every side of the market")
    return out


def _shift(p: float, lam: float, c: float) -> float:
    if abs(lam) < 1e-9:
        return p * math.exp(-c)
    base = p ** lam - lam * c
    if base <= 0:
        return 0.0
    return base ** (1.0 / lam)


def devig(prices: Sequence[float], lam: float = 0.0) -> list[float]:
    """Fair probabilities on the Box-Cox scale (lam = 0 multiplicative, 1 additive)."""
    if not 0.0 <= lam <= LAM_MAX:
        raise ValueError(f"lam {lam} outside [0, {LAM_MAX}]")
    p = implied(prices)
    if lam < 1e-9:
        total = sum(p)
        return [x / total for x in p]
    # The shifted probabilities fall as c rises: bracket and bisect for a sum of 1.
    f = lambda c: sum(_shift(x, lam, c) for x in p)
    lo, hi = -1.0, 1.0
    while f(hi) > 1:
        hi *= 2
    while f(lo) < 1:
        lo *= 2
        if lo < -1e6:
            raise ValueError("de-vig did not converge")
    for _ in range(200):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if f(mid) > 1 else (lo, mid)
    q = [_shift(x, lam, (lo + hi) / 2) for x in p]
    if any(v <= 0 for v in q):
        raise ValueError(f"lam={lam} removes a whole side's probability")
    s = sum(q)
    return [v / s for v in q]


def devig_power(prices: Sequence[float]) -> list[float]:
    """Power method: q_i = p_i**k with k chosen so the q_i sum to 1."""
    p = implied(prices)
    lo, hi = 0.01, 100.0
    for _ in range(200):
        k = (lo + hi) / 2
        if sum(x ** k for x in p) > 1:
            lo = k
        else:
            hi = k
    q = [x ** ((lo + hi) / 2) for x in p]
    s = sum(q)
    return [v / s for v in q]


def cautious_fair(prices: Sequence[float], side: int, book_lam: float | None = None) -> float:
    """The highest fair probability for `side` among multiplicative, additive, power (and the
    book's own lam): the least favourable benchmark for a bet on that side."""
    candidates = [devig(prices, 0.0)[side], devig_power(prices)[side]]
    for lam in (1.0, book_lam):
        if lam is None:
            continue
        try:
            candidates.append(devig(prices, lam)[side])
        except ValueError:
            # additive can wipe out a longshot; that method then says nothing about this side
            continue
    return max(candidates)


def cautious_edge(model_probability: float, prices: Sequence[float], side: int, book_lam: float | None = None) -> float:
    """Model probability minus the least favourable fair probability (can be negative)."""
    if not 0.0 < model_probability < 1.0:
        raise ValueError(f"model probability {model_probability} outside (0, 1)")
    return model_probability - cautious_fair(prices, side, book_lam)


def expected_value(model_probability: float, price: float) -> float:
    """EV per unit staked at a decimal price."""
    implied([price, 2.0])          # validates the price
    return model_probability * float(price) - 1.0


def exchange_fair(bid: float, ask: float) -> float:
    if not (0.0 < bid < ask < 1.0):
        raise ValueError(f"need 0 < bid < ask < 1, got {bid}, {ask}")
    return (bid + ask) / 2.0


def kalshi_fee(price: float, contracts: int = 1) -> float:
    """Kalshi taker fee in dollars for `contracts` bought at `price` (rounded up to the cent)."""
    if not 0.0 < price < 1.0:
        raise ValueError(f"Kalshi price {price} outside (0, 1)")
    return math.ceil(KALSHI_TAKER_FEE_RATE * contracts * price * (1.0 - price) * 100 - 1e-9) / 100.0


def kalshi_ev(model_probability: float, ask: float, contracts: int = 1) -> float:
    """EV per dollar spent buying YES at `ask`, fees included."""
    cost = ask * contracts + kalshi_fee(ask, contracts)
    return (model_probability * contracts - cost) / cost
