"""Step 2 and 3 on the Kaggle odds (2014-2025): models trained on top of the market's price, rolling
yearly tests, segment search, and betting at the file's best and average odds.

Market base: the de-vigged consensus (mean logit over Betfair, Bet365, Ladbrokes, Unibet, each
de-vigged multiplicatively) at the open or at the close. There is no Pinnacle in the file; the
Betfair-only benchmark is reported on its subset.

Rolling folds: test year Y in 2017..2025; train years 2014..Y-2; early stopping and config choice
on Y-1. Features: the leak-free table research_tests/features/features.pkl (Elo with exact parity,
EW serve/return, schedule/workload, ranking, H2H, style, context), oriented by key hash; plus
month, and for the close base the open-to-close move of the consensus.

Models: lgb_resid (LightGBM, init score = market logit), lr_resid (L2 logistic with the market
logit as a feature), lgb_group (lgb_resid per ATP / Challenger / WTA), lgb_alone (no market) and
blend (logistic on market logit + lgb_alone logit, fit on the validation year), ens (mean logit of
lgb_resid, lr_resid, lgb_group).

Retired matches and walkovers are excluded (books settle them differently).
Run: python research_tests/kaggle_odds/run_market_models.py -> preds.pkl (scratchpad), results.json
"""
from __future__ import annotations

import json
import os
import sys
import time
import warnings

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "research_tests", "features"))
from run_features import prep_lr  # noqa: E402
sys.path.insert(0, os.path.join(ROOT, "research_tests"))
from qa import QA  # noqa: E402

SCRATCH = os.environ.get("FS_SCRATCH", "/tmp/claude-0/-home-user-Tennis-Quant-Lab-V5/a0609b44-84ba-59ef-a5f1-f66b68d375ec/scratchpad")
RNG = np.random.default_rng(20261021)
EPS = 1e-6
BOOKS = ["Betfair", "bet365", "Ladbrokes", "Unibet"]
TEST_YEARS = list(range(2017, 2026))
LGB_BASE = dict(objective="binary", learning_rate=0.02, feature_fraction=0.6, bagging_fraction=0.8, bagging_freq=1,
                lambda_l2=20.0, verbose=-1, num_threads=4, seed=11)
CONFIGS = [dict(num_leaves=7, min_data_in_leaf=600), dict(num_leaves=15, min_data_in_leaf=400),
           dict(num_leaves=31, min_data_in_leaf=300)]
META = ("key", "tour", "tid", "level", "date", "year", "a_key", "b_key", "y", "n_min", "retired", "group")


def lg(p):
    p = np.clip(p, EPS, 1 - EPS)
    return np.log(p / (1 - p))


def sig(x):
    return 1 / (1 + np.exp(-x))


def ll(y, p):
    p = np.clip(p, EPS, 1 - EPS)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def boot_mean(v, reps=1000):
    v = np.asarray(v, float)
    v = v[np.isfinite(v)]
    n = len(v)
    if n < 2:
        return {"n": int(n)}
    idx = RNG.integers(0, n, size=(reps, n)) if n * reps < 6e7 else None
    if idx is None:
        means = np.array([v[RNG.integers(0, n, n)].mean() for _ in range(reps)])
    else:
        means = v[idx].mean(1)
    return {"n": int(n), "mean": round(float(v.mean()), 5), "lo": round(float(np.percentile(means, 2.5)), 5),
            "hi": round(float(np.percentile(means, 97.5)), 5)}


