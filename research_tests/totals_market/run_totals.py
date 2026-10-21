#!/usr/bin/env python3
"""Total games and game handicaps 2014-2025 (bet365, Ladbrokes, Unibet): market calibration, a
moneyline-pinned point model with learned dispersion and a first-server prior, stacking on the
books' own de-vigged prices (logistic and LightGBM), betting at open and close prices, the
first-server effect (with a simulation null for the selection effect of inferring the first
server from scores), and retirement / segment angles.

Usage:  python run_totals.py            (writes results.json next to this file; seeded)

Inputs (untrusted, pandas only): see prep.py. Helpers in this folder: prep.py, lines.py,
dist_lib.py, tmodel.py, firstserve.py, court_pace_src.py (copy of research_tests/ml).

Walk-forward: for test year Y in 2019..2025, fit on years <= Y-2, validate (early stopping,
model choice) on Y-1, test on Y. Nothing from the sealed period (2026-10-13 on) is read.
Decision times: 'close' (book's closing prices; moneyline closeness from Betfair's close,
bet365's where Betfair is missing) and 'open' (book's opening prices at the closing line, the
only line the file has; moneyline from bet365's opening). Betfair's 'opening' column is not
usable (favourite-longshot inverted, accuracy 34%: an in-play or settled price) and is never read.
Retired/abandoned matches are void (stake back) for totals and handicaps.
"""
from __future__ import annotations

import json
import os
import sys
import time
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import prep  # noqa: E402
import lines as LN  # noqa: E402
import tmodel as tm  # noqa: E402
import firstserve as fs  # noqa: E402
import dist_lib as dl  # noqa: E402

SEED = 20261021
RNG = np.random.default_rng(SEED)
T0 = time.time()
TEST_YEARS = list(range(2019, 2026))
THRESH = (0.0, 0.02, 0.04, 0.06)
B = 1000
OUT = {"meta": {"seed": SEED, "test_years": TEST_YEARS, "thresholds": THRESH}}


def log(*a):
    print(f"[{time.time() - T0:7.0f}s]", *a, flush=True)


def lg(p):
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def sig(x):
    return 1 / (1 + np.exp(-np.asarray(x, float)))


def ll(p, y):
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
    y = np.asarray(y, float)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def boot_ratio(groups, ret, stake=None, b=B):
    """Return per dollar with a match-resampled 95% range. groups: match id per bet."""
    ret = np.asarray(ret, float)
    stake = np.ones_like(ret) if stake is None else np.asarray(stake, float)
    if len(ret) == 0:
        return {"n": 0}
    u, inv = np.unique(groups, return_inverse=True)
    rs = np.bincount(inv, ret, len(u)); ss = np.bincount(inv, stake, len(u))
    idx = RNG.integers(0, len(u), size=(b, len(u)))
    bs = rs[idx].sum(1) / np.maximum(ss[idx].sum(1), 1e-9)
    return {"n": int(len(ret)), "roi": round(float(ret.sum() / stake.sum()), 4),
            "ci95": [round(float(np.percentile(bs, 2.5)), 4), round(float(np.percentile(bs, 97.5)), 4)]}


def boot_mean(x, groups=None, b=B):
    x = np.asarray(x, float)
    if len(x) == 0:
        return {"n": 0}
    if groups is None:
        groups = np.arange(len(x))
    u, inv = np.unique(groups, return_inverse=True)
    sx = np.bincount(inv, x, len(u)); cn = np.bincount(inv, None, len(u))
    idx = RNG.integers(0, len(u), size=(b, len(u)))
    bs = sx[idx].sum(1) / cn[idx].sum(1)
    return {"n": int(len(x)), "mean": round(float(x.mean()), 5),
            "ci95": [round(float(np.percentile(bs, 2.5)), 5), round(float(np.percentile(bs, 97.5)), 5)]}


# ====================================================================== data
pp = os.path.join(HERE, "prep.pkl")
if not os.path.exists(pp):
    prep.build().to_pickle(pp)
D = pd.read_pickle(pp)
D["s_hat"] = 0.5 * (sig(lg(D["pw0"]) + D["pace"]) + sig(lg(D["pl0"]) + D["pace"]))
L = LN.build_lines(D)
L["mid"] = L["idx"].values
log("matches", len(D), "line rows", len(L))
OUT["meta"]["n_matches"] = int(len(D))
OUT["meta"]["line_rows"] = {f"{m}|{b}": int(n) for (m, b), n in L.groupby(["market", "book"]).size().items()}
OUT["meta"]["integer_lines"] = int(((L["line"] % 1) == 0).sum())
OUT["meta"]["data_checks"] = {
    "betfair_opening_ll_vs_close": [round(float(ll(prep.devig(D.bf_w_opening, D.bf_l_opening), 1)[D.bf_w_opening.notna().values].mean()), 4),
                                    round(float(ll(prep.devig(D.bf_w, D.bf_l), 1)[D.bf_w.notna().values].mean()), 4)],
    "handicap_sign_vs_favourite_crosstab_corr": round(float(np.corrcoef(np.sign(D["b365_handicap"].fillna(0)), D["w_is_fav_close"].astype(float))[0, 1]), 4),
    "svgms_excludes_tiebreaks_share": 0.938,
}

# ====================================================================== 1. market calibration
log("1 calibration")
C = L[~L["void"]].copy()
C["lb_"] = pd.cut(C["line"].abs(), [0, 18.5, 20.5, 21.5, 22.5, 23.5, 26.5, 60]).astype(str)
C.loc[C["market"] == "hcp", "lb_"] = pd.cut(C.loc[C["market"] == "hcp", "line"].abs(), [0, 1.5, 2.5, 3.5, 4.5, 5.5, 20]).astype(str)


def calib_table(g):
    res = {}
    for t in ("close", "open"):
        x = g.dropna(subset=[f"p_{t}"])
        if len(x) < 30:
            continue
        y, p = x["y"].to_numpy(), x[f"p_{t}"].to_numpy()
        roi_a = np.where(y == 1, x[f"a_{t}"] - 1, -1.0); roi_b = np.where(y == 0, x[f"b_{t}"] - 1, -1.0)
        res[t] = {"n": int(len(x)), "rate_A": round(float(y.mean()), 4), "devig_A": round(float(p.mean()), 4),
                  "diff": round(float(y.mean() - p.mean()), 4), "se": round(float(y.std() / np.sqrt(len(y))), 4),
                  "logloss": round(float(ll(p, y).mean()), 5), "margin": round(float(x[f"over_{t}"].mean() - 1), 4),
                  "roi_A": round(float(roi_a.mean()), 4), "roi_B": round(float(roi_b.mean()), 4)}
    return res


