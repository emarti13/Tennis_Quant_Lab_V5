"""The two analyses the Gate 1 report lists as missing (docs/superpowers/specs/2026-10-23-gate1-segment-report.md §4).

Gap 1: Pinnacle calibration, 2026 fixtures before the seal.
  * By family (ATP, WTA, WTA125, Challenger), surface and qualifying (where the fixture joins
    our match table), favourite price band, and checkpoint (open, t24h, t6h, t1h, close).
  * Calibration of the close: observed vs predicted favourite win rate by band; logistic slope
    of the outcome on logit(p) (1 = calibrated, < 1 = overconfident).
Gap 2: does the production-parameter Elo add information beyond Pinnacle's close?
  * logit p = a·logit p_pinnacle + b·logit p_elo (roadmap §4, Phase 1), by segment, with a
    bootstrap interval for b; Elo needs both players >= 18 rated matches (production minimum).
  * Chronological check: fit on fixtures starting before 2026-06-01, measure the log-loss gain
    over Pinnacle's close on fixtures from 2026-06-01.
Elo per fixture: build_fixture_elo.py (from the blind replication; leak-free, matches
v5_baseline_elo exactly). Winners: v5_market_results.load_fixture_winners, voids dropped.

Run from the repo root: python research_tests/gate1/build_fixture_elo.py (once), then
python research_tests/gate1/run_gate1_gaps.py -> results.json
"""
from __future__ import annotations

import glob
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "research_tests"))
from qa import QA  # noqa: E402
from v5_market_results import load_fixture_winners  # noqa: E402

SEAL = pd.Timestamp("2026-10-13", tz="UTC")
SPLIT = pd.Timestamp("2026-06-01", tz="UTC")
SCRATCH = os.environ.get("FS_SCRATCH", "/tmp/claude-0/-home-user-Tennis-Quant-Lab-V5/a0609b44-84ba-59ef-a5f1-f66b68d375ec/scratchpad")
RNG = np.random.default_rng(1013)
CPS = ["open", "t24h", "t6h", "t1h", "close"]
EPS = 1e-6


def lg(p):
    p = np.clip(p, EPS, 1 - EPS)
    return np.log(p / (1 - p))


def ll(y, p):
    p = np.clip(p, EPS, 1 - EPS)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def logit_fit(X, y, iters=50):
    b = np.zeros(X.shape[1])
    for _ in range(iters):
        p = 1 / (1 + np.exp(-X @ b))
        H = (X * (p * (1 - p))[:, None]).T @ X + 1e-9 * np.eye(X.shape[1])
        step = np.linalg.solve(H, X.T @ (y - p))
        b += step
        if np.abs(step).max() < 1e-10:
            break
    return b


def boot_coef(X, y, j, reps=500):
    n = len(y)
    est = logit_fit(X, y)[j]
    bs = [logit_fit(X[i], y[i])[j] for i in (RNG.integers(0, n, n) for _ in range(reps))]
    return {"est": round(float(est), 3), "lo": round(float(np.percentile(bs, 2.5)), 3),
            "hi": round(float(np.percentile(bs, 97.5)), 3), "n": int(n)}


def load():
    fx = pd.concat([pd.read_csv(f) for f in sorted(glob.glob(os.path.join(ROOT, "market_history/fixtures/*.csv")))])
    fx = fx[fx.resolution == "ok"].drop_duplicates("fixture_id", keep="last")
    fx["start"] = pd.to_datetime(fx.cutoff_utc, utc=True)
    fx = fx[fx.start < SEAL].copy()
    fx["family"] = fx.edition_key.astype(str).str.split("|").str[0]
    pp = pd.concat([pd.read_csv(f) for f in sorted(glob.glob(os.path.join(ROOT, "market_history/price_points/*.csv")))])
    pp = pp[(pp.bookmaker == "pinnacle") & (pp.market_group == "moneyline") & pp.fixture_id.isin(fx.fixture_id)]
    pp = pp.drop_duplicates(["fixture_id", "side"], keep="last")
    pp.loc[pp.close_stale.astype(str) == "True", "close_price"] = np.nan
    for cp in CPS:
        w = pp.pivot(index="fixture_id", columns="side", values=f"{cp}_price")
        p1 = (1 / w.p1) / (1 / w.p1 + 1 / w.p2)
        fx[f"p_{cp}"] = fx.fixture_id.map(p1)
    w = load_fixture_winners(fx, base=ROOT)
    w = w[~w.void_for_measurement].drop_duplicates("fixture_id").set_index("fixture_id")
    fx = fx[fx.fixture_id.isin(w.index)].copy()
    fx["y"] = (fx.fixture_id.map(w.winner_side) == "p1").astype(float)
    elo = pd.read_csv(os.path.join(HERE, "elo_fixture_probs.csv")).set_index("fixture_id")
    fx["p_elo"] = fx.fixture_id.map(elo.p_elo)
    fx["elo_ok"] = (fx.fixture_id.map(elo.n1) >= 18) & (fx.fixture_id.map(elo.n2) >= 18)
    mk = pd.read_pickle(os.path.join(SCRATCH, "fs_market.pkl"))[["fixture_id", "surface", "stage"]]
    fx = fx.merge(mk, on="fixture_id", how="left")
    fx["qualifying"] = np.where(fx.stage.isna(), "unknown", np.where(fx.stage == 0, "qualifying", "main draw"))
    return fx


