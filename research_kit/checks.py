"""General checks every research result must pass, whatever the bug would be.

swap_source     Relabel the source (swap its first/second columns, invert the result) and rebuild:
                the model's inputs for the same oriented A/B pair must be bitwise identical.
                A pipeline that "knows" which side the source listed first fails this.
time_travel     Rebuild features for sampled rows from history cut at each row's decision time:
                they must equal the normal build. Any use of later data fails this.
planted_edge    Replace outcomes with draws from (market + a planted feature of known size):
                the test must find the planted improvement. A test that cannot find a real
                edge cannot be trusted when it reports none.
market_null     Replace outcomes with draws from the market itself (the market is the truth):
                the test must find no improvement and bets must lose about the margin.
shuffled_null   Shuffle the real outcomes: every model must be no better than a coin.
alarms          Flag results that are too good (audit for a leak) or worse than the plain market
                by more than chance (audit for a bug hiding an edge).
"""
from __future__ import annotations

from typing import Callable

import numpy as np
import pandas as pd

from research_kit.core import boot_mean, log_loss, logit


def _sigmoid(x):
    return 1 / (1 + np.exp(-x))


def frames_identical(a: pd.DataFrame, b: pd.DataFrame, cols: list[str]) -> list[str]:
    """Columns whose values differ in any bit (NaN equal to NaN)."""
    bad = []
    for c in cols:
        x, y = a[c].to_numpy(), b[c].to_numpy()
        if x.dtype.kind in "fc" or y.dtype.kind in "fc":
            xf, yf = x.astype(float), y.astype(float)
            same = (xf == yf) | (np.isnan(xf) & np.isnan(yf))
        else:
            same = (pd.Series(x).astype(str).values == pd.Series(y).astype(str).values)
        if not same.all():
            bad.append(c)
    return bad


def swap_source(build: Callable[[pd.DataFrame, np.ndarray], pd.DataFrame], raw: pd.DataFrame,
                swap: Callable[[pd.DataFrame], pd.DataFrame], flip: np.ndarray, input_cols: list[str]) -> dict:
    """build(raw, flip) -> one row per raw row, oriented; must not depend on which side the source
    put first. swap(raw) exchanges the source's first/second columns (and its result). Building
    swap(raw) with ~flip puts the same player as A for every row: inputs must be identical."""
    a = build(raw, flip).reset_index(drop=True)
    b = build(swap(raw), ~flip).reset_index(drop=True)
    if len(a) != len(b):
        return {"pass": False, "reason": f"row counts differ: {len(a)} vs {len(b)}"}
    bad = frames_identical(a, b, input_cols)
    y_ok = "y" not in a or bool((a["y"].to_numpy() != b["y"].to_numpy()).all())
    return {"pass": not bad and y_ok, "columns_differing": bad, "labels_inverted": y_ok, "rows": len(a)}


def time_travel(features_at: Callable[[pd.DataFrame, pd.DataFrame], pd.DataFrame], history: pd.DataFrame,
                targets: pd.DataFrame, time_col: str, cut_col: str, feature_cols: list[str], n: int = 300,
                seed: int = 0) -> dict:
    """features_at(history, targets) -> features for targets (same order). For n sampled targets,
    recompute from history strictly before each target's cut time and compare."""
    full = features_at(history, targets).reset_index(drop=True)
    g = np.random.default_rng(seed)
    idx = g.choice(len(targets), size=min(n, len(targets)), replace=False)
    mism = 0
    bad_cols: set = set()
    for i in idx:
        t = targets.iloc[[i]]
        cut = t[cut_col].iloc[0]
        h = history[history[time_col] < cut]
        one = features_at(h, t).reset_index(drop=True)
        ref = full.iloc[[i]].reset_index(drop=True)
        if len(one) != len(ref):
            mism += 1
            continue
        diff = [c for c in feature_cols if not np.allclose(np.asarray(one[c], float), np.asarray(ref[c], float), equal_nan=True, rtol=1e-9, atol=1e-12)]
        if diff:
            mism += 1
            bad_cols.update(diff)
    return {"pass": mism == 0, "checked": int(len(idx)), "mismatched_rows": mism, "columns": sorted(bad_cols)}


