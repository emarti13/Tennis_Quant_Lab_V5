"""Point DNA: does shot-by-shot style (Match Charting Project) add information beyond the market?

Usage:  python research_tests/point_dna/run_point_dna.py MCP_DIR JOINED_PKL OUT_JSON

MCP_DIR      clone of github.com/JeffSackmann/tennis_MatchChartingProject (CC BY-NC-SA 4.0:
             research use only, attribution: The Tennis Abstract Match Charting Project; the
             data is not copied into this repo).
JOINED_PKL   the Kaggle odds join (research_tests/kaggle_join/join_odds.py): ATP/WTA/Challenger
             2014-2025, bet365/Betfair/Ladbrokes/Unibet open and close; player_a = winner.

Pre-registered before any result was seen (2026-10-31):
  PRIMARY   test years 2021-2025 pooled, ATP main + WTA main, both players with >= 5 charted
            matches in the 3 years before the event. Market = Betfair closing, de-vigged.
            Compare M0 = logistic on logit(market) against M1 = M0 + point-DNA features
            (L2 logistic, standardised). Walk-forward: each test year trained on all earlier
            years from 2015. Metric: log loss M1 - M0, 95% range by match bootstrap.
            The DNA "adds information" only if the range is wholly below zero.
  SECONDARY LightGBM version of M1; the same against bet365's OPEN (a softer price); a
            betting check at Betfair close (2% commission) and bet365 open, edge >= 3/5/8 pts;
            DNA-only vs basic serve/return-only models without the market (does DNA predict
            at all, beyond plain serve/return rates?).
  LEAKS     A profile uses charted matches dated strictly before the event's tournament start
            (no same-tournament matches). Shrinkage means come from charted matches before 2014.
"""
from __future__ import annotations

import json
import re
import sys
import unicodedata

import numpy as np
import pandas as pd

HALF_LIFE_DAYS = 365
WINDOW_DAYS = 3 * 365
MIN_MATCHES = 5
PRIOR_PTS = 200          # shrinkage strength, in points (rally/net rates use the same)
TEST_YEARS = range(2018, 2026)
PRIMARY_YEARS = range(2021, 2026)
rng = np.random.default_rng(20261031)


def norm(s) -> str:
    return re.sub(r"[^a-z]", "", unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower())


# ---------------------------------------------------------------- per player-match counts
def read(mcp: str, tour: str, name: str) -> pd.DataFrame:
    return pd.read_csv(f"{mcp}/charting-{tour}-{name}.csv", encoding="latin-1", on_bad_lines="skip", low_memory=False)