# ------------------------------------------------------------------ data
def load():
    F = pd.read_pickle(os.path.join(ROOT, "research_tests", "features", "features.pkl"))
    J = pd.read_pickle(os.path.join(SCRATCH, "kaggle_joined.pkl"))
    J = J.drop(columns=["tour", "tid", "level", "date", "y"])
    D = F.merge(J, on="key", how="inner")
    QA("market_models_cache").check("odds rows found in the feature table (caches built from the same load)",
                                    J.key.isin(F.key).mean(), 0.98, 1.0)
    D = D[~D.retired.astype(bool) & (D.completed == 1)].reset_index(drop=True)
    for when, suf in (("close", ""), ("open", "_opening")):
        L, n = np.zeros(len(D)), np.zeros(len(D))
        for b in BOOKS:
            oa, ob = D[f"{b}{suf}_A"].to_numpy(float), D[f"{b}{suf}_B"].to_numpy(float)
            ok = np.isfinite(oa) & np.isfinite(ob) & (oa > 1) & (ob > 1)
            p = np.where(ok, (1 / oa) / (1 / oa + 1 / ob), np.nan)
            D[f"p_{b}_{when}"] = p
            L += np.where(ok, lg(p), 0)
            n += ok
        D[f"mkt_{when}"] = np.where(n > 0, L / np.maximum(n, 1), np.nan)      # consensus logit
        D[f"nbooks_{when}"] = n
        for s in ("A", "B"):
            odds = np.column_stack([D[f"{b}{suf}_{s}"].to_numpy(float) for b in BOOKS])
            odds[odds <= 1] = np.nan
            D[f"avg{suf}_{s}"] = np.nanmean(odds, 1)
    D = D[np.isfinite(D.mkt_close) & np.isfinite(D.mkt_open)].reset_index(drop=True)
    D["month"] = D.mdate.dt.month.astype(float)
    D["move"] = D.mkt_close - D.mkt_open
    D["kyear"] = D.mdate.dt.year
    qa = QA("market_models_load")
    qa.check("rows (completed, non-retired, with features and both prices)", len(D), 80000, 110000)
    qa.check("A win share", D.y.mean(), 0.48, 0.52)
    qa.check("consensus close log loss", ll(D.y.to_numpy(), sig(D.mkt_close.to_numpy())).mean(), 0.56, 0.63)
    qa.check("consensus close beats open (log loss gap)",
             (ll(D.y.to_numpy(), sig(D.mkt_open.to_numpy())) - ll(D.y.to_numpy(), sig(D.mkt_close.to_numpy()))).mean(), 0.0, 0.03)
    qa.zero("duplicate keys", D.key.duplicated().sum())
    qa.save(HERE)
    return D


def feature_cols(D):
    return [c for c in D.columns if c not in META and (c.startswith(("d_", "a_", "b_", "h2h", "bc_", "elo_"))
            or c in ("surface_c", "indoor", "level_ord", "is_wta", "is_chall", "best_of", "round_rank", "stage",
                     "draw_size", "entry_known", "hand_pair", "bigserve_vs_return", "lefty_vs_righty_ace", "month"))]


# ------------------------------------------------------------------ models
def fit_lgb(X, y, init, Xv, yv, initv):
    best = None
    for cfg in CONFIGS:
        dtr = lgb.Dataset(X, y, init_score=init, free_raw_data=False)
        dva = lgb.Dataset(Xv, yv, init_score=initv, reference=dtr)
        b = lgb.train({**LGB_BASE, **cfg}, dtr, num_boost_round=3000, valid_sets=[dva],
                      callbacks=[lgb.early_stopping(150, verbose=False)])
        pv = sig(b.predict(Xv, raw_score=True) + initv)
        s = ll(yv, pv).mean()
        if best is None or s < best[0]:
            best = (s, b, cfg, b.best_iteration)
    return best


def fit_all(D, tr, va, base, cols):
    """Fit every model on rows tr (early stopping / choices on va). Returns the fitted bundle."""
    c = cols + (["move", "nbooks_close"] if base == "close" else [])
    X, y, m = D[c], D.y.to_numpy(float), D[f"mkt_{base}"].to_numpy()
    M = {"cols": c, "info": {}}
    s, M["lgb_resid"], cfg, it = fit_lgb(X[tr], y[tr], m[tr], X[va], y[va], m[va])
    M["info"]["lgb_resid"] = {"cfg": cfg, "rounds": int(it)}
    M["group"] = {}
    for g in ("ATP", "Challenger", "WTA"):
        gm = (D.group == g).to_numpy()
        if (tr & gm).sum() < 2000:
            continue
        s, M["group"][g], cfg, it = fit_lgb(X[tr & gm], y[tr & gm], m[tr & gm], X[va & gm], y[va & gm], m[va & gm])
        M["info"].setdefault("lgb_group_rounds", {})[g] = int(it)
    M["lr_ref"] = X[tr]
    Ztr = prep_lr(X[tr], X[tr]); Zva = prep_lr(X[va], X[tr]).reindex(columns=Ztr.columns, fill_value=0.0)
    M["lr_cols"] = Ztr.columns
    best = None
    for C in (0.003, 0.03):
        lr = LogisticRegression(C=C, max_iter=400).fit(np.c_[m[tr], Ztr.values], y[tr])
        sc = ll(y[va], lr.predict_proba(np.c_[m[va], Zva.values])[:, 1]).mean()
        if best is None or sc < best[0]:
            best = (sc, lr, C)
    M["lr"], M["info"]["lr_C"] = best[1], best[2]
    s, M["alone"], cfg, it = fit_lgb(X[tr], y[tr], np.zeros(tr.sum()), X[va], y[va], np.zeros(va.sum()))
    pa_va = M["alone"].predict(X[va], raw_score=True)
    M["blend"] = LogisticRegression(C=10.0).fit(np.c_[m[va], pa_va], y[va])
    M["info"]["blend_coef"] = [round(float(x), 3) for x in M["blend"].coef_[0]]
    return M


