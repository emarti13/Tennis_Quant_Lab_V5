"""What in free match data predicts winners beyond leak-free Elo (and Pinnacle)?

Run:  python run_features.py            (builds features.pkl via build_features.py if missing)
Out:  results.json next to this file.

Splits (event start year): train 2012-2021, validate 2022 (early stopping / tuning), test 2023-2025,
test2 2026 (rows dated before 2026-10-12). Main evaluation subset: both players >= 18 rated matches
(the production pricing minimum); 'all' is reported too. Base = logistic on Elo logit only.
"""
from __future__ import annotations

import json
import os
import sys
import time

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

HERE = os.path.dirname(os.path.abspath(__file__))
SCRATCH = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
RNG = np.random.default_rng(20261020)
NMIN = 18
EPS = 1e-6


def ll(y, p):
    p = np.clip(p, EPS, 1 - EPS)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def logit(p):
    p = np.clip(p, EPS, 1 - EPS)
    return np.log(p / (1 - p))


def boot(d, reps=1000):
    """Mean of per-match paired differences with a match-resampled 95% percentile range."""
    d = np.asarray(d, float)
    n = len(d)
    if n == 0:
        return {"n": 0}
    means = []
    for _ in range(reps // 100):
        idx = RNG.integers(0, n, size=(100, n))
        means.append(d[idx].mean(axis=1))
    means = np.concatenate(means)
    return {"n": int(n), "mean": float(d.mean()), "lo": float(np.percentile(means, 2.5)), "hi": float(np.percentile(means, 97.5))}


# ------------------------------------------------------------------ families
def families(cols):
    fam = {}

    def has(c, *subs):
        return any(s in c for s in subs)

    for c in cols:
        if c in ("elo_logit",):
            continue
        if c in ("surface_c", "indoor", "level_ord", "is_wta", "is_chall", "best_of", "round_rank", "stage", "draw_size"):
            f = "context"
        elif c.startswith("h2h"):
            f = "h2h"
        elif has(c, "surf_win", "surf_tpw", "surf_n"):
            f = "surface_form"
        elif has(c, "over2", "tpw_m_", "tpw2", "upset", "giant"):
            f = "variance"
        elif has(c, "elo_all", "elo_surf", "n_all", "n_surf", "slope", "win_h", "opp_elo") or c == "elo_p":
            f = "ratings_ext"
        elif has(c, "over_h", "games_luck", "win_luck", "_tb_", "dec_h", "bpsave", "bpconv"):
            f = "luck"
        elif has(c, "spw", "rpw", "tpw", "games_h", "stats_points"):
            f = "points"
        elif has(c, "ace", "df_h", "fin_h", "fwon", "swon", "bpf_rate", "bpc_rate", "lefty", "hand", "ht", "bc_", "bigserve"):
            f = "style"
        elif has(c, "rank", "logpts", "seed", "entry"):
            f = "ranking"
        elif has(c, "weeks_since", "m_2w", "m_4w", "ev_m", "prev_round", "switch", "level_prev", "days_since", "home", "age"):
            f = "schedule"
        else:
            f = "other"
        fam.setdefault(f, []).append(c)
    return fam


# ------------------------------------------------------------------ models
LGB_BASE = dict(objective="binary", learning_rate=0.03, feature_fraction=0.7, bagging_fraction=0.8, bagging_freq=1,
                lambda_l2=10.0, verbose=-1, num_threads=2, seed=7)
CONFIGS = [dict(num_leaves=15, min_data_in_leaf=400), dict(num_leaves=31, min_data_in_leaf=200),
           dict(num_leaves=63, min_data_in_leaf=500)]


def fit_lgb(Xtr, ytr, itr, Xva, yva, iva, params):
    p = {**LGB_BASE, **params}
    dtr = lgb.Dataset(Xtr, ytr, init_score=itr, free_raw_data=False)
    dva = lgb.Dataset(Xva, yva, init_score=iva, reference=dtr)
    b = lgb.train(p, dtr, num_boost_round=4000, valid_sets=[dva],
                  callbacks=[lgb.early_stopping(150, verbose=False)])
    return b


def lgb_pred(b, X, init):
    return 1 / (1 + np.exp(-(b.predict(X, raw_score=True) + init)))


def prep_lr(X: pd.DataFrame, ref: pd.DataFrame):
    """Standardize on the train frame; NaN -> 0 with a missing-flag column per distinct missing pattern."""
    lo, hi = ref.quantile(0.01), ref.quantile(0.99)
    mu, sd = ref.clip(lo, hi, axis=1).mean(), ref.clip(lo, hi, axis=1).std().replace(0, 1)
    Z = ((X.clip(lo, hi, axis=1) - mu) / sd)
    miss = X.isna()
    flags = {}
    seen = set()
    for c in X.columns:
        if ref[c].isna().mean() > 0.01:
            h = hash(ref[c].isna().values.tobytes())
            if h not in seen:
                seen.add(h)
                flags[f"miss_{c}"] = miss[c].astype(float)
    return pd.concat([Z.fillna(0.0), pd.DataFrame(flags, index=X.index)], axis=1)


def main():
    t0 = time.time()
    fp = os.path.join(HERE, "features.pkl")
    if not os.path.exists(fp):
        import build_features
        build_features.main()
    D = pd.read_pickle(fp)
    D = D[np.isfinite(D["elo_logit"])].reset_index(drop=True)
    feat_cols = [c for c in D.columns if c not in ("key", "tour", "tid", "level", "date", "year", "a_key", "b_key", "y",
                                                     "n_min", "retired", "group")]
    fam = families(feat_cols)
    print({k: len(v) for k, v in fam.items()}, flush=True)
    tr = D["year"].between(2012, 2021).values
    va = (D["year"] == 2022).values
    te = D["year"].between(2023, 2025).values
    t26 = (D["year"] == 2026).values
    y = D["y"].values.astype(float)
    res = {"n_rows": {"train": int(tr.sum()), "val": int(va.sum()), "test_23_25": int(te.sum()), "test_2026": int(t26.sum())},
           "families": {k: v for k, v in fam.items()}}

    # base: logistic on Elo logit
    base = LogisticRegression(C=1e6).fit(D.loc[tr, ["elo_logit"]], y[tr])
    base_logit = base.decision_function(D[["elo_logit"]])
    p_base = 1 / (1 + np.exp(-base_logit))
    res["base_coef"] = [float(base.coef_[0, 0]), float(base.intercept_[0])]

    X = D[feat_cols].astype(float)

    # LightGBM on everything, residual on top of the base logit; tune on 2022
    best = None
    tune = []
    for cfg in CONFIGS:
        for init_mode in ("residual", "plain"):
            itr = base_logit[tr] if init_mode == "residual" else None
            iva = base_logit[va] if init_mode == "residual" else None
            b = fit_lgb(X[tr], y[tr], itr, X[va], y[va], iva, cfg)
            pv = lgb_pred(b, X[va], base_logit[va] if init_mode == "residual" else 0)
            sc = float(ll(y[va], pv).mean())
            tune.append({"cfg": cfg, "init": init_mode, "iters": b.best_iteration, "val_ll": sc})
            print("tune", cfg, init_mode, b.best_iteration, round(sc, 5), f"{time.time() - t0:.0f}s", flush=True)
            if best is None or sc < best[0]:
                best = (sc, cfg, init_mode, b)
    res["lgb_tuning"] = tune
    res["base_val_ll"] = float(ll(y[va], p_base[va]).mean())
    _, cfg, init_mode, booster = best
    resid = init_mode == "residual"
    init_all = base_logit if resid else np.zeros(len(D))
    p_lgb = lgb_pred(booster, X, init_all)

    # regularized logistic on everything
    Ztr = prep_lr(X[tr], X[tr])
    Zall = prep_lr(X, X[tr])
    lr_best = None
    for C in (0.003, 0.03, 0.3):
        m = LogisticRegression(C=C, max_iter=3000).fit(Ztr, y[tr])
        sc = float(ll(y[va], m.predict_proba(Zall[va])[:, 1]).mean())
        print("lr C", C, round(sc, 5), flush=True)
        if lr_best is None or sc < lr_best[0]:
            lr_best = (sc, C, m)
    p_lr = lr_best[2].predict_proba(Zall)[:, 1]
    res["lr_C"] = lr_best[1]

    def evaluate(p, name):
        out = {}
        for split, msk in (("test_23_25", te), ("test_2026", t26), ("val_2022", va)):
            for sub, sm in (("nmin18", D["n_min"].values >= NMIN), ("all", np.ones(len(D), bool))):
                for grp in ("ALL", "ATP", "Challenger", "WTA"):
                    gm = msk & sm & ((D["group"].values == grp) if grp != "ALL" else True)
                    if gm.sum() == 0:
                        continue
                    d = ll(y[gm], p[gm]) - ll(y[gm], p_base[gm])
                    r = boot(d)
                    r["base_ll"] = float(ll(y[gm], p_base[gm]).mean())
                    r["model_ll"] = float(ll(y[gm], p[gm]).mean())
                    out[f"{split}|{sub}|{grp}"] = r
        res.setdefault("eval", {})[name] = out

    evaluate(p_lgb, "lgb_all")
    evaluate(p_lr, "lr_all")
    print("main eval done", f"{time.time() - t0:.0f}s", flush=True)

    # importance
    imp = pd.Series(booster.feature_importance("gain"), index=feat_cols).sort_values(ascending=False)
    res["gain_top30"] = {k: float(v) for k, v in (imp / imp.sum()).head(30).items()}
    contrib = booster.predict(X[te], pred_contrib=True)[:, :-1]
    ca = pd.Series(np.abs(contrib).mean(axis=0), index=feat_cols).sort_values(ascending=False)
    res["contrib_abs_top30"] = {k: float(v) for k, v in ca.head(30).items()}
    fam_contrib = {f: float(np.abs(contrib[:, [feat_cols.index(c) for c in cs]].sum(axis=1)).mean()) for f, cs in fam.items()}
    res["contrib_abs_by_family"] = fam_contrib

    # ablation: drop-one and add-one (to Elo + context), LightGBM residual on base, fixed cfg
    abl = {}
    evm = te & (D["n_min"].values >= NMIN)
    e26 = t26 & (D["n_min"].values >= NMIN)

    def run_cols(cols):
        b = fit_lgb(X.loc[tr, cols], y[tr], base_logit[tr], X.loc[va, cols], y[va], base_logit[va], cfg)
        p = lgb_pred(b, X[cols], base_logit)
        return {"test_23_25": boot(ll(y[evm], p[evm]) - ll(y[evm], p_base[evm])),
                "test_2026": boot(ll(y[e26], p[e26]) - ll(y[e26], p_base[e26])), "iters": b.best_iteration}

    others = [f for f in fam if f != "context"]
    abl["context_only"] = run_cols(fam["context"])
    print("ablation context", abl["context_only"]["test_23_25"], flush=True)
    for f in others:
        abl[f"add_{f}"] = run_cols(fam["context"] + fam[f])
        abl[f"drop_{f}"] = run_cols([c for c in feat_cols if c not in fam[f]])
        print("ablation", f, round(abl[f"add_{f}"]["test_23_25"]["mean"], 5), round(abl[f"drop_{f}"]["test_23_25"]["mean"], 5),
              f"{time.time() - t0:.0f}s", flush=True)
    res["ablation"] = abl

    # ------------------------------------------------------------------ market test (2026, Pinnacle)
    tr2 = D["year"].between(2012, 2024).values
    va2 = (D["year"] == 2025).values
    base2 = LogisticRegression(C=1e6).fit(D.loc[tr2, ["elo_logit"]], y[tr2])
    bl2 = base2.decision_function(D[["elo_logit"]])
    b2 = fit_lgb(X[tr2], y[tr2], bl2[tr2] if resid else None, X[va2], y[va2], bl2[va2] if resid else None, cfg)
    p2 = lgb_pred(b2, X, bl2 if resid else 0)
    D["p_model"] = p2
    D["p_elo2"] = 1 / (1 + np.exp(-bl2))
    oc = pd.read_pickle(os.path.join(SCRATCH, "oc_j.pkl"))
    oc = oc[oc["start"] < pd.Timestamp("2026-10-12", tz="UTC")]
    j = oc.merge(D[["key", "a_key", "b_key", "y", "p_model", "p_elo2"] + feat_cols], on="key", how="inner", suffixes=("", "_d"))
    s = np.where(j["player1_id"] == j["a_key"], 1.0, np.where(j["player1_id"] == j["b_key"], -1.0, np.nan))
    j = j[np.isfinite(s)].copy()
    s = s[np.isfinite(s)]
    j["s"] = s
    j["pm"] = np.where(s > 0, j["p_model"], 1 - j["p_model"])
    j["pe"] = np.where(s > 0, j["p_elo2"], 1 - j["p_elo2"])
    chk = (np.where(s > 0, j["y_d"], 1 - j["y_d"]) == j["y"]).mean()
    mk = {"oc_rows": int(len(oc)), "joined": int(len(j)), "orientation_check_y_agree": float(chk)}
    j = j[np.isfinite(j["open_p1"]) & np.isfinite(j["close_p1"])].copy()
    j["lo"], j["lc"], j["lm"] = logit(j["open_p1"]), logit(j["close_p1"]), logit(j["pm"])
    yy = j["y"].values.astype(float)
    mtr = (j["start"].dt.month <= 6).values
    mte = ~mtr
    mk["n_train_janjun"], mk["n_test_jul_oct"] = int(mtr.sum()), int(mte.sum())
    # whole 2026: historical model vs Pinnacle
    for nm, col in (("model", "pm"), ("elo", "pe")):
        mk[f"all2026_{nm}_minus_open"] = boot(ll(yy, j[col].values) - ll(yy, j["open_p1"].values))
        mk[f"all2026_{nm}_minus_close"] = boot(ll(yy, j[col].values) - ll(yy, j["close_p1"].values))
    mk["ll_open_all2026"] = float(ll(yy, j["open_p1"].values).mean())
    mk["ll_close_all2026"] = float(ll(yy, j["close_p1"].values).mean())
    # residual models on logit(open), fit Jan-Jun, test Jul-Oct
    top = [c for c in res["contrib_abs_top30"] if (c.startswith("d_") or c in ("elo_logit", "bc_p_logit", "h2h_diff", "h2h_over"))][:10]
    feats = {"open_only": ["lo"], "open+model": ["lo", "lm"], "open+elo": ["lo", "le"]}
    j["le"] = logit(j["pe"])
    for c in top:
        j[f"o_{c}"] = j[c].astype(float) * j["s"]
    feats["open+model+top10"] = ["lo", "lm"] + [f"o_{c}" for c in top]
    preds = {}
    for name, cols in feats.items():
        Xm = j[cols].astype(float)
        mu, sd = Xm[mtr].mean(), Xm[mtr].std().replace(0, 1)
        Z = ((Xm - mu) / sd).fillna(0.0)
        C = 1e6 if len(cols) <= 2 else 0.05
        lrm = LogisticRegression(C=C, max_iter=2000).fit(Z[mtr], yy[mtr])
        preds[name] = lrm.predict_proba(Z)[:, 1]
        mk[f"resid_{name}_coef"] = dict(zip(cols, (lrm.coef_[0] / sd.values).round(4).tolist()))
        mk[f"resid_{name}_minus_open"] = boot(ll(yy[mte], preds[name][mte]) - ll(yy[mte], j["open_p1"].values[mte]))
        mk[f"resid_{name}_minus_close"] = boot(ll(yy[mte], preds[name][mte]) - ll(yy[mte], j["close_p1"].values[mte]))
    mk["ll_open_test"] = float(ll(yy[mte], j["open_p1"].values[mte]).mean())
    mk["ll_close_test"] = float(ll(yy[mte], j["close_p1"].values[mte]).mean())
    mk["ll_model_test"] = float(ll(yy[mte], j["pm"].values[mte]).mean())
    mk["model_minus_open_test"] = boot(ll(yy[mte], j["pm"].values[mte]) - ll(yy[mte], j["open_p1"].values[mte]))
    # open-to-close move toward the model's side
    mv = (j["close_p1"] - j["open_p1"]).values
    for name, p in (("raw_model", j["pm"].values), ("raw_elo", j["pe"].values), ("resid_open+model", preds["open+model"])):
        sg = np.sign(p - j["open_p1"].values)
        mk[f"clv_{name}_test"] = boot(sg[mte] * mv[mte])
        mk[f"clv_{name}_all2026"] = boot(sg * mv)
        big = np.abs(p - j["open_p1"].values) > 0.05
        mk[f"clv_{name}_test_gap>5pt"] = boot((sg * mv)[mte & big])
    # null checks for the move: drift toward 50% (no model), and whether the move follows the model
    # beyond Elo (OLS of close-open on model-open and elo-open, match-resampled ranges)
    sg50 = np.sign(0.5 - j["open_p1"].values)
    mk["clv_toward_50pct_test"] = boot(sg50[mte] * mv[mte])
    Xo = np.c_[np.ones(len(j)), j["pm"].values - j["open_p1"].values, j["pe"].values - j["open_p1"].values]
    coefs = []
    for _ in range(500):
        ii = RNG.integers(0, len(j), len(j))
        coefs.append(np.linalg.lstsq(Xo[ii], mv[ii], rcond=None)[0])
    coefs = np.array(coefs)
    full = np.linalg.lstsq(Xo, mv, rcond=None)[0]
    mk["move_ols_all2026"] = {n: {"coef": float(full[k]), "lo": float(np.percentile(coefs[:, k], 2.5)),
                                  "hi": float(np.percentile(coefs[:, k], 97.5))} for k, n in enumerate(["const", "model_minus_open", "elo_minus_open"])}
    for grp in ("ATP", "CHALLENGER", "WTA"):
        gm = (j["family"] == grp).values
        mk[f"clv_raw_model_all2026_{grp}"] = boot((np.sign(j["pm"].values - j["open_p1"].values) * mv)[gm])
        mk[f"all2026_model_minus_open_{grp}"] = boot(ll(yy[gm], j["pm"].values[gm]) - ll(yy[gm], j["open_p1"].values[gm]))
    j[["fixture_id", "key", "start", "family", "y", "open_p1", "close_p1", "pm", "pe"]].to_pickle(os.path.join(HERE, "market_join.pkl"))
    mk["families_by_group"] = j.groupby("family").size().to_dict()
    mk["top10_used"] = top
    res["market"] = mk
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(res, f, indent=1, default=str)
    print("done", f"{time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