def counts(mcp: str, tour: str) -> pd.DataFrame:
    """One row per (match_id, player): additive counts, so a profile is a weighted sum."""
    key = ["match_id", "player"]
    ov = read(mcp, tour, "stats-Overview")
    ov = ov[ov["set"].astype(str) == "Total"][key + ["serve_pts", "aces", "dfs", "first_in", "first_won", "second_in",
                                                    "second_won", "return_pts", "return_pts_won", "winners",
                                                    "winners_fh", "winners_bh", "unforced", "unforced_fh", "unforced_bh"]]
    sb = read(mcp, tour, "stats-ServeBasics")
    sb = sb[sb["row"].astype(str) == "Total"][key + ["unret", "pts_won_lte_3_shots"]]
    sd = read(mcp, tour, "stats-ServeDirection")
    sd = sd[sd["row"].astype(str) == "1"][key + ["deuce_wide", "deuce_middle", "deuce_t", "ad_wide", "ad_middle", "ad_t"]]
    ro = read(mcp, tour, "stats-ReturnOutcomes")
    ro["row"] = ro["row"].astype(str)
    parts = []
    for row, tag in (("v1st", "r1"), ("v2nd", "r2"), ("4", "rw"), ("6", "rt")):
        x = ro[ro["row"] == row][key + ["pts", "pts_won", "in_play"]]
        parts.append(x.rename(columns={"pts": f"{tag}_pts", "pts_won": f"{tag}_won", "in_play": f"{tag}_inplay"}))
    net = read(mcp, tour, "stats-NetPoints")
    net = net[net["row"].astype(str) == "NetPoints"][key + ["net_pts", "pts_won"]].rename(columns={"pts_won": "net_won"})
    kp = read(mcp, tour, "stats-KeyPointsServe")
    kp["row"] = kp["row"].astype(str)
    bp = kp[kp["row"] == "BP"][key + ["pts", "pts_won"]].rename(columns={"pts": "bp_pts", "pts_won": "bp_won"})
    ra = read(mcp, tour, "stats-Rally")
    ra["row"] = ra["row"].astype(str)
    rally = []
    for row, tag in (("1-3", "s"), ("4-6", "m"), ("7-9", "l"), ("10", "x")):
        x = ra[ra["row"] == row]
        for who, won in (("server", "pl1_won"), ("returner", "pl2_won")):
            rally.append(pd.DataFrame({"match_id": x["match_id"], "player": x[who], "bin": tag,
                                       "pts": x["pts"], "won": x[won]}))
    rally = pd.concat(rally).pivot_table(index=key, columns="bin", values=["pts", "won"], aggfunc="sum")
    rally.columns = [f"rl{b}_{v}" for v, b in rally.columns]
    out = ov
    for p in [sb, sd, *parts, net, bp]:
        out = out.merge(p, on=key, how="left")
    out = out.merge(rally.reset_index(), on=key, how="left")
    num = out.columns.drop(key)
    out[num] = out[num].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    m = read(mcp, tour, "matches")[["match_id", "Date", "Player 1", "Player 2", "Pl 1 hand", "Pl 2 hand"]]
    out = out.merge(m[["match_id", "Date"]], on="match_id")
    out["date"] = pd.to_datetime(out["Date"].astype(str).str[:8], format="%Y%m%d", errors="coerce")
    out = out[out["date"].notna() & (out["serve_pts"] > 0)]
    out["pkey"] = out["player"].map(norm)
    hands = pd.concat([m[["Player 1", "Pl 1 hand"]].set_axis(["p", "h"], axis=1),
                       m[["Player 2", "Pl 2 hand"]].set_axis(["p", "h"], axis=1)])
    hands["pkey"] = hands["p"].map(norm)
    out.attrs["lefty"] = set(hands.loc[hands["h"].astype(str).str.upper() == "L", "pkey"])
    return out.drop(columns=["Date"])


