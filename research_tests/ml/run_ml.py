"""Can an ML model on top of Pinnacle beat Pinnacle's close (or bet the execution books)?

Usage:  python run_ml.py            (writes results.json next to this file)

Research only. Chronological: train on fixtures starting Jan-Jun 2026, test Jul 1 - Oct 12 2026.
Nothing from fixtures starting 2026-10-13 or later (sealed period).

Decision time T (hours before the start: 12 or 1, plus 6 as a middle point): only prices whose
quote time is <= start - T are used. The market at T is Pinnacle's de-vigged price standing at T
(fixtures without one are not priced at T). Models predict the residual over that market:
- L2 logistic with offset logit(Pinnacle at T) (Newton, ridge chosen on a time-held-out slice);
- LightGBM (binary, init_score = logit(Pinnacle at T), depth 2 or 3, lr 0.05, early stopping on
  the time-held-out slice May 15 - Jun 30, then refit on all of Jan-Jun with the chosen rounds).
Betting: at each execution book's own price standing at T (raw decimal odds, vig included; no
extra fees at these sportsbooks), on the side with the larger EV when EV > threshold.
"""
from __future__ import annotations

import glob
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import lightgbm as lgb

REPO = Path("/home/user/Tennis_Quant_Lab_V5")
HERE = Path(__file__).resolve().parent
SCRATCH = HERE.parents[1]
sys.path.insert(0, str(REPO))
from v5_devig import book_lam, devig  # noqa: E402

SEALED_FROM = pd.Timestamp("2026-10-13", tz="UTC")
TEST_FROM = pd.Timestamp("2026-07-01", tz="UTC")
VAL_FROM = pd.Timestamp("2026-05-15", tz="UTC")
EXEC = ["betrivers", "draftkings", "bet365"]
BOOKS = ["pinnacle"] + EXEC
CHECKS = [("open", None), ("t24h", 24), ("t12h", 12), ("t6h", 6), ("t1h", 1), ("close", 0)]
FATIGUE = ["prev_in_event_minutes", "prev_in_event_sets", "prev_in_event_went_distance", "ev_matches_before",
           "ev_minutes_before", "ev_quali_matches_before", "weeks_since_prev_event", "matches_last_4w",
           "layoff_8w_plus", "retired_last_match", "retired_or_wo_last5"]
B = 2000
rng = np.random.default_rng(20261020)


def logit(p):
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def L(s: pd.Series) -> pd.Series:
    """logit of a Series, NaN kept."""
    return pd.Series(logit(s.fillna(0.5)), index=s.index).where(s.notna())


def sig(z):
    return 1 / (1 + np.exp(-z))


def ll(p, y):
    p = np.clip(p, 1e-12, 1 - 1e-12)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def paired(a, b):
    d = a - b
    bs = d[rng.integers(0, len(d), size=(B, len(d)))].mean(axis=1)
    return {"mean": round(float(d.mean()), 5), "ci95": [round(float(np.percentile(bs, 2.5)), 5), round(float(np.percentile(bs, 97.5)), 5)]}


def boot(x):
    x = np.asarray(x, float)
    if len(x) == 0:
        return {"n": 0}
    bs = x[rng.integers(0, len(x), size=(B, len(x)))].mean(axis=1)
    return {"n": int(len(x)), "mean": round(float(x.mean()), 4), "ci95": [round(float(np.percentile(bs, 2.5)), 4), round(float(np.percentile(bs, 97.5)), 4)]}


# ------------------------------------------------------------------ data
def load_points() -> pd.DataFrame:
    pts = pd.concat([pd.read_csv(p, dtype={"fixture_id": str}) for p in sorted(glob.glob(str(REPO / "market_history/price_points/*.csv")))])
    return pts[pts["bookmaker"].isin(BOOKS)]