def predict_all(M, X, m, group):
    """Predictions of every model for feature frame X, market logit m, group labels."""
    X = X[M["cols"]]
    out = pd.DataFrame(index=X.index)
    out["mkt"] = sig(m)
    out["lgb_resid"] = sig(M["lgb_resid"].predict(X, raw_score=True) + m)
    pg = out["lgb_resid"].to_numpy().copy()
    for g, b in M["group"].items():
        sel = (np.asarray(group) == g)
        if sel.any():
            pg[sel] = sig(b.predict(X[sel], raw_score=True) + m[sel])
    out["lgb_group"] = pg
    Z = prep_lr(X, M["lr_ref"]).reindex(columns=M["lr_cols"], fill_value=0.0)
    out["lr_resid"] = M["lr"].predict_proba(np.c_[m, Z.values])[:, 1]
    pa = M["alone"].predict(X, raw_score=True)
    out["lgb_alone"] = sig(pa)
    out["blend"] = M["blend"].predict_proba(np.c_[m, pa])[:, 1]
    out["ens"] = sig((lg(out.lgb_resid) + lg(out.lr_resid) + lg(out.lgb_group)) / 3)
    return out


def fold(D, Y, base, cols):
    tr = (D.kyear <= Y - 2).to_numpy()
    va = (D.kyear == Y - 1).to_numpy()
    te = (D.kyear == Y).to_numpy()
    M = fit_all(D, tr, va, base, cols)
    out = predict_all(M, D[te], D[f"mkt_{base}"].to_numpy()[te], D.group.to_numpy()[te])
    return out, M["info"]


# ------------------------------------------------------------------ evaluation
MODELS = ["lgb_resid", "lgb_group", "lr_resid", "blend", "ens", "lgb_alone"]


def eval_ll(P, D, base):
    out = {}
    y = D.loc[P.index, "y"].to_numpy(float)
    llm = ll(y, P.mkt.to_numpy())
    out["market_logloss"] = round(float(llm.mean()), 5)
    for mdl in MODELS:
        d = llm - ll(y, P[mdl].to_numpy())                     # > 0: model better than the market
        out[mdl] = {"gain_all": boot_mean(d)}
        yr = D.loc[P.index, "kyear"].to_numpy()
        out[mdl]["by_year"] = {int(Y): round(float(d[yr == Y].mean()), 5) for Y in TEST_YEARS}
        for g in ("ATP", "Challenger", "WTA"):
            gm = (D.loc[P.index, "group"] == g).to_numpy()
            out[mdl][f"gain_{g}"] = boot_mean(d[gm])
    # Betfair-only benchmark subset (close / open as the base)
    bf = D.loc[P.index, f"p_Betfair_{base}"].to_numpy()
    ok = np.isfinite(bf)
    out["betfair_subset"] = {"n": int(ok.sum()), "betfair_logloss": round(float(ll(y[ok], bf[ok]).mean()), 5),
                             "consensus_logloss": round(float(llm[ok].mean()), 5),
                             "ens_logloss": round(float(ll(y[ok], P.ens.to_numpy()[ok]).mean()), 5),
                             "ens_gain_vs_betfair": boot_mean(ll(y[ok], bf[ok]) - ll(y[ok], P.ens.to_numpy()[ok]))}
    return out