def rates(c: dict, mu: dict | None) -> dict:
    """Shrunk rates from summed counts. mu: the prior means (None = raw, used to compute mu)."""
    def r(num, den, name):
        prior = 0.0 if mu is None else PRIOR_PTS
        m = 0.0 if mu is None else mu[name]
        d = c[den] + prior
        return (c[num] + prior * m) / d if d > 0 else np.nan
    tot = c["serve_pts"] + c["return_pts"]
    c = {**c, "tot": tot, "sv_won": c["first_won"] + c["second_won"],
         "dir_wide": c["deuce_wide"] + c["ad_wide"], "dir_t": c["deuce_t"] + c["ad_t"],
         "dir_all": c["deuce_wide"] + c["ad_wide"] + c["deuce_t"] + c["ad_t"] + c["deuce_middle"] + c["ad_middle"],
         "rl_long_pts": c.get("rll_pts", 0) + c.get("rlx_pts", 0), "rl_long_won": c.get("rll_won", 0) + c.get("rlx_won", 0),
         "rl_all": sum(c.get(f"rl{b}_pts", 0) for b in "smlx")}
    f = {
        "ace": r("aces", "serve_pts", "ace"), "df": r("dfs", "serve_pts", "df"),
        "first_in": r("first_in", "serve_pts", "first_in"), "first_won": r("first_won", "first_in", "first_won"),
        "second_won": r("second_won", "second_in", "second_won"), "sv_won": r("sv_won", "serve_pts", "sv_won"),
        "unret": r("unret", "serve_pts", "unret"), "short_sv": r("pts_won_lte_3_shots", "serve_pts", "short_sv"),
        "ret_won": r("return_pts_won", "return_pts", "ret_won"), "ret_v1": r("r1_won", "r1_pts", "ret_v1"),
        "ret_v2": r("r2_won", "r2_pts", "ret_v2"), "ret_inplay": r("r1_inplay", "r1_pts", "ret_inplay"),
        "ret_wide": r("rw_won", "rw_pts", "ret_wide"), "ret_t": r("rt_won", "rt_pts", "ret_t"),
        "wide_share": r("dir_wide", "dir_all", "wide_share"), "t_share": r("dir_t", "dir_all", "t_share"),
        "win_short": r("rls_won", "rls_pts", "win_short"), "win_mid": r("rlm_won", "rlm_pts", "win_mid"),
        "win_long": r("rl_long_won", "rl_long_pts", "win_long"), "long_share": r("rl_long_pts", "rl_all", "long_share"),
        "net_freq": r("net_pts", "tot", "net_freq"), "net_won": r("net_won", "net_pts", "net_won"),
        "winners": r("winners", "tot", "winners"), "ue": r("unforced", "tot", "ue"),
        "fh_w": r("winners_fh", "tot", "fh_w"), "fh_ue": r("unforced_fh", "tot", "fh_ue"),
        "bh_w": r("winners_bh", "tot", "bh_w"), "bh_ue": r("unforced_bh", "tot", "bh_ue"),
        "bp_won": r("bp_won", "bp_pts", "bp_won"),
    }
    if c["dir_all"] > 0 and mu is not None:
        p = np.array([c[k] for k in ("deuce_wide", "deuce_middle", "deuce_t", "ad_wide", "ad_middle", "ad_t")], float)
        p = (p + 1) / (p.sum() + 6)
        f["dir_entropy"] = float(-(p * np.log(p)).sum())
    else:
        f["dir_entropy"] = np.nan
    f["clutch"] = f["bp_won"] - f["sv_won"]
    return f


def profiles(cnt: pd.DataFrame, targets: pd.DataFrame, mu: dict) -> pd.DataFrame:
    """targets: columns pkey, cut (tournament start). Weighted counts of charted matches in
    [cut - window, cut), half-life weighting; then shrunk rates."""
    cols = [c for c in cnt.columns if c not in ("match_id", "player", "date", "pkey")]
    by = {k: (g["date"].values.astype("datetime64[D]"), g[cols].to_numpy(float)) for k, g in cnt.groupby("pkey")}
    rows = []
    for (pk, cut), g in targets.groupby(["pkey", "cut"]):
        if pk not in by:
            continue
        d, X = by[pk]
        age = (np.datetime64(cut, "D") - d).astype(int)
        ok = (age > 0) & (age <= WINDOW_DAYS)
        if ok.sum() < MIN_MATCHES:
            continue
        w = 0.5 ** (age[ok] / HALF_LIFE_DAYS)
        c = dict(zip(cols, (w[:, None] * X[ok]).sum(0)))
        f = rates(c, mu)
        f.update(pkey=pk, cut=cut, n_charted=int(ok.sum()))
        rows.append(f)
    return pd.DataFrame(rows)


def prior_means(cnt: pd.DataFrame) -> dict:
    early = cnt[cnt["date"] < "2014-01-01"]
    cols = [c for c in cnt.columns if c not in ("match_id", "player", "date", "pkey")]
    f = rates(dict(early[cols].sum()), None)
    return {k: (0.0 if (v is None or not np.isfinite(v)) else float(v)) for k, v in f.items()}


# ---------------------------------------------------------------- matches with market prices
def devig(a, b):
    ia, ib = 1 / a, 1 / b
    return ia / (ia + ib)