def moneyline_wide(pts: pd.DataFrame) -> pd.DataFrame:
    """Per fixture: for each book and checkpoint, raw p1/p2 odds, quote time, de-vigged p1."""
    ml = pts[pts["market_group"] == "moneyline"].copy()
    ml.loc[ml["close_stale"].astype(str) == "True", ["close_price", "close_utc"]] = np.nan
    out = {}
    for c, _ in CHECKS:
        for s in ("p1", "p2"):
            part = ml[ml["side"] == s].drop_duplicates(["fixture_id", "bookmaker"]).set_index(["fixture_id", "bookmaker"])
            out[(c, s)] = part[f"{c}_price"]
            out[(c, s + "_utc")] = pd.to_datetime(part[f"{c}_utc"], utc=True)
    w = pd.DataFrame({f"{c}_{s}": v for (c, s), v in out.items()}).unstack("bookmaker")
    w.columns = [f"{b}_{a}" for a, b in w.columns]
    for b in BOOKS:
        lam = book_lam(b)
        for c, _ in CHECKS:
            a, d = w.get(f"{b}_{c}_p1"), w.get(f"{b}_{c}_p2")
            if a is None:
                continue
            ok = (a > 1) & (d > 1)
            w.loc[~ok, [f"{b}_{c}_p1", f"{b}_{c}_p2"]] = np.nan
            w[f"{b}_{c}_utc"] = w[f"{b}_{c}_p1_utc"].where(ok)
            w[f"{b}_{c}_q"] = np.nan
            idx = ok[ok].index
            w.loc[idx, f"{b}_{c}_q"] = [devig([x, z], lam)[0] for x, z in zip(a[idx], d[idx])]
    return w


def main_line(pts: pd.DataFrame, group: str, side: str, col: str) -> pd.Series:
    """Pinnacle's main line (most balanced prices) for `group` using prices in column `col`."""
    g = pts[(pts["bookmaker"] == "pinnacle") & (pts["market_group"] == group)]
    a = g[g["side"] == side][["fixture_id", "market_id", "line", col]]
    other = g[g["side"] != side][["fixture_id", "market_id", col]].rename(columns={col: "o"})
    m = a.merge(other, on=["fixture_id", "market_id"]).dropna(subset=[col, "o"])
    m = m[(m[col] > 1) & (m["o"] > 1)]
    m["bal"] = np.abs(np.log(m[col] / m["o"]))
    m = m.sort_values("bal").drop_duplicates("fixture_id").set_index("fixture_id")
    return pd.DataFrame({"line": m["line"].astype(float), "q": (1 / m[col]) / (1 / m[col] + 1 / m["o"])})


def build() -> pd.DataFrame:
    j = pd.read_pickle(SCRATCH / "oc_j.pkl")
    j = j[(j["start"] < SEALED_FROM) & (j["n_min"] >= 18)].copy()
    ms = pd.read_pickle(SCRATCH / "matches_serve.pkl").drop_duplicates("key").set_index("key")
    j = j.join(ms[["level", "round", "rank", "stage", "best_of"]], on="key")
    cpf = pd.read_pickle(HERE / "cp_feats.pkl").drop_duplicates("key").set_index("key")
    j = j.join(cpf[["p_pt0", "p_pt", "pace", "S_w", "S_l", "R_w", "R_l", "pace_pts"]], on="key")
    flip = (j["y"] == 0).to_numpy()                         # cp features are winner-first -> fixture p1
    j["pt_p1"] = np.where(flip, 1 - j["p_pt0"], j["p_pt0"])
    j["ptpace_p1"] = np.where(flip, 1 - j["p_pt"], j["p_pt"])
    j["serve_gap"] = np.where(flip, -1, 1) * ((j["S_w"] - j["R_l"]) - (j["S_l"] - j["R_w"]))
    pts = load_points()
    w = moneyline_wide(pts)
    j = j.join(w, on="fixture_id")
    for c, _ in CHECKS[1:5]:
        for grp, side, name in (("total_games", "Over", "tot"), ("game_spread", "p1", "spr")):
            ln = main_line(pts, grp, side, f"{c}_price")
            j[f"{name}_{c}_line"] = j["fixture_id"].map(ln["line"])
            j[f"{name}_{c}_q"] = j["fixture_id"].map(ln["q"])
    return j.reset_index(drop=True)