cal = {}
for (mk, bk), g in C.groupby(["market", "book"]):
    k = f"{mk}|{bk}"
    cal[k] = {"all": calib_table(g),
              "by_level": {lv: calib_table(x) for lv, x in g.groupby("odds_level")},
              "by_year": {int(y): calib_table(x) for y, x in g.groupby("year")},
              "by_line": {lb: calib_table(x) for lb, x in g.groupby("lb_")},
              "by_level_bo": {f"{lv}|bo{bo}": calib_table(x) for (lv, bo), x in g.groupby(["odds_level", "bo"]) if len(x) > 200}}
    # consistency: years with the over (A) rate below de-vig, per level
    cons = {}
    for lv, x in g.groupby("odds_level"):
        diffs = [calib_table(z).get("close", {}).get("diff") for _, z in x.groupby("year")]
        diffs = [v for v in diffs if v is not None]
        cons[lv] = {"years": len(diffs), "years_A_below_devig": int(sum(v < 0 for v in diffs)),
                    "mean_diff": round(float(np.mean(diffs)), 4) if diffs else None}
    cal[k]["consistency_close"] = cons
    # open vs close log loss on the same rows (paired)
    x = g.dropna(subset=["p_open"])
    dlt = ll(x["p_close"], x["y"]) - ll(x["p_open"], x["y"])
    cal[k]["close_minus_open_logloss"] = boot_mean(dlt, x["mid"].to_numpy())
OUT["calibration"] = cal

# robustness: the full file (all rows, ITF included, no warehouse join), totals only
try:
    raw = pd.read_csv(os.path.join(prep.SCR, "kaggle_data", "extracted", "tennis_matches_2014_2025.csv"), low_memory=False,
                      usecols=["tour", "tournament", "match_format", "comment", "total_games", "match_date_formatted",
                               "bet365_total_games_line", "bet365_odds_over", "bet365_odds_under",
                               "Unibet_total_games_line", "Unibet_odds_over", "Unibet_odds_under"])
    raw = raw[raw["comment"] == "completed"]
    tn = raw["tournament"].astype(str).str.lower()
    raw["lvl"] = np.where(tn.str.contains("itf"), "ITF", np.where(tn.str.contains("challenger"), "Challenger", raw["tour"].astype(str) + " main"))
    full = {}
    for bk, pre in (("b365", "bet365"), ("ub", "Unibet")):
        Lr, o, u = raw[f"{pre}_total_games_line"], raw[f"{pre}_odds_over"], raw[f"{pre}_odds_under"]
        ok = Lr.notna() & (o > 1.01) & (u > 1.01) & np.where(raw["match_format"] == 5, (Lr >= 25.5) & (Lr <= 50.5), (Lr >= 12.5) & (Lr <= 33.5))
        x = raw[ok]
        p = prep.devig(o[ok], u[ok]); y = (x["total_games"] > Lr[ok]).astype(float).to_numpy()
        for lv in sorted(x["lvl"].unique()):
            mm = (x["lvl"] == lv).to_numpy()
            if mm.sum() > 300:
                full[f"{bk}|{lv}"] = {"n": int(mm.sum()), "over_rate": round(float(y[mm].mean()), 4), "devig": round(float(p[mm].mean()), 4),
                                      "diff": round(float(y[mm].mean() - p[mm].mean()), 4), "se": round(float(y[mm].std() / np.sqrt(mm.sum())), 4)}
    OUT["calibration_full_file_totals"] = full
except Exception as e:  # noqa: BLE001
    OUT["calibration_full_file_totals"] = {"error": str(e)}

# ====================================================================== 2. point model per fold
GRID_DELTA = (-0.03, -0.015, 0.0)
GRID_TAU = (0.06, 0.075, 0.09, 0.105)
GRID_SIGMA = (0.0, 0.03)


def solve_g0(s, q, bo, tau):
    bi = (np.asarray(bo) == 5).astype(int)
    si = np.clip(np.round((np.asarray(s) - tm.S0) / tm.SSTEP).astype(int), 0, tm.NS - 1)
    q = np.clip(np.asarray(q), 0.5, 0.995)
    lo, hi = np.zeros(len(s)), np.full(len(s), 0.4)
    nodes = list(zip(tm.GZ5, tm.GW5)) if tau > 0 else [(0.0, 1.0)]
    for _ in range(22):
        mid = 0.5 * (lo + hi)
        pwm = sum(w * tm._pw_signed(bi, si, mid + tau * z) for z, w in nodes)
        hi = np.where(pwm > q, mid, hi); lo = np.where(pwm > q, lo, mid)
    return 0.5 * (lo + hi)


def fit_point(train):
    """(delta, tau, sigma) per gender by the log-likelihood of observed totals + favourite margins."""
    par = {}
    for g in ("MEN", "WTA"):
        x = train[train["gender"] == g]
        x = x.sample(min(6000, len(x)), random_state=SEED)
        Mf = (np.where(x["w_is_fav_close"], x["Mw"], -x["Mw"]) + dl.MOFF).astype(int)
        best = None
        for de in GRID_DELTA:
            for ta in GRID_TAU:
                for sg in GRID_SIGMA:
                    pt, pm = tm.mix2(x["s_hat"].values + de, x["q_close"].values, x["bo"].values, np.full(len(x), 0.5), sg, ta)
                    v = tm.loglik_totals(pt, x["T"]).mean() + np.log(np.maximum(pm[np.arange(len(x)), np.clip(Mf, 0, dl.NM - 1)], 1e-9)).mean()
                    if best is None or v > best[0]:
                        best = (v, de, ta, sg)
        par[g] = {"delta": best[1], "tau": best[2], "sigma": best[3], "ll": round(float(best[0]), 4)}
    return par