def build(joined: pd.DataFrame, tour: str, cnt: pd.DataFrame, lefty: set) -> pd.DataFrame:
    j = joined[joined["tour"] == tour].copy()
    j["cut"] = pd.to_datetime(j["wh_date"]).dt.normalize()
    j["year"] = j["cut"].dt.year
    j["wk"], j["lk"] = j["winner_name"].map(norm), j["loser_name"].map(norm)
    mu = prior_means(cnt)
    targets = pd.concat([j[["wk", "cut"]].set_axis(["pkey", "cut"], axis=1), j[["lk", "cut"]].set_axis(["pkey", "cut"], axis=1)]).drop_duplicates()
    prof = profiles(cnt, targets, mu)
    feats = [c for c in prof.columns if c not in ("pkey", "cut")]
    j = j.merge(prof.add_prefix("w_").rename(columns={"w_pkey": "wk", "w_cut": "cut"}), on=["wk", "cut"])
    j = j.merge(prof.add_prefix("l_").rename(columns={"l_pkey": "lk", "l_cut": "cut"}), on=["lk", "cut"])
    flip = rng.random(len(j)) < 0.5                     # A = winner unless flipped
    out = pd.DataFrame({"year": j["year"].values, "level": j["odds_level"].values, "y": (~flip).astype(int)})
    for f in feats:
        a = np.where(flip, j[f"l_{f}"], j[f"w_{f}"])
        b = np.where(flip, j[f"w_{f}"], j[f"l_{f}"])
        out[f"a_{f}"], out[f"b_{f}"] = a, b
    for book, (cw, cl) in {"bf_close": ("bf_w", "bf_l"), "b365_open": ("b365_w_opening", "b365_l_opening"),
                           "b365_close": ("b365_w", "b365_l")}.items():
        ow, ol = pd.to_numeric(j[cw], errors="coerce").values, pd.to_numeric(j[cl], errors="coerce").values
        good = (ow > 1) & (ol > 1)
        oa, ob = np.where(flip, ol, ow), np.where(flip, ow, ol)
        # computed from A's and B's odds the same way for every row: writing the flipped side
        # as 1 - p leaves float-rounding traces that a tree model reads as the result (found
        # 2026-10-31: LightGBM on the market price alone "beat" the market by 0.06 log loss)
        out[f"p_{book}"] = np.where(good, devig(oa, ob), np.nan)
        out[f"oddsA_{book}"], out[f"oddsB_{book}"] = oa, ob
    al, bl = np.where(flip, j["lk"], j["wk"]), np.where(flip, j["wk"], j["lk"])
    out["a_lefty"] = pd.Series(al).isin(lefty).astype(int).values
    out["b_lefty"] = pd.Series(bl).isin(lefty).astype(int).values
    out["tour"] = tour
    return out


def matchup(df: pd.DataFrame) -> pd.DataFrame:
    """A-minus-B differences plus style interactions."""
    X = pd.DataFrame(index=df.index)
    base = ["ace", "df", "first_in", "first_won", "second_won", "sv_won", "unret", "short_sv", "ret_won", "ret_v1",
            "ret_v2", "ret_inplay", "ret_wide", "ret_t", "wide_share", "t_share", "win_short", "win_mid", "win_long",
            "long_share", "net_freq", "net_won", "winners", "ue", "fh_w", "fh_ue", "bh_w", "bh_ue", "bp_won",
            "dir_entropy", "clutch"]
    for f in base:
        X[f"d_{f}"] = df[f"a_{f}"] - df[f"b_{f}"]
    # serve aimed at the opponent's weaker return side (wide vs T), each way
    tgt = lambda s, r: df[f"{s}_wide_share"] * (df[f"{r}_ret_t"] - df[f"{r}_ret_wide"]) + df[f"{s}_t_share"] * (df[f"{r}_ret_wide"] - df[f"{r}_ret_t"])  # noqa: E731
    X["x_target"] = tgt("a", "b") - tgt("b", "a")
    # rally-length matchup: expected share of long rallies x each player's long-rally edge
    ls = (df["a_long_share"] + df["b_long_share"]) / 2
    X["x_rally"] = ls * (df["a_win_long"] - df["b_win_long"]) + (1 - ls) * (df["a_win_short"] - df["b_win_short"])
    # serve power against return reliability
    X["x_serve_vs_return"] = (df["a_unret"] - (1 - df["b_ret_inplay"])) - (df["b_unret"] - (1 - df["a_ret_inplay"]))
    # net rushers against passers (opponent's points won at net is a proxy for being passed)
    X["x_net"] = df["a_net_freq"] * (df["a_net_won"] - (1 - df["b_net_won"])) - df["b_net_freq"] * (df["b_net_won"] - (1 - df["a_net_won"]))
    X["x_lefty"] = df["a_lefty"] - df["b_lefty"]
    X["x_lefty_vs_wide_ret"] = df["a_lefty"] * (df["b_ret_wide"] - df["b_ret_t"]) - df["b_lefty"] * (df["a_ret_wide"] - df["a_ret_t"])
    X["log_n"] = np.log(df["a_n_charted"]) - np.log(df["b_n_charted"])
    return X