# ------------------------------------------------------------------ features at a decision time
def features(j: pd.DataFrame, T: int) -> tuple[pd.DataFrame, list[str]]:
    tc = f"t{T}h"
    dec = j["start"] - pd.Timedelta(hours=T)
    d = j[j[f"pinnacle_{tc}_q"].notna()].copy()
    dec = dec[d.index]
    # leak guard: every quote used must be timed at or before the decision time
    usable = [c for c, h in CHECKS if c == "open" or (h is not None and h >= T)]
    for b in BOOKS:
        for c in usable:
            col = f"{b}_{c}_q"
            if col in d:
                late = d[f"{b}_{c}_utc"] > dec
                d.loc[late, col] = np.nan
    assert (d[f"pinnacle_{tc}_utc"] <= dec).all()
    d["m"] = logit(d[f"pinnacle_{tc}_q"])
    d["pin_T"] = d[f"pinnacle_{tc}_q"]
    F: dict[str, pd.Series] = {"m": d["m"]}
    for c in usable:
        if c == tc:
            continue
        F[f"pin_move_from_{c}"] = d["m"] - L(d[f"pinnacle_{c}_q"])
    for b in EXEC:
        for c in usable:
            q = d.get(f"{b}_{c}_q")
            if q is not None:
                F[f"{b}_{c}_minus_pinT"] = L(q) - d["m"]
    F["elo_gap"] = pd.Series(logit(d["elo_p1"]), index=d.index) - d["m"]
    F["pt_gap"] = L(d["pt_p1"]) - d["m"]
    F["pace_gap"] = L(d["ptpace_p1"]) - L(d["pt_p1"])
    F["serve_gap"] = d["serve_gap"]
    F["pace"] = d["pace"]
    F["pace_x_serve"] = d["pace"] * d["serve_gap"]
    for c in fat_cols():
        F[c] = d[c]
    F["tot_line"] = d[f"tot_{tc}_line"]
    F["tot_q"] = d[f"tot_{tc}_q"]
    F["spr_line_p1"] = d[f"spr_{tc}_line"]
    F["spr_q_p1"] = d[f"spr_{tc}_q"]
    F["m_x_tot"] = d["m"] * d[f"tot_{tc}_line"]
    F["spr_plus_m"] = d[f"spr_{tc}_line"] + 4.0 * d["m"]       # spread vs what the moneyline implies (rough)
    lvl = d["level"].astype(str)
    for name, vals in (("G", {"G"}), ("M", {"M", "1000"}), ("500", {"500"}), ("250", {"250", "A"}), ("C", {"C"}), ("D", {"D"})):
        F[f"lvl_{name}"] = lvl.isin(vals).astype(float)
    F["round_rank"] = d["rank"].astype(float)
    F["qualifying"] = (d["stage"] == 0).astype(float)
    F["best_of5"] = (d["best_of"] == 5).astype(float)
    F["log_n_min"] = np.log(d["n_min"].astype(float))
    F["hours_open"] = d["hours_open"].clip(upper=96)
    for f in ("ATP", "WTA", "CHALLENGER"):
        F[f"fam_{f}"] = (d["family"] == f).astype(float)
    X = pd.DataFrame(F)
    return d, X


def fat_cols():
    return [f"d_{c}" for c in FATIGUE] + [f"d_{c}_missing" for c in FATIGUE]


def lin_matrix(X: pd.DataFrame, tr_mask: np.ndarray):
    """Fill NaN with the training median plus a missing flag; standardize on training rows."""
    cols, parts = [], []
    for c in X.columns:
        v = X[c].to_numpy(float)
        if np.isnan(v).any():
            med = np.nanmedian(v[tr_mask]) if np.isfinite(v[tr_mask]).any() else 0.0
            flag = np.isnan(v).astype(float)
            parts.append(np.where(np.isnan(v), med, v)); cols.append(c)
            if flag[tr_mask].std() > 0:
                parts.append(flag); cols.append(c + "_nan")
        else:
            parts.append(v); cols.append(c)
    M = np.column_stack(parts)
    mu, sd = M[tr_mask].mean(0), M[tr_mask].std(0)
    keep = sd > 0
    M = (M[:, keep] - mu[keep]) / sd[keep]
    return np.c_[M, np.ones(len(M))], [c for c, k in zip(cols, keep) if k] + ["intercept"]