def planted_edge(run: Callable[[np.ndarray, np.ndarray | None], dict], p_market: np.ndarray, size: float = 0.25,
                 seed: int = 0) -> dict:
    """run(y, planted_feature) -> {'delta': (mean, lo, hi)} of the test's main comparison
    (model with features minus market-only; negative = better). Outcomes are drawn from
    sigmoid(logit(p_market) + size * z), z ~ N(0,1), and z is given to the model as a feature.
    The expected improvement is computed exactly from the planted truth."""
    g = np.random.default_rng(seed)
    z = g.standard_normal(len(p_market))
    p_true = _sigmoid(logit(p_market) + size * z)
    y = (g.random(len(p_market)) < p_true).astype(int)
    expected = float((_kl(p_true, p_market)).mean())          # best-case improvement in log loss
    got = run(y, z)
    mean = got["delta"][0]
    found = got["delta"][2] < 0
    return {"pass": bool(found and -mean >= 0.25 * expected), "expected_improvement": round(expected, 5),
            "found_delta": [round(v, 5) for v in got["delta"]], "size": size}


def _kl(p, q):
    p, q = np.clip(p, 1e-9, 1 - 1e-9), np.clip(q, 1e-9, 1 - 1e-9)
    return p * np.log(p / q) + (1 - p) * np.log((1 - p) / (1 - q))


def market_null(run: Callable[[np.ndarray, np.ndarray | None], dict], p_market: np.ndarray, seed: int = 1) -> dict:
    """Outcomes drawn from the market itself: the features carry no information, so the test's
    improvement must not be significantly negative."""
    g = np.random.default_rng(seed)
    y = (g.random(len(p_market)) < p_market).astype(int)
    got = run(y, None)
    return {"pass": bool(got["delta"][1] > -1e-4 or got["delta"][0] > -1e-4), "found_delta": [round(v, 5) for v in got["delta"]]}


def shuffled_null(run_model_only: Callable[[np.ndarray], np.ndarray], y: np.ndarray, years: np.ndarray, seed: int = 2) -> dict:
    """Outcomes shuffled within each year: a model without the market must score no better
    than a coin (log loss ln 2) on its predictions."""
    g = np.random.default_rng(seed)
    ys = y.copy()
    for yr in np.unique(years):
        m = years == yr
        ys[m] = g.permutation(ys[m])
    p = run_model_only(ys)
    ok = np.isfinite(p)
    mean, lo, hi = boot_mean(log_loss(ys[ok], p[ok]) - np.log(2))
    return {"pass": bool(lo > -0.003), "model_minus_coin": [round(mean, 5), round(lo, 5), round(hi, 5)]}


def alarms(delta: tuple[float, float, float], roi: float | None = None) -> list[str]:
    """delta: (mean, lo, hi) of model-with-features minus market-only log loss."""
    out = []
    if delta[0] < -0.01:
        out.append("TOO GOOD: beats the market by more than 0.01 log loss; audit for a leak")
    if delta[1] > 0.003:
        out.append("TOO BAD: worse than the plain market beyond chance by >0.003; audit for a bug hiding an edge (or overfitting)")
    if roi is not None and roi > 0.10:
        out.append("TOO GOOD: ROI above 10%; audit for a leak")
    return out


def known_answers(y: np.ndarray, p_market: np.ndarray, expect_ll: tuple[float, float]) -> dict:
    """The market's log loss must be in its known range, and after orientation A must win about
    half the time."""
    ll = float(log_loss(y, p_market).mean())
    share = float(np.mean(y))
    return {"pass": bool(expect_ll[0] <= ll <= expect_ll[1] and 0.47 <= share <= 0.53),
            "market_log_loss": round(ll, 5), "expected_range": list(expect_ll), "A_win_share": round(share, 4)}