def sets_fav(row_sets, w_is_fav):
    return [(a, b) if w_is_fav else (b, a) for a, b, _ in row_sets]


# first-server sample: completed, first server determinable, warehouse score parsable
D["sets_raw"] = D["raw_score"].map(prep.parse_sets)
FSM = D[(~D["void"]) & D["first_server"].isin(["w", "l"]) & D["sets_raw"].notna() & D["q_close"].notna()].copy()
FSM["x_fav"] = ((FSM["first_server"] == "w") == FSM["w_is_fav_close"]).astype(int)
FSM["x_winner"] = (FSM["first_server"] == "w").astype(int)


def fit_pi(par, years_max):
    """Conditional-likelihood prior and the naive (selection-biased) count, on years <= years_max."""
    x = FSM[FSM["year"] <= years_max]
    out = {}
    lf_all, ld_all, g_all, xf_all = [], [], [], []
    for g in ("MEN", "WTA"):
        z = x[x["gender"] == g]
        p = par[g]
        s = z["s_hat"].values + p["delta"]
        g0 = solve_g0(s, z["q_close"].values, z["bo"].values, p["tau"])
        sts = [sets_fav(r, w) for r, w in zip(z["sets_raw"], z["w_is_fav_close"])]
        lf, ld = fs.likelihoods(sts, s, g0, p["tau"])
        lf_all.append(lf); ld_all.append(ld); g_all.append(g0); xf_all.append(z["x_fav"].values)
    lf, ld, g0, xf = map(np.concatenate, (lf_all, ld_all, g_all, xf_all))
    cond = fs.fit_prior(xf, lf - ld, g0)
    naive = fs.fit_naive(xf, g0)
    out = {"n": int(len(xf)), "naive_share_fav_first": round(float(xf.mean()), 4),
           "conditional": {k: round(v, 4) for k, v in cond.items()}, "naive": {k: round(v, 4) for k, v in naive.items()},
           "conditional_pi_at_mean_gap": round(float(sig(cond["a"] + cond["b"] * g0.mean())), 4),
           "mean_gap": round(float(g0.mean()), 4)}
    return out, cond


# ====================================================================== features
SURF = {"hard": 0, "clay": 1, "grass": 2, "indoors": 3}
LVL = {"ATP main": 0, "Challenger": 1, "WTA main": 2}
BOOK = {"b365": 0, "lb": 1, "ub": 2}


def match_features(d, t):
    """Pre-match features per match; symmetric for totals (sums, min/max), favourite-first for margins."""
    wf = d[f"w_is_fav_{t}"].values
    f = pd.DataFrame(index=d.index)
    f["q"] = d[f"q_{t}"].values
    f["bo5"] = (d["bo"] == 5).astype(int).values
    f["wta"] = (d["gender"] == "WTA").astype(int).values
    f["lvl"] = d["odds_level"].map(LVL).values
    f["surf"] = d["surface"].map(SURF).values
    f["indoor"] = d["indoor"].values
    f["round_rank"] = d["round_rank"].values
    f["s_hat"] = d["s_hat"].values
    f["pace"] = d["pace"].values; f["pace_pts"] = np.log1p(d["pace_pts"].values)
    f["mu"] = d["mu"].values
    f["S_sum"] = (d["S_w"] + d["S_l"]).values; f["R_sum"] = (d["R_w"] + d["R_l"]).values
    for c in ("hold", "opp_hold", "tb_rate", "gps", "ret52", "n52", "ev_matches_before", "prev_round_minutes",
              "weeks_since_prev_event", "age", "ace_h20"):
        a, b = d[f"w_{c}"].values.astype(float), d[f"l_{c}"].values.astype(float)
        fav, dog = np.where(wf, a, b), np.where(wf, b, a)
        f[f"{c}_sum"] = a + b
        f[f"{c}_max"] = np.fmax(a, b)
        f[f"{c}_fav"] = fav; f[f"{c}_dog"] = dog
    f["n_all_min"] = np.fmin(d["w_n_all"].values, d["l_n_all"].values)
    f["elo_gap_abs"] = np.abs(d["w_elo_all"].values - d["l_elo_all"].values)
    return f


def line_features(Lr, F, pmf_t, pmf_m, t, d_wfav):
    """Per line row: market, model and match features. Handicap side A is the book's favourite;
    when that differs from the moneyline favourite the margin pmf is mirrored."""
    i = Lr["idx"].values
    X = F.loc[i].reset_index(drop=True)
    pos = D.index.get_indexer(i)
    is_tot = (Lr["market"].values == "tot")
    p_mod = np.empty(len(Lr))
    ex = np.empty(len(Lr)); sd = np.empty(len(Lr))
    if is_tot.any():
        pt = pmf_t[pos[is_tot]]
        p_mod[is_tot] = tm.p_over(pt, Lr["line"].values[is_tot])
        e = (pt * np.arange(dl.TMAX)).sum(1)
        ex[is_tot] = e - Lr["line"].values[is_tot]
        sd[is_tot] = np.sqrt((pt * (np.arange(dl.TMAX)[None, :] - e[:, None]) ** 2).sum(1))
    h = ~is_tot
    if h.any():
        pm = pmf_m[pos[h]]
        same = (Lr["A_is_w"].values[h].astype(bool) == d_wfav[pos[h]])
        pm = np.where(same[:, None], pm, pm[:, ::-1])
        p_mod[h] = tm.p_cover(pm, Lr["line"].values[h])
        mv = np.arange(dl.NM) - dl.MOFF
        e = (pm * mv).sum(1)
        ex[h] = e + Lr["line"].values[h]
        sd[h] = np.sqrt((pm * (mv[None, :] - e[:, None]) ** 2).sum(1))
        # A-oriented skill features for margins
        same_all = np.ones(len(Lr), bool); same_all[h] = same
        for c in ("hold", "opp_hold", "ret52", "age", "ace_h20", "prev_round_minutes", "ev_matches_before"):
            fa, fd_ = X[f"{c}_fav"].values.copy(), X[f"{c}_dog"].values.copy()
            X[f"{c}_fav"] = np.where(same_all, fa, fd_); X[f"{c}_dog"] = np.where(same_all, fd_, fa)
    X["book"] = Lr["book"].map(BOOK).values
    X["line"] = Lr["line"].values
    X["lp_mkt"] = lg(Lr[f"p_{t}"].values)
    X["margin"] = Lr[f"over_{t}"].values - 1
    X["lp_model"] = lg(p_mod)
    X["gap"] = X["lp_model"] - X["lp_mkt"]
    X["model_ex"] = ex; X["model_sd"] = sd
    return X, p_mod


