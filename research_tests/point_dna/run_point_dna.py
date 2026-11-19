"""Point DNA: does shot-by-shot style (Match Charting Project) add information beyond the market?

Usage:  python research_tests/point_dna/run_point_dna.py MCP_DIR JOINED_PKL OUT_JSON [v1|v2]

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

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))
from research_kit import checks, provenance  # noqa: E402
from research_kit.core import back_bets, boot_mean, coin_flip, devig, log_loss as ll, logit, orient  # noqa: E402
from research_kit.core import walk_forward as kit_walk_forward  # noqa: E402

HALF_LIFE_DAYS = 365
WINDOW_DAYS = 3 * 365
MIN_MATCHES = 5
PRIOR_PTS = 200          # shrinkage strength, in points (rally/net rates use the same)
TEST_YEARS = range(2018, 2026)
PRIMARY_YEARS = range(2021, 2026)
SEED = 20261031


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
    sb = sb[sb["row"].astype(str) == "Total"][key + ["unret", "forced_err", "pts_won_lte_3_shots"]]
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
    c = {**c, "tot": tot, "sv_unreturned": c["aces"] + c["unret"] + c.get("forced_err", 0), "sv_won": c["first_won"] + c["second_won"],
         "dir_wide": c["deuce_wide"] + c["ad_wide"], "dir_t": c["deuce_t"] + c["ad_t"],
         "dir_all": c["deuce_wide"] + c["ad_wide"] + c["deuce_t"] + c["ad_t"] + c["deuce_middle"] + c["ad_middle"],
         "rl_long_pts": c.get("rll_pts", 0) + c.get("rlx_pts", 0), "rl_long_won": c.get("rll_won", 0) + c.get("rlx_won", 0),
         "rl_all": sum(c.get(f"rl{b}_pts", 0) for b in "smlx")}
    f = {
        "ace": r("aces", "serve_pts", "ace"), "df": r("dfs", "serve_pts", "df"),
        "first_in": r("first_in", "serve_pts", "first_in"), "first_won": r("first_won", "first_in", "first_won"),
        "second_won": r("second_won", "second_in", "second_won"), "sv_won": r("sv_won", "serve_pts", "sv_won"),
        "unret": r("unret", "serve_pts", "unret"), "short_sv": r("pts_won_lte_3_shots", "serve_pts", "short_sv"),
        "unreturned": r("sv_unreturned", "serve_pts", "unreturned"),
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
BOOKS = {"bf_close": ("bf_w", "bf_l"), "b365_open": ("b365_w_opening", "b365_l_opening"), "b365_close": ("b365_w", "b365_l")}


def swap_source(joined: pd.DataFrame) -> pd.DataFrame:
    """The same matches as if the source had listed the loser first (for the swap check)."""
    j = joined.copy()
    pairs = [("winner_name", "loser_name")] + list(BOOKS.values())
    for a, b in pairs:
        j[a], j[b] = joined[b].values, joined[a].values
    return j


def build(joined: pd.DataFrame, tour: str, cnt: pd.DataFrame, lefty: set) -> pd.DataFrame:
    """One row per match with both players profiled, oriented by joined["flip"] (True: the
    source's second player is A). Every A/B value is taken from the flipped columns."""
    j = joined[joined["tour"] == tour].copy()
    j["cut"] = pd.to_datetime(j["wh_date"]).dt.normalize()
    j["year"] = j["cut"].dt.year
    j["k1"], j["k2"] = j["winner_name"].map(norm), j["loser_name"].map(norm)
    mu = prior_means(cnt)
    targets = pd.concat([j[["k1", "cut"]].set_axis(["pkey", "cut"], axis=1), j[["k2", "cut"]].set_axis(["pkey", "cut"], axis=1)]).drop_duplicates()
    prof = profiles(cnt, targets, mu)
    feats = [c for c in prof.columns if c not in ("pkey", "cut")]
    j = j.merge(prof.add_prefix("s1_").rename(columns={"s1_pkey": "k1", "s1_cut": "cut"}), on=["k1", "cut"])
    j = j.merge(prof.add_prefix("s2_").rename(columns={"s2_pkey": "k2", "s2_cut": "cut"}), on=["k2", "cut"])
    j = j.sort_values("match_key", kind="stable")
    flip = j["flip"].to_numpy(bool)
    out = pd.DataFrame({"match_key": j["match_key"].values, "year": j["year"].values,
                        "level": j["odds_level"].values, "y": (~flip).astype(int)})
    for f in feats:
        out[f"a_{f}"], out[f"b_{f}"] = orient(j[f"s1_{f}"], j[f"s2_{f}"], flip)
    for book, (c1, c2) in BOOKS.items():
        oa, ob = orient(pd.to_numeric(j[c1], errors="coerce"), pd.to_numeric(j[c2], errors="coerce"), flip)
        out[f"p_{book}"] = devig(oa, ob)
        out[f"oddsA_{book}"], out[f"oddsB_{book}"] = oa, ob
    ka, kb = orient(j["k1"], j["k2"], flip)
    out["a_lefty"] = pd.Series(ka).isin(lefty).astype(int).values
    out["b_lefty"] = pd.Series(kb).isin(lefty).astype(int).values
    out["tour"] = tour
    return out


def matchup(df: pd.DataFrame) -> pd.DataFrame:
    """A-minus-B differences plus style interactions."""
    X = pd.DataFrame(index=df.index)
    base = ["ace", "df", "first_in", "first_won", "second_won", "sv_won", "unret", "short_sv", "ret_won", "ret_v1",
            "ret_v2", "ret_inplay", "ret_wide", "ret_t", "wide_share", "t_share", "win_short", "win_mid", "win_long",
            "long_share", "net_freq", "net_won", "winners", "ue", "fh_w", "fh_ue", "bh_w", "bh_ue", "bp_won",
            "dir_entropy", "clutch", "unreturned"]
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
    # v2: the same with the full unreturned-serve rate (aces + untouched + forced return errors)
    X["x_serve_vs_return2"] = (df["a_unreturned"] - (1 - df["b_ret_inplay"])) - (df["b_unreturned"] - (1 - df["a_ret_inplay"]))
    # net rushers against passers (opponent's points won at net is a proxy for being passed)
    X["x_net"] = df["a_net_freq"] * (df["a_net_won"] - (1 - df["b_net_won"])) - df["b_net_freq"] * (df["b_net_won"] - (1 - df["a_net_won"]))
    X["x_lefty"] = df["a_lefty"] - df["b_lefty"]
    X["x_lefty_vs_wide_ret"] = df["a_lefty"] * (df["b_ret_wide"] - df["b_ret_t"]) - df["b_lefty"] * (df["a_ret_wide"] - df["a_ret_t"])
    X["log_n"] = np.log(df["a_n_charted"]) - np.log(df["b_n_charted"])
    return X


BASIC = ["d_sv_won", "d_ret_won"]
# v2, pre-registered 2026-10-31 after the v1 checks showed the 39-feature model costs about
# 0.0017 log loss even when the features carry nothing (market-null check): 8 features chosen
# before seeing any v2 result.
COMPACT = ["d_sv_won", "d_ret_won", "d_unreturned", "d_win_short", "d_win_long", "x_target", "x_rally", "x_serve_vs_return2"]


# ---------------------------------------------------------------- models


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


def walk_forward(df: pd.DataFrame, X: pd.DataFrame, market: str | None, cols: list[str], kind: str,
                 y: np.ndarray | None = None, extra: np.ndarray | None = None) -> np.ndarray:
    """Out-of-sample predictions for TEST_YEARS rows (trained on 2015..year-1); NaN elsewhere.
    y / extra: replacement outcomes and an extra feature column (used by the checks)."""
    feats = X[cols].copy() if cols else pd.DataFrame(index=X.index)
    if market:
        feats["mkt"] = logit(df[f"p_{market}"].values)
    if extra is not None:
        feats["extra"] = extra
    feats = feats.fillna(0.0)
    yy = df["y"].to_numpy() if y is None else y

    def fit_predict(tr, te):
        model = fit_logistic(feats[tr], yy[tr], C=0.1) if kind == "logit" else fit_lgbm(feats[tr], yy[tr])
        return model.predict_proba(feats[te])[:, 1]
    return kit_walk_forward(df["year"].to_numpy(), TEST_YEARS, fit_predict, first_train_year=2015)


def load(mcp: str, joined: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    parts, cnts = [], {}
    for tour, t in (("ATP", "m"), ("WTA", "w")):
        cnt = counts(mcp, t)
        cnts[tour] = cnt
        parts.append(build(joined, tour, cnt, cnt.attrs["lefty"]))
    return pd.concat(parts, ignore_index=True), cnts


def run_checks(df: pd.DataFrame, X: pd.DataFrame, dna: list[str], prim: np.ndarray, joined: pd.DataFrame, cnts: dict) -> dict:
    out = {}
    # 1. swap: the model's inputs must not depend on which side the source listed first
    tour = "WTA"                                               # the smaller tour keeps this quick
    cnt = cnts[tour]
    sub = joined[joined["tour"] == tour]
    build_fn = lambda raw, flip: (lambda b: pd.concat([b, matchup(b)], axis=1))(build(raw.assign(flip=flip), tour, cnt, cnt.attrs["lefty"]))  # noqa: E731
    cols = [c for c in ("p_bf_close", "p_b365_open", "oddsA_bf_close", "oddsB_bf_close", *dna)]
    out["swap_source"] = checks.swap_source(build_fn, sub, swap_source, sub["flip"].to_numpy(bool), cols)
    # 2. time travel: a profile must equal one built from charted matches before the cut only
    mu = prior_means(cnt)
    tg = pd.DataFrame({"pkey": pd.concat([sub["winner_name"], sub["loser_name"]]).map(norm).values,
                       "cut": pd.to_datetime(pd.concat([sub["wh_date"], sub["wh_date"]])).dt.normalize().values})
    tg = tg[tg["pkey"].isin(set(cnt["pkey"]))].drop_duplicates().reset_index(drop=True)
    feat_cols = ["ace", "sv_won", "ret_won", "win_long", "net_freq", "dir_entropy", "n_charted"]

    def features_at(h, t):
        p = profiles(h, t, mu)
        if p.empty:                                            # nobody profiled from this history
            return pd.DataFrame(np.nan, index=t.index, columns=feat_cols)
        return t.merge(p, on=["pkey", "cut"], how="left")[feat_cols]
    out["time_travel"] = checks.time_travel(features_at, cnt, tg, "date", "cut", feat_cols, n=200)
    # 3-4. planted edge and market null on the primary comparison
    p_mkt = df["p_bf_close"].to_numpy()

    def run(y, z):
        p0 = walk_forward(df, X, "bf_close", [], "logit", y=y)
        p1 = walk_forward(df, X, "bf_close", dna, "logit", y=y, extra=z)
        m = prim & np.isfinite(p1)
        return {"delta": boot_mean(ll(y[m], p1[m]) - ll(y[m], p0[m]), seed=SEED)}
    out["planted_edge"] = checks.planted_edge(run, p_mkt, size=0.25, seed=SEED)
    out["market_null"] = checks.market_null(run, p_mkt, seed=SEED + 1)
    # 5. shuffled outcomes: the DNA-only model must be no better than a coin
    out["shuffled_null"] = checks.shuffled_null(lambda ys: walk_forward(df, X, None, dna, "logit", y=ys),
                                                df["y"].to_numpy(), df["year"].to_numpy(), seed=SEED + 2)
    # 6. known answers: Betfair close log loss on main tours 2021-25, and A wins about half
    m = prim
    out["known_answers"] = checks.known_answers(df["y"].to_numpy()[m], p_mkt[m], (0.57, 0.64))
    return out


VERSION = "v1"


def main() -> int:
    global VERSION
    mcp, joined_pkl, out_json = sys.argv[1:4]
    VERSION = sys.argv[4] if len(sys.argv) > 4 else "v1"
    joined = pd.read_pickle(joined_pkl)
    joined = joined.assign(match_key=np.arange(len(joined)), flip=coin_flip(len(joined), SEED))
    df, cnts = load(mcp, joined)
    df = df[df["p_bf_close"].notna()].reset_index(drop=True)
    X = matchup(df)
    dna = COMPACT if VERSION == "v2" else [c for c in X.columns if c not in ("d_unreturned", "x_serve_vs_return2")]   # v1 as first run
    res = {"version": VERSION, "manifest": provenance.manifest({"mcp": mcp, "joined": joined_pkl}, {"orientation": SEED, "bootstrap": SEED},
                                          " ".join(["python"] + sys.argv)),
           "rows_by_year_level": df.groupby(["year", "level"]).size().unstack(fill_value=0).to_dict(), "results": {}}
    test = df["year"].isin(TEST_YEARS).values
    prim = df["year"].isin(PRIMARY_YEARS).values & df["level"].isin(["ATP main", "WTA main"]).values
    y = df["y"].values

    preds = {}
    for market in ("bf_close", "b365_open"):
        ok = df[f"p_{market}"].notna().values
        for k, cols, kind in (("M0", [], "logit"), ("M1", dna, "logit"), ("M1gb", dna, "lgbm")):
            full = np.full(len(df), np.nan)
            full[ok] = walk_forward(df[ok].reset_index(drop=True), X[ok].reset_index(drop=True), market, cols, kind)
            preds[f"{k}_{market}"] = full
    preds["dna_only"] = walk_forward(df, X, None, dna, "logit")
    preds["basic_only"] = walk_forward(df, X, None, BASIC, "logit")

    for market in ("bf_close", "b365_open"):
        for name, mask in (("PRIMARY 2021-25 main tours", prim), ("all test years 2018-25, all levels", test)):
            m = mask & np.isfinite(preds[f"M0_{market}"])
            r = {"n": int(m.sum()), "ll_market_raw": round(float(ll(y[m], df[f"p_{market}"].values[m]).mean()), 5),
                 "ll_M0": round(float(ll(y[m], preds[f"M0_{market}"][m]).mean()), 5)}
            for k in ("M1", "M1gb"):
                r[f"{k}_minus_M0"] = [round(v, 5) for v in boot_mean(ll(y[m], preds[f"{k}_{market}"][m]) - ll(y[m], preds[f"M0_{market}"][m]), seed=SEED)]
            r["M1_minus_M0_by_year"] = {int(yr): [int((m & (df["year"].values == yr)).sum()),
                                                  round(float((ll(y[m & (df["year"].values == yr)], preds[f"M1_{market}"][m & (df["year"].values == yr)])
                                                               - ll(y[m & (df["year"].values == yr)], preds[f"M0_{market}"][m & (df["year"].values == yr)])).mean()), 5)]
                                        for yr in sorted(set(df.loc[m, "year"]))}
            res["results"][f"{market} | {name}"] = r
    m = test & np.isfinite(preds["dna_only"])
    res["results"]["no market: DNA vs basic serve/return (all test rows)"] = {
        "n": int(m.sum()), "ll_basic": round(float(ll(y[m], preds["basic_only"][m]).mean()), 5),
        "ll_dna": round(float(ll(y[m], preds["dna_only"][m]).mean()), 5),
        "dna_minus_basic": [round(v, 5) for v in boot_mean(ll(y[m], preds["dna_only"][m]) - ll(y[m], preds["basic_only"][m]), seed=SEED)],
        "ll_bf_close": round(float(ll(y[m], df["p_bf_close"].values[m]).mean()), 5)}

    # does bet365's close move toward what DNA adds at the open? (beyond a market-only recalibration)
    m = test & np.isfinite(preds["M1_b365_open"]) & df["p_b365_close"].notna().values
    move = (df["p_b365_close"] - df["p_b365_open"]).values[m]
    l0 = preds["M0_b365_open"][m] - df["p_b365_open"].values[m]
    extra = preds["M1_b365_open"][m] - preds["M0_b365_open"][m]
    A = np.c_[np.ones(m.sum()), l0, extra]
    coef = np.linalg.lstsq(A, move, rcond=None)[0]
    g = np.random.default_rng(SEED)
    bs = np.array([np.linalg.lstsq(A[i], move[i], rcond=None)[0][2] for i in (g.integers(0, len(move), len(move)) for _ in range(1000))])
    s = np.abs(extra) >= 0.03
    res["results"]["b365 open->close move toward DNA's extra lean (test 2018-25, all levels)"] = {
        "n": int(m.sum()), "share_of_dna_lean_absorbed": [round(float(coef[2]), 4), *[round(float(v), 4) for v in np.percentile(bs, [2.5, 97.5])]],
        "where_dna_shifts_3pts_or_more": {"n": int(s.sum()), "move_toward_dna_pts": [round(100 * v, 3) for v in boot_mean(np.sign(extra[s]) * move[s], seed=SEED)]}}

    betting = {}
    for market, comm in (("bf_close", 0.02), ("b365_open", 0.0)):
        for k in ("M1", "M1gb"):
            for thr in (0.03, 0.05, 0.08):
                m = test & np.isfinite(preds[f"{k}_{market}"])
                betting[f"{market} {k} edge>={thr}"] = back_bets(y[m], preds[f"{k}_{market}"][m], df[f"oddsA_{market}"].values[m],
                                                                 df[f"oddsB_{market}"].values[m], thr, comm, seed=SEED).as_dict()
    res["betting_test_2018_25"] = betting
    ok = df["p_bf_close"].notna()
    fe = X[dna].fillna(0.0).copy()
    fe["mkt"] = logit(df["p_bf_close"].values)
    mdl = fit_logistic(fe[ok], df.loc[ok, "y"], C=0.1)
    res["coef_M1_bf_close"] = {k: round(float(v), 4) for k, v in sorted(zip(fe.columns, mdl[-1].coef_[0]), key=lambda kv: -abs(kv[1]))}

    prim_delta = tuple(res["results"]["bf_close | PRIMARY 2021-25 main tours"]["M1_minus_M0"])
    res["checks"] = run_checks(df, X, dna, prim, joined, cnts)
    res["alarms"] = checks.alarms(prim_delta, max([b["roi"] for b in betting.values() if b["n"] >= 100], default=None))
    res["checks_passed"] = all(c["pass"] for c in res["checks"].values())
    with open(out_json, "w") as f:
        json.dump(res, f, indent=1, default=str)
    print(json.dumps({k: res[k] for k in ("results", "checks", "alarms", "checks_passed")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