BASIC = ["d_sv_won", "d_ret_won"]


# ---------------------------------------------------------------- models
def logit(p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def ll(y, p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def fit_logistic(X, y, C=1.0):
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    m = make_pipeline(StandardScaler(), LogisticRegression(C=C, max_iter=2000))
    return m.fit(X, y)


def fit_lgbm(X, y):
    import lightgbm as lgb
    return lgb.LGBMClassifier(n_estimators=300, learning_rate=0.02, num_leaves=15, min_child_samples=100,
                              subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=5.0, verbose=-1).fit(X, y)


def walk_forward(df: pd.DataFrame, X: pd.DataFrame, market: str | None, cols: list[str], kind: str) -> np.ndarray:
    """Out-of-sample predictions for TEST_YEARS rows; NaN elsewhere."""
    pred = np.full(len(df), np.nan)
    feats = X[cols].copy() if cols else pd.DataFrame(index=X.index)
    if market:
        feats["mkt"] = logit(df[f"p_{market}"].values)
    feats = feats.fillna(0.0)
    for yr in TEST_YEARS:
        tr = (df["year"] < yr) & (df["year"] >= 2015)
        te = df["year"] == yr
        if tr.sum() < 500 or te.sum() == 0:
            continue
        model = fit_logistic(feats[tr], df.loc[tr, "y"], C=0.1) if kind == "logit" else fit_lgbm(feats[tr], df.loc[tr, "y"])
        pred[te.values] = model.predict_proba(feats[te])[:, 1]
    return pred


def boot(diff: np.ndarray, n=2000) -> tuple[float, float, float]:
    idx = rng.integers(0, len(diff), (n, len(diff)))
    m = diff[idx].mean(1)
    return float(diff.mean()), float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def bets(df, p_model, book, thr, commission):
    """Back the side whose model probability beats the book's price by thr (in probability)."""
    oa, ob = df[f"oddsA_{book}"].values, df[f"oddsB_{book}"].values
    ea, eb = p_model - 1 / oa, (1 - p_model) - 1 / ob
    side_a = (ea >= thr) & (ea >= eb)
    side_b = (eb >= thr) & (eb > ea)
    win = np.where(side_a, df["y"].values == 1, df["y"].values == 0)
    odds = np.where(side_a, oa, ob)
    pnl = np.where(win, (odds - 1) * (1 - commission), -1.0)[side_a | side_b]
    if len(pnl) == 0:
        return {"n": 0}
    lo, hi = np.percentile([pnl[rng.integers(0, len(pnl), len(pnl))].mean() for _ in range(2000)], [2.5, 97.5])
    return {"n": int(len(pnl)), "roi": round(float(pnl.mean()), 4), "ci": [round(float(lo), 4), round(float(hi), 4)]}


def main() -> int:
    mcp, joined_pkl, out_json = sys.argv[1:4]
    joined = pd.read_pickle(joined_pkl)
    parts = []
    for tour, t in (("ATP", "m"), ("WTA", "w")):
        cnt = counts(mcp, t)
        parts.append(build(joined, tour, cnt, cnt.attrs["lefty"]))
    df = pd.concat(parts, ignore_index=True)
    df = df[df["p_bf_close"].notna()].reset_index(drop=True)
    X = matchup(df)
    dna = list(X.columns)
    res = {"rows_by_year_level": df.groupby(["year", "level"]).size().unstack(fill_value=0).to_dict(), "results": {}}
    test = df["year"].isin(TEST_YEARS).values
    prim = df["year"].isin(PRIMARY_YEARS).values & df["level"].isin(["ATP main", "WTA main"]).values

    preds = {}
    for market in ("bf_close", "b365_open"):
        ok = df[f"p_{market}"].notna().values
        preds[f"M0_{market}"] = walk_forward(df[ok].reset_index(drop=True), X[ok].reset_index(drop=True), market, [], "logit")
        preds[f"M1_{market}"] = walk_forward(df[ok].reset_index(drop=True), X[ok].reset_index(drop=True), market, dna, "logit")
        preds[f"M1gb_{market}"] = walk_forward(df[ok].reset_index(drop=True), X[ok].reset_index(drop=True), market, dna, "lgbm")
        for k in ("M0", "M1", "M1gb"):
            full = np.full(len(df), np.nan)
            full[ok] = preds[f"{k}_{market}"]
            preds[f"{k}_{market}"] = full
    preds["dna_only"] = walk_forward(df, X, None, dna, "logit")
    preds["basic_only"] = walk_forward(df, X, None, BASIC, "logit")

    y = df["y"].values
    for market in ("bf_close", "b365_open"):
        for name, mask in (("PRIMARY 2021-25 main tours", prim), ("all test years 2018-25, all levels", test)):
            m = mask & np.isfinite(preds[f"M0_{market}"])
            r = {"n": int(m.sum()), "ll_market_raw": round(float(ll(y[m], df[f"p_{market}"].values[m]).mean()), 5),
                 "ll_M0": round(float(ll(y[m], preds[f"M0_{market}"][m]).mean()), 5)}
            for k in ("M1", "M1gb"):
                d = ll(y[m], preds[f"{k}_{market}"][m]) - ll(y[m], preds[f"M0_{market}"][m])
                mean, lo, hi = boot(d)
                r[f"{k}_minus_M0"] = [round(mean, 5), round(lo, 5), round(hi, 5)]
            by_year = {}
            for yr in sorted(set(df.loc[m, "year"])):
                mm = m & (df["year"].values == yr)
                by_year[int(yr)] = [int(mm.sum()), round(float((ll(y[mm], preds[f"M1_{market}"][mm]) - ll(y[mm], preds[f"M0_{market}"][mm])).mean()), 5)]
            r["M1_minus_M0_by_year"] = by_year
            res["results"][f"{market} | {name}"] = r
    m = test & np.isfinite(preds["dna_only"])
    res["results"]["no market: DNA vs basic serve/return (all test rows)"] = {
        "n": int(m.sum()), "ll_basic": round(float(ll(y[m], preds["basic_only"][m]).mean()), 5),
        "ll_dna": round(float(ll(y[m], preds["dna_only"][m]).mean()), 5),
        "dna_minus_basic": [round(v, 5) for v in boot(ll(y[m], preds["dna_only"][m]) - ll(y[m], preds["basic_only"][m]))],
        "ll_bf_close": round(float(ll(y[m], df["p_bf_close"].values[m]).mean()), 5)}
    betting = {}
    for market, comm in (("bf_close", 0.02), ("b365_open", 0.0)):
        for k in ("M1", "M1gb"):
            for thr in (0.03, 0.05, 0.08):
                m = test & np.isfinite(preds[f"{k}_{market}"])
                sub = df[m].reset_index(drop=True)
                betting[f"{market} {k} edge>={thr}"] = bets(sub, preds[f"{k}_{market}"][m], market, thr, comm)
    res["betting_test_2018_25"] = betting
    # what the logistic M1 leans on (fit on everything before 2026, standardised coefficients)
    ok = df["p_bf_close"].notna()
    fe = X[dna].fillna(0.0).copy()
    fe["mkt"] = logit(df["p_bf_close"].values)
    mdl = fit_logistic(fe[ok], df.loc[ok, "y"], C=0.1)
    coef = dict(zip(fe.columns, mdl[-1].coef_[0]))
    res["coef_M1_bf_close"] = {k: round(float(v), 4) for k, v in sorted(coef.items(), key=lambda kv: -abs(kv[1]))}
    with open(out_json, "w") as f:
        json.dump(res, f, indent=1, default=str)
    print(json.dumps(res["results"], indent=1))
    print(json.dumps(betting, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