def fit_offset_logit(X, y, off, l2=1.0, iters=30):
    """Logistic regression with an offset (Newton)."""
    X = np.c_[X, np.ones(len(X))]
    w = np.zeros(X.shape[1])
    for _ in range(iters):
        p = sig(X @ w + off)
        g = X.T @ (p - y) + l2 * np.r_[w[:-1], 0]
        H = (X * (p * (1 - p))[:, None]).T @ X + l2 * np.diag(np.r_[np.ones(X.shape[1] - 1), 0])
        step = np.linalg.solve(H, g)
        w -= step
        if np.abs(step).max() < 1e-8:
            break
    return w


def stack_design(X):
    cols = ["gap", "gap_bo5", "gap_wta", "pace", "bk1", "bk2", "lvl1", "lvl2", "bo5", "margin"]
    Z = pd.DataFrame({"gap": X["gap"], "gap_bo5": X["gap"] * X["bo5"], "gap_wta": X["gap"] * X["wta"], "pace": X["pace"],
                      "bk1": (X["book"] == 1).astype(float), "bk2": (X["book"] == 2).astype(float),
                      "lvl1": (X["lvl"] == 1).astype(float), "lvl2": (X["lvl"] == 2).astype(float), "bo5": X["bo5"], "margin": X["margin"]})
    return Z[cols].to_numpy(float)


import lightgbm as lgb  # noqa: E402

LGB_PARAMS = dict(objective="binary", learning_rate=0.02, num_leaves=15, min_data_in_leaf=300, feature_fraction=0.7,
                  bagging_fraction=0.8, bagging_freq=1, lambda_l2=10.0, verbose=-1, seed=SEED, deterministic=True,
                  num_threads=4, force_col_wise=True)


# ====================================================================== walk-forward
PRED = []           # test-year line rows with every model's probability
FOLD = {}
PI_FITS = {}
CACHE = os.path.join(HERE, "walkforward_cache.pkl")
REUSE = os.environ.get("REUSE_WALKFORWARD") == "1" and os.path.exists(CACHE)
if REUSE:
    import pickle
    with open(CACHE, "rb") as fh:
        PR, FOLD, PI_FITS = pickle.load(fh)
    log("reusing walk-forward cache")
for Y in ([] if REUSE else TEST_YEARS):
    log("fold", Y)
    tr_years, va_year = list(range(2014, Y - 1)), Y - 1
    Dm = D[(D["year"] <= Y) & D["s_hat"].notna()]
    trm = Dm[(Dm["year"] <= Y - 2) & ~Dm["void"] & Dm["q_close"].notna()]
    par = fit_point(trm)
    pif, cond = fit_pi(par, Y - 2)
    PI_FITS[Y] = pif
    FOLD[Y] = {"point_params": par, "first_server_prior": pif}
    log("  params", par, "pi", pif["conditional"], "naive share", pif["naive_share_fav_first"])
    for t in ("close", "open"):
        ok = Dm[f"q_{t}"].notna()
        Dt = Dm[ok]
        pmf_t = np.zeros((len(D), dl.TMAX), np.float32); pmf_m = np.zeros((len(D), dl.NM), np.float32)
        for g in ("MEN", "WTA"):
            z = Dt[Dt["gender"] == g]
            p = par[g]
            s = z["s_hat"].values + p["delta"]
            g0 = solve_g0(s, z[f"q_{t}"].values, z["bo"].values, p["tau"])
            pi = sig(cond["a"] + cond["b"] * g0)
            a_, b_ = tm.mix2(s, z[f"q_{t}"].values, z["bo"].values, pi, p["sigma"], p["tau"])
            pos = D.index.get_indexer(z.index)
            pmf_t[pos] = a_; pmf_m[pos] = b_
        F = match_features(D, t)
        wfav = D[f"w_is_fav_{t}"].values
        Lt = L[(L["year"] <= Y) & L[f"p_{t}"].notna() & L["idx"].isin(Dt.index)].copy()
        for mk in ("tot", "hcp"):
            Lm = Lt[Lt["market"] == mk].reset_index(drop=True)
            X, p_mod = line_features(Lm, F, pmf_t, pmf_m, t, wfav)
            y = Lm["y"].to_numpy(float)
            nv = ~Lm["void"].to_numpy()
            tr = (Lm["year"].to_numpy() <= Y - 2) & nv
            va = (Lm["year"].to_numpy() == Y - 1) & nv
            te = (Lm["year"].to_numpy() == Y)
            off = X["lp_mkt"].to_numpy()
            preds = {"market": sig(off), "point_raw": p_mod}
            # model alone, Platt-calibrated on train
            Zl = X[["lp_model"]].to_numpy()
            w = fit_offset_logit(Zl[tr], y[tr], np.zeros(tr.sum()), l2=0.0)
            preds["alone"] = sig(np.c_[Zl, np.ones(len(Zl))] @ w)
            # stack on the market
            Zs = stack_design(X)
            mu_, sd_ = Zs[tr].mean(0), Zs[tr].std(0) + 1e-9
            Zs = (Zs - mu_) / sd_
            w = fit_offset_logit(Zs[tr], y[tr], off[tr], l2=5.0)
            preds["stack"] = sig(off + np.c_[Zs, np.ones(len(Zs))] @ w)
            # LightGBM on top of the market (init score), early stopping on the validation year
            feat_cols = [c for c in X.columns if c not in ("lp_mkt",)] + ["lp_mkt"]
            dtr = lgb.Dataset(X.loc[tr, feat_cols], y[tr], init_score=off[tr], free_raw_data=False)
            dva = lgb.Dataset(X.loc[va, feat_cols], y[va], init_score=off[va], reference=dtr)
            bst = lgb.train(LGB_PARAMS, dtr, 2000, valid_sets=[dva], callbacks=[lgb.early_stopping(100, verbose=False)])
            preds["lgb"] = sig(off + bst.predict(X[feat_cols], raw_score=True, num_iteration=bst.best_iteration))
            # model alone without the market: LightGBM on everything except market columns
            alone_cols = [c for c in X.columns if c not in ("lp_mkt", "gap", "margin")]
            dtr2 = lgb.Dataset(X.loc[tr, alone_cols], y[tr], free_raw_data=False)
            dva2 = lgb.Dataset(X.loc[va, alone_cols], y[va], reference=dtr2)
            bst2 = lgb.train(LGB_PARAMS, dtr2, 2000, valid_sets=[dva2], callbacks=[lgb.early_stopping(100, verbose=False)])
            preds["lgb_alone"] = bst2.predict(X[alone_cols], num_iteration=bst2.best_iteration)
            vll = {k: float(ll(v[va], y[va]).mean()) for k, v in preds.items()}
            cand = ["market", "stack", "lgb", "alone", "lgb_alone"]
            chosen = min(cand, key=lambda k: vll[k])
            FOLD[Y][f"{mk}|{t}"] = {"val_logloss": {k: round(v, 5) for k, v in vll.items()}, "chosen": chosen,
                                   "lgb_rounds": int(bst.best_iteration), "lgb_alone_rounds": int(bst2.best_iteration),
                                   "stack_w": np.round(w, 4).tolist(),
                                   "lgb_top_gain": dict(sorted(zip(feat_cols, bst.feature_importance("gain").round(1).tolist()), key=lambda kv: -kv[1])[:8])}
            log(f"  {mk}|{t}", "val", {k: round(v, 4) for k, v in vll.items()}, "chosen", chosen, "rounds", bst.best_iteration)
            P = Lm.loc[te, ["idx", "mid", "book", "market", "line", "year", "odds_level", "bo", "gender", "level", "y", "void",
                            "a_close", "b_close", "a_open", "b_open", "p_close", "p_open"]].copy()
            P["t"] = t
            for k, v in preds.items():
                P[f"m_{k}"] = v[te]
            P["m_chosen"] = preds[chosen][te]
            P["chosen"] = chosen
            for c in ("ret52_sum", "ret52_max", "prev_round_minutes_sum", "ev_matches_before_sum", "q", "model_ex", "pace"):
                P[c] = X.loc[te, c].values
            PRED.append(P)