def bets(P, D, base, model, thr, odds_kind):
    """One bet per match on the side with the larger EV if EV > thr. Returns DataFrame of bets."""
    suf = "" if base == "close" else "_opening"
    dd = D.loc[P.index]
    if odds_kind == "best":
        oa, ob = dd[f"best{suf}_A"].to_numpy(float), dd[f"best{suf}_B"].to_numpy(float)
    else:
        oa, ob = dd[f"avg{suf}_A"].to_numpy(float), dd[f"avg{suf}_B"].to_numpy(float)
    p = P[model].to_numpy()
    ea, eb = p * oa - 1, (1 - p) * ob - 1
    take_a = (ea > thr) & (ea >= eb)
    take_b = (eb > thr) & (eb > ea)
    y = dd.y.to_numpy()
    ret = np.where(take_a, np.where(y == 1, oa - 1, -1.0), np.where(take_b, np.where(y == 0, ob - 1, -1.0), np.nan))
    pc = sig(dd.mkt_close.to_numpy())
    clv = np.where(take_a, oa * pc - 1, np.where(take_b, ob * (1 - pc) - 1, np.nan))   # vs close consensus fair
    sel = take_a | take_b
    return pd.DataFrame({"ret": ret[sel], "clv": clv[sel], "year": dd.kyear.to_numpy()[sel],
                         "side_a": take_a[sel], "idx": dd.index[sel]})


def eval_bets(P, D, base):
    out = {}
    for model in ["mkt_flat_fav"] + MODELS:
        for kind in ("best", "avg"):
            for thr in (0.0, 0.02, 0.05):
                if model == "mkt_flat_fav":
                    if thr > 0:
                        continue
                    Q = P.copy()
                    Q["mkt_flat_fav"] = np.where(P.mkt > 0.5, 1.0, 0.0)   # always back the favourite
                    b = bets(Q, D, base, "mkt_flat_fav", -1.0, kind)
                else:
                    b = bets(P, D, base, model, thr, kind)
                if len(b) < 50:
                    continue
                cell = {"all": boot_mean(b.ret), "clv": boot_mean(b.clv) if base == "open" else None,
                        "disc_2017_21": boot_mean(b.ret[b.year <= 2021]), "conf_2022_25": boot_mean(b.ret[b.year >= 2022])}
                out[f"{model}|{kind}|ev>{thr:.2f}"] = cell
    return out


# ------------------------------------------------------------------ segment search
def side_table(P, D, base, model):
    """Two rows per match (side A, side B) with side attributes, price and model probability."""
    suf = "" if base == "close" else "_opening"
    dd = D.loc[P.index]
    rows = []
    for s, o in (("A", "B"), ("B", "A")):
        a, b = s.lower(), o.lower()
        win = (dd.y == 1) if s == "A" else (dd.y == 0)
        pm = P.mkt if s == "A" else 1 - P.mkt
        pmod = P[model] if s == "A" else 1 - P[model]
        r = pd.DataFrame({
            "idx": dd.index, "year": dd.kyear, "win": win.astype(float), "pm": pm, "pmod": pmod,
            "best": dd[f"best{suf}_{s}"], "avg": dd[f"avg{suf}_{s}"],
            "fav": (pm > 0.5).astype(int), "home": dd[f"{a}_home"].fillna(0), "opp_home": dd[f"{b}_home"].fillna(0),
            "qual_entry": dd[f"{a}_entry_Q"].fillna(0), "qualifying_rd": (dd.stage == 0).astype(int),
            "rank_band": pd.cut(dd[f"{a}_rank"], [0, 10, 30, 75, 150, 300, 1e5], labels=False),
            "opp_rank_band": pd.cut(dd[f"{b}_rank"], [0, 10, 30, 75, 150, 300, 1e5], labels=False),
            "workload": pd.cut(dd[f"{a}_ev_matches_before"].fillna(0), [-1, 0, 1, 2, 3, 99], labels=False),
            "prev_long": (dd[f"{a}_prev_round_minutes"] > 150).astype(int),
            "rust": (dd[f"{a}_weeks_since_prev_event"] >= 6).astype(int),
            "early_season": (dd.month <= 2).astype(int), "surface": dd.surface_c, "indoor": dd.indoor,
            "round": dd.k_round.astype(str), "group": dd.group, "best_of": dd.best_of,
            "price_band": pd.cut(pm, [0, 0.2, 0.35, 0.5, 0.65, 0.8, 1], labels=False),
            "age_band": pd.cut(dd[f"{a}_age"], [0, 21, 25, 30, 33, 50], labels=False),
        })
        rows.append(r)
    S = pd.concat(rows, ignore_index=True)
    S["ret_best"] = np.where(S.win == 1, S.best - 1, -1.0)
    S["ret_avg"] = np.where(S.win == 1, S.avg - 1, -1.0)
    S["edge_best"] = S.pmod * S.best - 1
    return S


