"""The research toolkit: each general check must catch the kind of bug it exists for (shown with
a deliberately broken pipeline) and pass a correct one."""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

from research_kit import checks
from research_kit.core import back_bets, boot_mean, coin_flip, devig, log_loss, logit, orient, walk_forward


def _raw(n=4000, seed=0):
    """A winner-first source with bet365-like ladder odds (few distinct values)."""
    g = np.random.default_rng(seed)
    ladder = np.array([1.36, 1.44, 1.5, 1.57, 1.66, 1.72, 1.83, 2.0, 2.2, 2.38, 2.62, 3.0])
    i = g.integers(0, len(ladder), n)
    ow = ladder[i]
    ol = ladder[len(ladder) - 1 - i]
    return pd.DataFrame({"w_odds": ow, "l_odds": ol, "year": g.integers(2015, 2025, n)})


def _swap(raw):
    return raw.rename(columns={"w_odds": "l_odds", "l_odds": "w_odds"})


def _build_ok(raw, flip):
    oa, ob = orient(raw["w_odds"], raw["l_odds"], flip)
    return pd.DataFrame({"p": devig(oa, ob), "y": (~flip).astype(int)})


def _build_one_minus_p(raw, flip):           # the 2026-10-31 bug
    pw = devig(raw["w_odds"], raw["l_odds"])
    return pd.DataFrame({"p": np.where(flip, 1 - pw, pw), "y": (~flip).astype(int)})


def test_swap_source_catches_the_one_minus_p_leak_and_passes_the_fix():
    raw = _raw()
    flip = coin_flip(len(raw), 1)
    assert checks.swap_source(_build_ok, raw, _swap, flip, ["p"])["pass"]
    bad = checks.swap_source(_build_one_minus_p, raw, _swap, flip, ["p"])
    assert not bad["pass"] and bad["columns_differing"] == ["p"]


def test_time_travel_catches_features_that_use_later_matches():
    g = np.random.default_rng(0)
    hist = pd.DataFrame({"player": g.integers(0, 20, 3000), "t": np.sort(g.random(3000) * 100), "x": g.random(3000)})
    targets = pd.DataFrame({"player": g.integers(0, 20, 200), "cut": g.random(200) * 100})

    def past_only(h, t):
        return pd.DataFrame({"f": [h[(h.player == p) & (h.t < c)]["x"].mean() for p, c in zip(t.player, t.cut)]})

    def all_history(h, t):                    # look-ahead: averages every match, later ones too
        return pd.DataFrame({"f": [h[h.player == p]["x"].mean() for p in t.player]})

    assert checks.time_travel(past_only, hist, targets, "t", "cut", ["f"], n=40)["pass"]
    assert not checks.time_travel(all_history, hist, targets, "t", "cut", ["f"], n=40)["pass"]


def _runner(p_mkt, years, use_feature=True):
    """A minimal test: logistic on logit(market) (+ feature) vs market-only, walk-forward."""
    def run(y, z):
        X0 = logit(p_mkt)[:, None]
        X1 = X0 if (z is None or not use_feature) else np.c_[X0, z]

        def fp(X):
            return lambda tr, te: LogisticRegression(C=1.0).fit(X[tr], y[tr]).predict_proba(X[te])[:, 1]
        p0 = walk_forward(years, range(2020, 2025), fp(X0))
        p1 = walk_forward(years, range(2020, 2025), fp(X1))
        ok = np.isfinite(p1)
        return {"delta": boot_mean(log_loss(y[ok], p1[ok]) - log_loss(y[ok], p0[ok]))}
    return run


def test_planted_edge_is_found_by_a_working_test_and_missed_by_a_broken_one():
    g = np.random.default_rng(3)
    n = 20000
    p_mkt = np.clip(g.beta(4, 4, n), 0.05, 0.95)
    years = g.integers(2015, 2025, n)
    assert checks.planted_edge(_runner(p_mkt, years), p_mkt, size=0.3)["pass"]
    assert not checks.planted_edge(_runner(p_mkt, years, use_feature=False), p_mkt, size=0.3)["pass"]


def test_market_null_passes_when_features_carry_nothing():
    g = np.random.default_rng(4)
    n = 20000
    p_mkt = np.clip(g.beta(4, 4, n), 0.05, 0.95)
    years = g.integers(2015, 2025, n)
    assert checks.market_null(_runner(p_mkt, years), p_mkt)["pass"]


def test_shuffled_null_catches_a_model_that_sees_the_result():
    g = np.random.default_rng(5)
    n, years = 8000, g.integers(2015, 2025, 8000)
    y = (g.random(n) < 0.5).astype(int)
    honest = lambda ys: np.full(len(ys), 0.5)                                  # noqa: E731
    leaky = lambda ys: np.where(ys == 1, 0.8, 0.2)                             # noqa: E731
    assert checks.shuffled_null(honest, y, years)["pass"]
    assert not checks.shuffled_null(leaky, y, years)["pass"]


def test_boot_range_is_a_real_range_with_and_without_clusters():
    x = np.random.default_rng(6).normal(0, 1, 500)
    m, lo, hi = boot_mean(x)
    assert lo < m < hi and hi - lo > 0.1                 # the per-draw-reseeded bug collapsed this to a point
    m2, lo2, hi2 = boot_mean(x, cluster=np.repeat(np.arange(50), 10))
    assert abs(m2 - m) < 1e-12 and lo2 < m2 < hi2


def test_devig_orientation_and_bets():
    assert abs(devig(2.0, 2.0) - 0.5) < 1e-12 and np.isnan(devig(1.0, 2.0))
    a, b = orient(np.array([1, 2]), np.array([3, 4]), np.array([False, True]))
    assert list(a) == [1, 4] and list(b) == [3, 2]
    r = back_bets(np.array([1, 0]), np.array([0.6, 0.6]), np.array([2.0, 2.0]), np.array([2.0, 2.0]), edge=0.05, commission=0.02)
    assert r.n == 2 and abs(r.roi - ((0.98) - 1) / 2) < 1e-12


def test_alarms_flag_both_directions():
    assert checks.alarms((-0.02, -0.03, -0.01))[0].startswith("TOO GOOD")
    assert checks.alarms((0.006, 0.004, 0.008))[0].startswith("TOO BAD")
    assert checks.alarms((0.0005, -0.001, 0.002)) == []