if not REUSE:
    PR = pd.concat(PRED, ignore_index=True)
    import pickle
    with open(CACHE, "wb") as fh:
        pickle.dump((PR, FOLD, PI_FITS), fh)
OUT["folds"] = {str(k): v for k, v in FOLD.items()}
PR.to_pickle(os.path.join(HERE, "test_predictions.pkl"))

# ====================================================================== evaluation (log loss vs the book's own price)
log("evaluation")
MODELS = ["market", "point_raw", "alone", "lgb_alone", "stack", "lgb", "chosen"]
ev = {}
for (mk, t), g in PR[~PR["void"]].groupby(["market", "t"]):
    y = g["y"].to_numpy()
    base = ll(g["m_market"], y)
    e = {"n": int(len(g)), "market_logloss": round(float(base.mean()), 5)}
    for m_ in MODELS[1:]:
        dl_ = ll(g[f"m_{m_}"], y) - base
        e[f"{m_}_minus_market"] = boot_mean(dl_, g["mid"].to_numpy())
        e[f"{m_}_minus_market_by_year"] = {int(yy): round(float(dl_[g["year"].to_numpy() == yy].mean()), 5) for yy in TEST_YEARS}
    # calibration of P(over) for the chosen model and the market, by decile of the chosen probability
    q_ = pd.qcut(g["m_chosen"], 10, duplicates="drop")
    e["calibration_chosen"] = [{"p": round(float(x["m_chosen"].mean()), 4), "y": round(float(x["y"].mean()), 4), "n": int(len(x))} for _, x in g.groupby(q_)]
    q2 = pd.qcut(g["m_point_raw"], 10, duplicates="drop")
    e["calibration_point_raw"] = [{"p": round(float(x["m_point_raw"].mean()), 4), "y": round(float(x["y"].mean()), 4), "n": int(len(x))} for _, x in g.groupby(q2)]
    e["chosen_by_year"] = {int(yy): str(x["chosen"].iloc[0]) for yy, x in g.groupby("year")}
    ev[f"{mk}|{t}"] = e
OUT["evaluation"] = ev


# ====================================================================== 3. betting
log("3 betting")


def bets(g, model, t, thr):
    """One bet per line row (the side with the higher EV) when EV > thr; void rows are refunded (no bet)."""
    p = g[f"m_{model}"].to_numpy()
    a, b = g[f"a_{t}"].to_numpy(), g[f"b_{t}"].to_numpy()
    eva, evb = p * a - 1, (1 - p) * b - 1
    side_a = eva >= evb
    ev_ = np.where(side_a, eva, evb)
    pick = (ev_ > thr) & ~g["void"].to_numpy() & np.isfinite(ev_)
    y = g["y"].to_numpy()
    ret = np.where(side_a, np.where(y == 1, a - 1, -1.0), np.where(y == 0, b - 1, -1.0))
    clv = None
    if t == "open":
        pc = g["p_close"].to_numpy()
        clv = np.where(side_a, a * pc - 1, b * (1 - pc) - 1)
    return pick, ret, side_a, clv


BET = {}
for model in ("chosen", "lgb", "stack", "alone", "lgb_alone"):
    res = {}
    for (mk, t, bk), g in PR.groupby(["market", "t", "book"]):
        g = g.dropna(subset=[f"a_{t}", f"b_{t}"])
        for thr in THRESH:
            pick, ret, side_a, clv = bets(g, model, t, thr)
            cell = {"all": boot_ratio(g["mid"].to_numpy()[pick], ret[pick])}
            cell["share_side_A"] = round(float(side_a[pick].mean()), 3) if pick.any() else None
            yrs = {}
            for yy in TEST_YEARS:
                mm = pick & (g["year"].to_numpy() == yy)
                yrs[int(yy)] = {"n": int(mm.sum()), "roi": round(float(ret[mm].mean()), 4) if mm.any() else None}
            cell["by_year"] = yrs
            cell["positive_years"] = int(sum(1 for v in yrs.values() if v["roi"] is not None and v["roi"] > 0))
            if clv is not None and pick.any():
                cell["clv_vs_close_devig"] = boot_mean(clv[pick], g["mid"].to_numpy()[pick])
            res[f"{mk}|{t}|{bk}|ev>{thr}"] = cell
    BET[model] = res