ATTRS = ["fav", "home", "opp_home", "qual_entry", "qualifying_rd", "rank_band", "opp_rank_band", "workload",
         "prev_long", "rust", "early_season", "surface", "indoor", "round", "group", "best_of", "price_band", "age_band"]


def segment_search(S, min_n=400, top=15):
    """All single attributes and pairs; flat bets at avg odds and model-filtered (edge_best > 0) bets at
    best odds. Discovery 2017-2021 (ranked by t), confirmation 2022-2025 on the top cells only."""
    disc, conf = S[S.year <= 2021], S[S.year >= 2022]
    cells = []
    attrs = [a for a in ATTRS if S[a].notna().any()]
    combos = [(a,) for a in attrs] + [(a, b) for i, a in enumerate(attrs) for b in attrs[i + 1:]]
    for rule in ("flat_avg", "model_best"):
        for combo in combos:
            dsub = disc if rule == "flat_avg" else disc[disc.edge_best > 0]
            col = "ret_avg" if rule == "flat_avg" else "ret_best"
            g = dsub.groupby(list(combo), observed=True)[col].agg(["mean", "std", "count"])
            g = g[g["count"] >= min_n]
            for k, r in g.iterrows():
                t = r["mean"] / (r["std"] / np.sqrt(r["count"]))
                cells.append((rule, combo, k if isinstance(k, tuple) else (k,), float(r["mean"]), int(r["count"]), float(t)))
    C = pd.DataFrame(cells, columns=["rule", "attrs", "values", "disc_roi", "disc_n", "disc_t"])
    n_cells = len(C)
    C = C.sort_values("disc_t", ascending=False).head(top)
    out = []
    for r in C.itertuples():
        sub = conf if r.rule == "flat_avg" else conf[conf.edge_best > 0]
        m = np.ones(len(sub), bool)
        for a, v in zip(r.attrs, r.values):
            m &= (sub[a] == v).to_numpy()
        col = "ret_avg" if r.rule == "flat_avg" else "ret_best"
        out.append({"rule": r.rule, "segment": dict(zip(r.attrs, [str(v) for v in r.values])),
                    "disc_roi": round(r.disc_roi, 4), "disc_n": r.disc_n, "disc_t": round(r.disc_t, 2),
                    "conf": boot_mean(sub[col].to_numpy()[m])})
    return {"cells_tested": n_cells, "top_by_discovery_t": out}


def main():
    t0 = time.time()
    D = load()
    cols = feature_cols(D)
    print("rows", len(D), "features", len(cols), flush=True)
    R = {"rows": int(len(D)), "n_features": len(cols),
         "rows_by_year": D.groupby("kyear").size().astype(int).to_dict()}
    for base in ("close", "open"):
        parts, infos = [], {}
        for Y in TEST_YEARS:
            p, info = fold(D, Y, base, cols)
            parts.append(p); infos[Y] = info
            print(base, Y, "done", f"{time.time() - t0:.0f}s", info["lgb_resid"], flush=True)
        P = pd.concat(parts)
        P.to_pickle(os.path.join(SCRATCH, f"kaggle_preds_{base}.pkl"))
        R[base] = {"fold_info": infos, "logloss": eval_ll(P, D, base), "bets": eval_bets(P, D, base)}
        S = side_table(P, D, base, "ens")
        R[base]["segments"] = segment_search(S)
        json.dump(R, open(os.path.join(HERE, "results_market_models.json"), "w"), indent=1, default=str)
    D[["key", "kyear", "mkt_close", "mkt_open"]].to_pickle(os.path.join(SCRATCH, "kaggle_D_index.pkl"))
    print("done", f"{time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