def fit_logistic(X, y, off, ridge):
    w = np.zeros(X.shape[1])
    R = ridge * np.eye(len(w)); R[-1, -1] = 1e-6
    for _ in range(100):
        p = sig(off + X @ w)
        g = X.T @ (p - y) + R @ w
        h = (X * (p * (1 - p))[:, None]).T @ X + R
        step = np.linalg.solve(h, g)
        w -= step
        if np.abs(step).max() < 1e-9:
            break
    return w


def models(d: pd.DataFrame, X: pd.DataFrame) -> dict:
    tr = (d["start"] < TEST_FROM).to_numpy()
    te = ~tr
    fit = tr & (d["start"] < VAL_FROM).to_numpy()
    val = tr & ~fit
    y = d["y"].to_numpy(float)
    off = d["m"].to_numpy()
    out, info = {}, {}
    # logistic
    M, names = lin_matrix(X, tr)
    best = None
    for r in (3, 10, 30, 100, 300, 1000, 3000):
        w = fit_logistic(M[fit], y[fit], off[fit], r)
        v = ll(sig(off[val] + M[val] @ w), y[val]).mean()
        best = min(best or (v, r), (v, r))
    w = fit_logistic(M[tr], y[tr], off[tr], best[1])
    out["logistic"] = sig(off + M @ w)
    top = np.argsort(-np.abs(w[:-1]))[:8]
    info["logistic"] = {"ridge": best[1], "val_loss": round(best[0], 5), "val_market_loss": round(float(ll(sig(off[val]), y[val]).mean()), 5),
                        "top_weights": {names[i]: round(float(w[i]), 4) for i in top}}
    # LightGBM on the residual
    Xn = X.to_numpy(float)
    best = None
    for depth in (2, 3):
        params = dict(objective="binary", learning_rate=0.05, max_depth=depth, num_leaves=2 ** depth, min_data_in_leaf=60,
                      lambda_l2=10.0, feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1, verbose=-1, seed=7)
        dtr = lgb.Dataset(Xn[fit], y[fit], init_score=off[fit], feature_name=list(X.columns))
        dva = lgb.Dataset(Xn[val], y[val], init_score=off[val], reference=dtr)
        bst = lgb.train(params, dtr, 2000, valid_sets=[dva], callbacks=[lgb.early_stopping(100, verbose=False)])
        v = ll(sig(off[val] + bst.predict(Xn[val], raw_score=True, num_iteration=bst.best_iteration)), y[val]).mean()
        if best is None or v < best[0]:
            best = (v, depth, max(bst.best_iteration, 1), params)
    v, depth, iters, params = best
    bst = lgb.train(params, lgb.Dataset(Xn[tr], y[tr], init_score=off[tr]), iters)
    out["lightgbm"] = sig(off + bst.predict(Xn, raw_score=True))
    imp = bst.feature_importance("gain")
    info["lightgbm"] = {"depth": depth, "rounds": iters, "val_loss": round(float(v), 5),
                        "top_gain": {X.columns[i]: round(float(imp[i]), 1) for i in np.argsort(-imp)[:8]}}
    out["avg"] = sig(0.5 * (logit(out["logistic"]) + logit(out["lightgbm"])))
    return out, info, te


def evaluate(d, preds, te, T) -> dict:
    t = d[te]
    y = t["y"].to_numpy(float)
    base = {"pin_T": ll(t["pin_T"].to_numpy(), y)}
    has_close = t["pinnacle_close_q"].notna().to_numpy()
    res = {"n_train": int((~te).sum()), "n_test": int(te.sum()), "n_test_with_close": int(has_close.sum()),
           "log_loss": {"pinnacle_T": round(float(base["pin_T"].mean()), 5),
                        "pinnacle_close": round(float(ll(t["pinnacle_close_q"].to_numpy()[has_close], y[has_close]).mean()), 5)}}
    close_l = ll(t["pinnacle_close_q"].to_numpy()[has_close], y[has_close])
    fam = t["family"].to_numpy()
    for k, p in preds.items():
        pl = ll(p[te], y)
        r = {"log_loss": round(float(pl.mean()), 5), "minus_pin_T": paired(pl, base["pin_T"]),
             "minus_pin_close": paired(pl[has_close], close_l), "by_family": {}}
        for f in ("ATP", "WTA", "CHALLENGER"):
            s = fam == f
            sc = s & has_close
            r["by_family"][f] = {"n": int(s.sum()), "minus_pin_T": paired(pl[s], base["pin_T"][s]),
                                 "minus_pin_close": paired(pl[sc], ll(t["pinnacle_close_q"].to_numpy()[sc], y[sc]))}
        res[k] = r
    res["pin_T_minus_close"] = paired(base["pin_T"][has_close], close_l)
    return res