OUT["betting"] = BET

# robustness: main-line-shaped prices only (both sides within 1.6-2.4 at the bet time), and best of 3 only.
# Off-balance prices at a "main" line are where set-handicap rows or stale/mislabelled lines hide.
ROB = {}
for model in ("chosen", "lgb", "stack", "alone", "lgb_alone"):
    res = {}
    for (mk, t, bk), g in PR.groupby(["market", "t", "book"]):
        g = g.dropna(subset=[f"a_{t}", f"b_{t}"])
        shape = ((g[f"a_{t}"].between(1.6, 2.4)) & (g[f"b_{t}"].between(1.6, 2.4))).to_numpy()
        for thr in THRESH:
            pick, ret, side_a, clv = bets(g, model, t, thr)
            for nm, mask in (("main_shape", shape), ("main_shape_bo3", shape & (g["bo"] == 3).to_numpy())):
                mm = pick & mask
                cell = {"all": boot_ratio(g["mid"].to_numpy()[mm], ret[mm]),
                        "positive_years": int(sum(1 for yy in TEST_YEARS if (mm & (g["year"].to_numpy() == yy)).any() and ret[mm & (g["year"].to_numpy() == yy)].mean() > 0))}
                if clv is not None and mm.any():
                    cell["clv_vs_close_devig"] = boot_mean(clv[mm], g["mid"].to_numpy()[mm])
                res[f"{mk}|{t}|{bk}|ev>{thr}|{nm}"] = cell
    ROB[model] = res
OUT["betting_robust"] = ROB

# no-model rules from the calibration (fixed on 2014-2018, tested 2019-2025): always under / always favourite cover
rules = {}
for (mk, bk, lv), g in L[~L["void"]].groupby(["market", "book", "odds_level"]):
    for t in ("close", "open"):
        x = g.dropna(subset=[f"a_{t}", f"b_{t}"])
        if len(x) < 500:
            continue
        pre = x[x["year"] <= 2018]; post = x[x["year"] >= 2019]
        if len(pre) < 200 or len(post) < 200:
            continue
        side_A = (pre["y"].mean() - pre[f"p_{t}"].mean()) > 0         # direction chosen on 2014-2018 only
        ret = np.where(side_A, np.where(post["y"] == 1, post[f"a_{t}"] - 1, -1.0), np.where(post["y"] == 0, post[f"b_{t}"] - 1, -1.0))
        rules[f"{mk}|{bk}|{lv}|{t}"] = {"side": "A(over/fav)" if side_A else "B(under/dog)",
                                        "pre_diff": round(float(pre["y"].mean() - pre[f"p_{t}"].mean()), 4),
                                        "test_2019_2025": boot_ratio(post["mid"].to_numpy(), ret),
                                        "test_by_year": {int(yy): round(float(ret[post["year"].to_numpy() == yy].mean()), 4) for yy in sorted(post["year"].unique())}}
OUT["flat_rules_from_calibration"] = rules

# ====================================================================== 4. first-server effect
log("4 first server")
# (a) on matches with an inferable first server, test years, compare with a simulation null of the
# same inference and selection, using the parameters fitted on years <= 2017 (fold 2019)
par = FOLD[2019]["point_params"]
fsr = {"prior_fits_by_fold": {str(k): v for k, v in PI_FITS.items()}}
cand = D[(~D["void"]) & D["q_close"].notna() & D["s_hat"].notna() & D["w_SvGms"].notna() & (D["year"] >= 2019)].copy()
cand["sets_raw"] = cand["raw_score"].map(prep.parse_sets)
cand = cand[cand["sets_raw"].notna()]
cond19 = PI_FITS[2019]["conditional"]
sim_rows, real_rows = [], []
for g in ("MEN", "WTA"):
    z = cand[cand["gender"] == g]
    p = par[g]
    s = z["s_hat"].values + p["delta"]
    g0 = solve_g0(s, z["q_close"].values, z["bo"].values, p["tau"])
    pi_fit = sig(cond19["a"] + cond19["b"] * g0)
    pt, pm = tm.mix2(s, z["q_close"].values, z["bo"].values, pi_fit, p["sigma"], p["tau"])
    pt_f, pm_f = tm.mix2(s, z["q_close"].values, z["bo"].values, np.ones(len(z)), p["sigma"], p["tau"])
    pt_d, pm_d = tm.mix2(s, z["q_close"].values, z["bo"].values, np.zeros(len(z)), p["sigma"], p["tau"])
    ET = (pt * np.arange(dl.TMAX)).sum(1)
    mv = np.arange(dl.NM) - dl.MOFF
    EM = (pm * mv).sum(1)
    r = pd.DataFrame({"idx": z.index, "gender": g, "ET": ET, "EM": EM,
                      "ET_ffirst": (pt_f * np.arange(dl.TMAX)).sum(1), "ET_dfirst": (pt_d * np.arange(dl.TMAX)).sum(1),
                      "EM_ffirst": (pm_f * mv).sum(1), "EM_dfirst": (pm_d * mv).sum(1),
                      "T": z["T"].values, "Mfav": np.where(z["w_is_fav_close"], z["Mw"], -z["Mw"]),
                      "fav_won": z["w_is_fav_close"].values, "fs": z["first_server"].values,
                      "line": z["b365_total_games_line"].values, "year": z["year"].values})
    r["det"] = r["fs"].isin(["w", "l"])
    r["x_fav"] = np.where(r["det"], ((r["fs"] == "w") == r["fav_won"]).astype(float), np.nan)
    real_rows.append(r)
    for pi_name, pi_v in (("pi_fit", pi_fit), ("pi_half", np.full(len(z), 0.5))):
        sm = fs.simulate(s, g0, p["tau"], pi_v, z["bo"].values, 5, RNG)
        k = 5
        sim_rows.append(pd.DataFrame({"gender": g, "pi": pi_name, "ET": np.repeat(ET, k), "EM": np.repeat(EM, k),
                                      "T": sm["total"], "Mfav": sm["margin"], "fav_won": sm["fav_won"],
                                      "det": sm["determinable"], "x_fav": np.where(sm["determinable"], (sm["inferred"] == 1).astype(float), np.nan),
                                      "true_fav_first": sm["fav_first"]}))