def calibration(d, col):
    p, y = d[col].to_numpy(), d.y.to_numpy()
    fav = np.where(p >= 0.5, p, 1 - p)
    fwin = np.where(p >= 0.5, y, 1 - y)
    bands = [(0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.0)]
    out = {}
    for lo, hi in bands:
        m = (fav >= lo) & (fav < hi)
        if m.sum() < 30:
            continue
        diff = fwin[m] - fav[m]
        bs = [diff[i].mean() for i in (RNG.integers(0, m.sum(), m.sum()) for _ in range(1000))]
        out[f"fav {lo:.1f}-{hi:.1f}"] = {"n": int(m.sum()), "predicted": round(float(fav[m].mean()), 4),
                                         "observed": round(float(fwin[m].mean()), 4),
                                         "obs_minus_pred": round(float(diff.mean()), 4),
                                         "lo": round(float(np.percentile(bs, 2.5)), 4), "hi": round(float(np.percentile(bs, 97.5)), 4)}
    X = np.c_[np.ones(len(y)), lg(p)]
    out["logistic_slope"] = boot_coef(X, y, 1, reps=300)
    out["log_loss"] = round(float(ll(y, p).mean()), 5)
    return out


def info_test(d):
    d = d[d.elo_ok & d.p_close.notna() & d.p_elo.notna()]
    if len(d) < 200:
        return {"n": int(len(d))}
    X = np.c_[lg(d.p_close.to_numpy()), lg(d.p_elo.to_numpy())]
    y = d.y.to_numpy()
    res = {"a_pinnacle": boot_coef(X, y, 0), "b_elo": boot_coef(X, y, 1)}
    tr = (d.start < SPLIT).to_numpy()
    if tr.sum() > 200 and (~tr).sum() > 200:
        coef = logit_fit(X[tr], y[tr])
        pb = 1 / (1 + np.exp(-X[~tr] @ coef))
        g = ll(y[~tr], d.p_close.to_numpy()[~tr]) - ll(y[~tr], pb)
        bs = [g[i].mean() for i in (RNG.integers(0, len(g), len(g)) for _ in range(1000))]
        res["chronological_gain_vs_pinnacle"] = {"fit_before": "2026-06-01", "coef": [round(float(c), 3) for c in coef],
                                                 "n_test": int(len(g)), "gain": round(float(g.mean()), 5),
                                                 "lo": round(float(np.percentile(bs, 2.5)), 5), "hi": round(float(np.percentile(bs, 97.5)), 5)}
    return res


def main():
    fx = load()
    qa = QA("gate1_gaps")
    qa.count("fixtures before the seal with a non-void winner", len(fx))
    qa.check("share with a Pinnacle close", fx.p_close.notna().mean(), 0.80, 1.0)
    qa.check("player1 win share", fx.y.mean(), 0.45, 0.56)
    qa.check("Pinnacle close log loss (all)", ll(fx.y[fx.p_close.notna()], fx.p_close.dropna()).mean(), 0.55, 0.63)
    qa.check("share with an Elo probability", fx.p_elo.notna().mean(), 0.9, 1.0)
    qa.check("share joined to the match table (surface, stage)", fx.surface.notna().mean(), 0.5, 0.95)
    R = {"n": int(len(fx))}
    # checkpoints on fixtures priced at every checkpoint
    allcp = fx.dropna(subset=[f"p_{c}" for c in CPS])
    R["checkpoints_common_fixtures"] = {"n": int(len(allcp)), **{c: round(float(ll(allcp.y, allcp[f"p_{c}"]).mean()), 5) for c in CPS}}
    segs = {"all": fx}
    for f, g in fx.groupby("family"):
        segs[f"family={f}"] = g
    for s, g in fx.groupby("surface"):
        segs[f"surface={s}"] = g
    for q, g in fx.groupby("qualifying"):
        segs[f"draw={q}"] = g
    R["calibration_close"], R["information_elo"] = {}, {}
    for k, g in segs.items():
        g2 = g[g.p_close.notna()]
        if len(g2) >= 200:
            R["calibration_close"][k] = calibration(g2, "p_close")
            R["information_elo"][k] = info_test(g2)
    R["calibration_open"] = calibration(fx[fx.p_open.notna()], "p_open")
    qa.save(HERE)
    json.dump(R, open(os.path.join(HERE, "results.json"), "w"), indent=1, default=str)
    print(json.dumps(R["checkpoints_common_fixtures"]))
    for k in R["calibration_close"]:
        c, i = R["calibration_close"][k], R["information_elo"][k]
        print(f"{k:22s} n={c['logistic_slope']['n']:5d} LL={c['log_loss']:.4f} slope={c['logistic_slope']['est']} "
              f"[{c['logistic_slope']['lo']},{c['logistic_slope']['hi']}]  b_elo={i.get('b_elo')}  chrono={i.get('chronological_gain_vs_pinnacle', {}).get('gain')}"
              f" [{i.get('chronological_gain_vs_pinnacle', {}).get('lo')},{i.get('chronological_gain_vs_pinnacle', {}).get('hi')}]")
    for b, v in R["calibration_close"]["all"].items():
        if b.startswith("fav"):
            print("  close", b, v)


if __name__ == "__main__":
    main()