def betting(d, preds, te, T) -> dict:
    t = d[te]
    tc = f"t{T}h"
    y = t["y"].to_numpy(float)
    fair_close = t["pinnacle_close_q"].to_numpy()
    out = {}
    probs = {"pinnacle_T_only": t["pin_T"].to_numpy(), **{k: v[te] for k, v in preds.items()}}
    for b in EXEC:
        a, c = t.get(f"{b}_{tc}_p1"), t.get(f"{b}_{tc}_p2")
        if a is None:
            continue
        a, c = a.to_numpy(float), c.to_numpy(float)
        utc = t[f"{b}_{tc}_utc"]
        ok = np.isfinite(a) & np.isfinite(c) & (utc <= t["start"] - pd.Timedelta(hours=T)).to_numpy()
        out[b] = {"n_priced": int(ok.sum()), "overround": round(float(np.nanmean((1 / a + 1 / c - 1)[ok])), 4) if ok.any() else None}
        for name, p in probs.items():
            ev1, ev2 = p * a - 1, (1 - p) * c - 1
            side1 = ev1 >= ev2
            ev = np.where(side1, ev1, ev2)
            price = np.where(side1, a, c)
            win = np.where(side1, y, 1 - y)
            fc = np.where(side1, fair_close, 1 - fair_close)
            r = {}
            for thr in (0.0, 0.02, 0.04):
                s = ok & (ev > thr)
                sc = s & np.isfinite(fc)
                r[f"ev_gt_{thr}"] = {"return_per_$": boot(price[s] * win[s] - 1), "clv_vs_pin_close": boot(price[sc] * fc[sc] - 1)}
            out[b][name] = r
    return out


def late_info(j) -> dict:
    """Pinnacle and execution books' log loss at each checkpoint on test fixtures that have all of them."""
    t = j[(j["start"] >= TEST_FROM)]
    out = {}
    for b in BOOKS:
        cols = [f"{b}_{c}_q" for c, _ in CHECKS if f"{b}_{c}_q" in t and c != "t24h"]
        s = t.dropna(subset=cols + ["pinnacle_close_q"])
        if len(s) < 100:
            continue
        y = s["y"].to_numpy(float)
        out[b] = {"n": int(len(s)), **{c.split("_")[1]: round(float(ll(s[c].to_numpy(), y).mean()), 5) for c in cols},
                  "pin_close": round(float(ll(s["pinnacle_close_q"].to_numpy(), y).mean()), 5)}
    return out


def main():
    cache = HERE / "joined.pkl"
    j = pd.read_pickle(cache) if cache.exists() else build()
    j.to_pickle(cache)
    report = {"n_fixtures": int(len(j)), "late_information_test": late_info(j), "decisions": {}}
    for T in (12, 6, 1):
        d, X = features(j, T)
        d, X = d.reset_index(drop=True), X.reset_index(drop=True)
        preds, info, te = models(d, X)
        report["decisions"][f"t{T}h"] = {"features": list(X.columns), "fit": info, "eval": evaluate(d, preds, te, T),
                                         "betting": betting(d, preds, te, T)}
        e = report["decisions"][f"t{T}h"]["eval"]
        print(f"t{T}h", json.dumps({k: (v["log_loss"], v["minus_pin_T"], v["minus_pin_close"]) for k, v in e.items() if isinstance(v, dict) and "minus_pin_T" in v}), e["log_loss"], flush=True)
    (HERE / "results.json").write_text(json.dumps(report, indent=1, default=str) + "\n")


if __name__ == "__main__":
    main()