RR = pd.concat(real_rows, ignore_index=True); SS = pd.concat(sim_rows, ignore_index=True)


def fs_stats(x, grp_ids=None):
    d_ = x[x["det"]]
    out = {"n_all": int(len(x)), "share_determinable": round(float(x["det"].mean()), 4), "n_det": int(len(d_)),
           "share_fav_first": round(float(d_["x_fav"].mean()), 4),
           "share_winner_first": round(float((d_["x_fav"] == d_["fav_won"].astype(float)).mean()), 4)}
    for name, m in (("fav_first", d_["x_fav"] == 1), ("dog_first", d_["x_fav"] == 0),
                    ("winner_first", d_["x_fav"] == d_["fav_won"].astype(float)), ("loser_first", d_["x_fav"] != d_["fav_won"].astype(float))):
        out[name] = {"n": int(m.sum()), "T_minus_model": round(float((d_["T"] - d_["ET"])[m].mean()), 3),
                     "Mfav_minus_model": round(float((d_["Mfav"] - d_["EM"])[m].mean()), 3)}
        if "line" in d_:
            out[name]["T_minus_b365_line"] = round(float((d_["T"] - d_["line"])[m].mean()), 3)
    out["did_T_fav_minus_dog_first"] = round(out["fav_first"]["T_minus_model"] - out["dog_first"]["T_minus_model"], 3)
    out["did_M_fav_minus_dog_first"] = round(out["fav_first"]["Mfav_minus_model"] - out["dog_first"]["Mfav_minus_model"], 3)
    return out


fsr["real_2019_2025"] = fs_stats(RR)
fsr["sim_pi_fit"] = fs_stats(SS[SS["pi"] == "pi_fit"])
fsr["sim_pi_half"] = fs_stats(SS[SS["pi"] == "pi_half"])
sim_inf_ok = SS[SS["det"]]
fsr["sim_inference_accuracy"] = round(float((sim_inf_ok["x_fav"] == sim_inf_ok["true_fav_first"].astype(float)).mean()), 4)
# real minus simulated (pi_fit) fav-first vs dog-first difference, with a match bootstrap on the real side
Rd = RR[RR["det"]].copy()
Rd["rT"] = Rd["T"] - Rd["ET"]; Rd["rM"] = Rd["Mfav"] - Rd["EM"]
Sd = SS[(SS["pi"] == "pi_fit") & SS["det"]]
simT = (Sd["T"] - Sd["ET"])[Sd["x_fav"] == 1].mean() - (Sd["T"] - Sd["ET"])[Sd["x_fav"] == 0].mean()
simM = (Sd["Mfav"] - Sd["EM"])[Sd["x_fav"] == 1].mean() - (Sd["Mfav"] - Sd["EM"])[Sd["x_fav"] == 0].mean()
bsT, bsM = [], []
fx = Rd["x_fav"].to_numpy(); rT = Rd["rT"].to_numpy(); rM = Rd["rM"].to_numpy()
for _ in range(B):
    ii = RNG.integers(0, len(Rd), len(Rd))
    f1 = fx[ii] == 1
    bsT.append(rT[ii][f1].mean() - rT[ii][~f1].mean()); bsM.append(rM[ii][f1].mean() - rM[ii][~f1].mean())
realT = rT[fx == 1].mean() - rT[fx == 0].mean(); realM = rM[fx == 1].mean() - rM[fx == 0].mean()
fsr["real_minus_sim_fav_vs_dog_first"] = {
    "totals": {"real": round(float(realT), 3), "sim": round(float(simT), 3), "excess": round(float(realT - simT), 3),
               "real_ci95": [round(float(np.percentile(bsT, 2.5)), 3), round(float(np.percentile(bsT, 97.5)), 3)]},
    "margin": {"real": round(float(realM), 3), "sim": round(float(simM), 3), "excess": round(float(realM - simM), 3),
               "real_ci95": [round(float(np.percentile(bsM, 2.5)), 3), round(float(np.percentile(bsM, 97.5)), 3)]}}
# model-implied first-server shift (what knowing the toss is worth under the model)
fsr["model_shift_fav_first_minus_dog_first"] = {
    "totals_mean": round(float((RR["ET_ffirst"] - RR["ET_dfirst"]).mean()), 3),
    "totals_abs_p95": round(float(np.percentile(np.abs(RR["ET_ffirst"] - RR["ET_dfirst"]), 95)), 3),
    "margin_mean": round(float((RR["EM_ffirst"] - RR["EM_dfirst"]).mean()), 3),
    "margin_abs_p95": round(float(np.percentile(np.abs(RR["EM_ffirst"] - RR["EM_dfirst"]), 95)), 3)}

# (b) hypothetical in-play right after the toss: model P(over b365 close line | first server)
# vs the pre-match close price, assuming the price has not moved. Not a pre-match edge.
hyp = {}
cl = L[(L["market"] == "tot") & (L["book"] == "b365") & (L["year"] >= 2019) & ~L["void"]].set_index("idx")
for g in ("MEN", "WTA"):
    z = cand[(cand["gender"] == g) & cand.index.isin(cl.index)]
    p = par[g]
    s = z["s_hat"].values + p["delta"]
    g0 = solve_g0(s, z["q_close"].values, z["bo"].values, p["tau"])
    pi_fit = sig(cond19["a"] + cond19["b"] * g0)
    lines_ = cl.loc[z.index, "line"].values
    po = {}
    for nm, pv in (("prior", pi_fit), ("fav", np.ones(len(z))), ("dog", np.zeros(len(z)))):
        pt_, _ = tm.mix2(s, z["q_close"].values, z["bo"].values, pv, p["sigma"], p["tau"], want=("tot",))
        po[nm] = tm.p_over(pt_, lines_)
    dp = np.r_[po["fav"] - po["prior"], po["dog"] - po["prior"]]
    a_, b_ = cl.loc[z.index, "a_close"].values, cl.loc[z.index, "b_close"].values
    pm_ = cl.loc[z.index, "p_close"].values
    # the toss information added to the market's de-vigged price (logit shift of the model)
    evs = []
    for nm in ("fav", "dog"):
        padj = sig(lg(pm_) + lg(po[nm]) - lg(po["prior"]))
        evs.append(np.maximum(padj * a_ - 1, (1 - padj) * b_ - 1))
    evs = np.r_[evs[0], evs[1]]
    hyp[g] = {"n": int(len(z)), "abs_dp_over_mean": round(float(np.abs(dp).mean()), 4), "abs_dp_over_p95": round(float(np.percentile(np.abs(dp), 95)), 4),
              "share_ev_gt_0": round(float((evs > 0).mean()), 4), "share_ev_gt_2pct": round(float((evs > 0.02).mean()), 4),
              "mean_best_ev": round(float(evs.mean()), 4)}
