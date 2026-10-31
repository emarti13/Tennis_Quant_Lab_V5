"""Shared pieces every research test uses: orientation, de-vig, log loss, walk-forward splits,
resampled ranges, and bet simulation with fees. One tested copy, so each test does not
re-implement (and re-break) them.

Conventions
- A match has two sides, A and B. y = 1 if A won.
- Sources that list the winner first (Kaggle, Sackmann) are oriented by a seeded coin flip,
  and every A/B value is taken from the flipped columns: never computed as 1 - (B's value).
- Probabilities are A's chance unless named otherwise.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

import numpy as np
import pandas as pd

EPS = 1e-6


# ---------------------------------------------------------------- orientation and prices
def coin_flip(n: int, seed: int) -> np.ndarray:
    """True = the source's second player (the loser, in winner-first sources) becomes A."""
    return np.random.default_rng(seed).random(n) < 0.5


def orient(first: np.ndarray, second: np.ndarray, flip: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(A, B) values from the source's first/second columns."""
    first, second = np.asarray(first), np.asarray(second)
    return np.where(flip, second, first), np.where(flip, first, second)


def devig(odds_a, odds_b) -> np.ndarray:
    """Multiplicative de-vig of decimal odds: A's fair probability. NaN unless both odds > 1."""
    oa, ob = np.asarray(odds_a, float), np.asarray(odds_b, float)
    good = (oa > 1) & (ob > 1)
    with np.errstate(divide="ignore", invalid="ignore"):
        p = (1 / oa) / (1 / oa + 1 / ob)
    return np.where(good, p, np.nan)


def logit(p) -> np.ndarray:
    p = np.clip(np.asarray(p, float), 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def log_loss(y, p) -> np.ndarray:
    """Per-row log loss."""
    y, p = np.asarray(y, float), np.clip(np.asarray(p, float), EPS, 1 - EPS)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


# ---------------------------------------------------------------- ranges
def boot_mean(x, n: int = 2000, seed: int = 0, cluster=None) -> tuple[float, float, float]:
    """Mean and 95% range, resampling rows (or whole clusters, e.g. a match's several rows).
    Each resample draws a fresh index (a seeded generator created once, not per draw)."""
    x = np.asarray(x, float)
    g = np.random.default_rng(seed)
    if len(x) == 0:
        return float("nan"), float("nan"), float("nan")
    if cluster is None:
        means = np.array([x[g.integers(0, len(x), len(x))].mean() for _ in range(n)])
    else:
        codes, uniq = pd.factorize(pd.Series(cluster))
        sums = np.bincount(codes, weights=x)
        cnts = np.bincount(codes).astype(float)
        means = np.empty(n)
        for i in range(n):
            pick = g.integers(0, len(uniq), len(uniq))
            means[i] = sums[pick].sum() / cnts[pick].sum()
    lo, hi = np.percentile(means, [2.5, 97.5])
    return float(x.mean()), float(lo), float(hi)


# ---------------------------------------------------------------- walk-forward
def walk_forward(years: np.ndarray, test_years: Iterable[int], fit_predict: Callable[[np.ndarray, np.ndarray], np.ndarray],
                 first_train_year: int | None = None, min_train: int = 500) -> np.ndarray:
    """Out-of-sample predictions: each test year trained only on earlier years.
    fit_predict(train_mask, test_mask) -> predictions for test rows. NaN outside test years."""
    years = np.asarray(years)
    pred = np.full(len(years), np.nan)
    for yr in test_years:
        tr = years < yr
        if first_train_year is not None:
            tr &= years >= first_train_year
        te = years == yr
        if tr.sum() < min_train or te.sum() == 0:
            continue
        pred[te] = fit_predict(tr, te)
    return pred


# ---------------------------------------------------------------- betting
def kalshi_taker_fee(price) -> np.ndarray:
    """Kalshi taker fee per contract (dollars), price in dollars: 0.07 * P * (1 - P), rounded up
    to the cent per order in reality (not modelled here)."""
    p = np.asarray(price, float)
    return 0.07 * p * (1 - p)


@dataclass
class BetResult:
    n: int
    roi: float
    lo: float
    hi: float

    def as_dict(self) -> dict:
        return {"n": self.n, "roi": round(self.roi, 4), "range": [round(self.lo, 4), round(self.hi, 4)]}


def back_bets(y, p_model, odds_a, odds_b, edge: float, commission: float = 0.0, seed: int = 0) -> BetResult:
    """Back the side whose model probability beats the price's implied probability by `edge`
    (one bet per row, 1 unit). commission: share of net winnings taken (exchange style)."""
    y, p = np.asarray(y), np.asarray(p_model, float)
    oa, ob = np.asarray(odds_a, float), np.asarray(odds_b, float)
    ea, eb = p - 1 / oa, (1 - p) - 1 / ob
    side_a = (ea >= edge) & (ea >= eb) & np.isfinite(ea)
    side_b = (eb >= edge) & (eb > ea) & np.isfinite(eb)
    bet = side_a | side_b
    won = np.where(side_a, y == 1, y == 0)
    odds = np.where(side_a, oa, ob)
    pnl = np.where(won, (odds - 1) * (1 - commission), -1.0)[bet]
    if len(pnl) == 0:
        return BetResult(0, float("nan"), float("nan"), float("nan"))
    m, lo, hi = boot_mean(pnl, seed=seed)
    return BetResult(int(len(pnl)), m, lo, hi)