fsr["hypothetical_after_toss_b365_close"] = hyp
OUT["first_server"] = fsr

# ====================================================================== 5. angles
log("5 angles")
ang = {}
CC = L[~L["void"] & (L["market"] == "tot")].join(D[["w_ret52", "l_ret52", "w_prev_round_minutes", "l_prev_round_minutes",
                                                    "w_ev_matches_before", "l_ev_matches_before", "level"]].add_prefix("d_"), on="idx")
CC["ret_sum"] = CC["d_w_ret52"].fillna(0) + CC["d_l_ret52"].fillna(0)
CC["work"] = CC["d_w_prev_round_minutes"].fillna(0) + CC["d_l_prev_round_minutes"].fillna(0)
# void rates by retirement history (retirements void totals: information for a market maker, not a bettor)
VV = D.copy()
VV["ret_sum"] = VV["w_ret52"].fillna(0) + VV["l_ret52"].fillna(0)
VV["retired"] = VV["comment"] == "retired_or_abandoned"
ang["retirement_rate_by_recent_retirements"] = {str(k): {"n": int(len(x)), "retired_share": round(float(x["retired"].mean()), 4)}
                                                 for k, x in VV.groupby(pd.cut(VV["ret_sum"], [-1, 0, 1, 2, 100]))}
for nm, col, bins in (("over_vs_devig_by_recent_retirements", "ret_sum", [-1, 0, 1, 2, 100]),
                      ("over_vs_devig_by_prev_round_minutes_sum", "work", [-1, 0, 150, 250, 350, 2000])):
    res = {}
    for k, x in CC.groupby(pd.cut(CC[col], bins)):
        for per, xx in (("2014_2018", x[x["year"] <= 2018]), ("2019_2025", x[x["year"] >= 2019])):
            if len(xx) > 100:
                res[f"{k}|{per}"] = boot_mean((xx["y"] - xx["p_close"]).to_numpy(), xx["mid"].to_numpy())
    ang[nm] = res
# segments of the chosen-model bets and calibration: Slams best of 5, tours, line level
seg = {}
PRb = PR.copy()
PRb["slam_bo5"] = (PRb["bo"] == 5)
for (mk, t), g in PRb.groupby(["market", "t"]):
    g = g.dropna(subset=[f"a_{t}", f"b_{t}"])
    for thr in (0.0, 0.02, 0.04):
        pick, ret, side_a, _ = bets(g, "chosen", t, thr)
        for sname, mask in (("bo5", g["slam_bo5"].to_numpy()), ("ATP main bo3", ((g["odds_level"] == "ATP main") & (g["bo"] == 3)).to_numpy()),
                            ("Challenger", (g["odds_level"] == "Challenger").to_numpy()), ("WTA", (g["odds_level"] == "WTA main").to_numpy()),
                            ("line<=20.5", (g["line"].abs() <= 20.5).to_numpy() & (g["bo"] == 3).to_numpy()),
                            ("line>=23.5", (g["line"].abs() >= 23.5).to_numpy() & (g["bo"] == 3).to_numpy())):
            mm = pick & mask
            seg[f"{mk}|{t}|ev>{thr}|{sname}"] = boot_ratio(g["mid"].to_numpy()[mm], ret[mm])
ang["chosen_model_bets_by_segment"] = seg
bo5 = L[~L["void"] & (L["bo"] == 5)]
ang["bo5_calibration"] = {f"{mk}|{bk}": calib_table(x) for (mk, bk), x in bo5.groupby(["market", "book"]) if len(x) > 100}
ang["lines_half_vs_integer"] = {"integer_line_rows": int(((L["line"] % 1) == 0).sum()), "half_line_rows": int(((L["line"] % 1) != 0).sum())}
OUT["angles"] = ang

# ====================================================================== leak sentinel
log("leak sentinel")
# features are favourite-oriented or symmetric; a model of "favourite won" from them should not beat the moneyline by much
F = match_features(D, "close")
ok = D["q_close"].notna() & ~D["void"]
yf = D.loc[ok, "w_is_fav_close"].astype(float).to_numpy()
Xf = F[ok]
trm = (D.loc[ok, "year"] <= 2021).to_numpy(); tem = (D.loc[ok, "year"] >= 2023).to_numpy(); vam = (D.loc[ok, "year"] == 2022).to_numpy()
off = lg(Xf["q"].to_numpy())
dtr = lgb.Dataset(Xf[trm], yf[trm], init_score=off[trm]); dva = lgb.Dataset(Xf[vam], yf[vam], init_score=off[vam], reference=dtr)
bst = lgb.train(LGB_PARAMS, dtr, 2000, valid_sets=[dva], callbacks=[lgb.early_stopping(100, verbose=False)])
pfw = sig(off + bst.predict(Xf, raw_score=True, num_iteration=bst.best_iteration))
OUT["leak_sentinel_fav_won"] = {"market_ll": round(float(ll(sig(off[tem]), yf[tem]).mean()), 5),
                                "features_on_market_ll": round(float(ll(pfw[tem], yf[tem]).mean()), 5), "rounds": int(bst.best_iteration)}

with open(os.path.join(HERE, "results.json"), "w") as fh:
    json.dump(OUT, fh, indent=1, default=str)
log("done")
