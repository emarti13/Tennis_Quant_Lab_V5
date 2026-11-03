"""Incentives from the rankings calendar: does the price miss how much a player has to play for?

Usage:  python research_tests/incentives/run_incentives.py JOINED_PKL HISTORY_DIR OUT_JSON

JOINED_PKL   the Kaggle odds join (2014-2025; bet365 open/close, Betfair close; first player = winner)
HISTORY_DIR  .v5_history_cache (Sackmann-format ATP.csv, WTA.csv, Challenger.csv: rank, ranking points,
             entry, seed, tourney level and date, round)

Pre-registered 2026-11-03, before any result was seen. Ratings-based prices treat every week the same;
players do not. Each player's incentives at the match, from information public before it:

  bubble_main    ranked 95-125 (WTA 95-125) and the next Grand Slam's entry deadline (start - 42 days)
                 is 0-42 days away: winning points now decides direct entry
  bubble_quali   ranked 220-260, same window: decides a place in Slam qualifying
  defending      reached the semi-final or better at the same event last year (points to defend)
  pre_slam       ranked top 30 in an event that ends within 8 days of a Grand Slam's start
  season_end     a match after October 20 for a player ranked 31-90 (no year-end finals at stake,
                 off-season close)
  wildcard       entered as a wildcard (ATP/WTA tour events; often young or home players)
  qualifier      entered from qualifying or as a lucky loser (extra matches, in form)
Every flag is A's minus B's (-1, 0, +1).

  SET       ATP main, WTA main, Challenger with odds; walk-forward by year from 2016, test 2022-2025.
  PRIMARY   M0 = logistic on logit(Betfair close); M1 = M0 + the seven flag differences (L2): log loss
            M1 - M0 on 2022-2025, 95% range resampling matches.
  SECONDARY each flag on its own: A's result minus Betfair close where A has the flag and B does not
            (and the reverse), 2016-2025; the money version for any flag whose 2016-21 residual is
            beyond 2 points: back the indicated side at Betfair close (2% commission) and bet365 close
            in 2022-2025 only.
  CHECKS    swap-source; planted edge; market null; known answers.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research_kit import checks, provenance  # noqa: E402
from research_kit.core import boot_mean, coin_flip, devig, log_loss, logit, orient, walk_forward  # noqa: E402

SEED = 20261103
TEST_YEARS = range(2022, 2026)
FLAGS = ["bubble_main", "bubble_quali", "defending", "pre_slam", "season_end", "wildcard", "qualifier"]
BOOKS = {"bf_close": ("bf_w", "bf_l"), "b365_close": ("b365_w", "b365_l")}
# the Kaggle "Betfair" price is a sportsbook price with its margin in it (audit 2026-11-03): no commission
COMMISSION = {"bf_close": 0.0, "b365_close": 0.0}
ROUND_RANK = {"Q1": 0, "Q2": 1, "Q3": 2, "R128": 3, "R64": 4, "R32": 5, "R16": 6, "QF": 7, "SF": 8, "F": 9}


def history(hist_dir: Path) -> pd.DataFrame:
    frames = []
    for f, tour in (("ATP.csv", "ATP"), ("WTA.csv", "WTA"), ("Challenger.csv", "ATP")):
        d = pd.read_csv(hist_dir / f, low_memory=False)
        d["tour"] = tour
        frames.append(d)
    h = pd.concat(frames, ignore_index=True)
    h["date"] = pd.to_datetime(h["tourney_date"].astype(str).str[:8], format="%Y%m%d", errors="coerce")
    return h.dropna(subset=["date"])


def slam_starts(h: pd.DataFrame) -> dict:
    g = h[h["tourney_level"] == "G"].groupby(["tour", "tourney_id"])["date"].min()
    return {t: np.sort(g.loc[t].to_numpy(dtype="datetime64[D]")) for t in g.index.get_level_values(0).unique()}


def player_rows(h: pd.DataFrame) -> pd.DataFrame:
    """One row per (match, player) with the player's incentive flags at that match."""
    slams = slam_starts(h)
    rows = []
    for side in ("winner", "loser"):
        x = pd.DataFrame({"tour": h["tour"], "tourney_id": h["tourney_id"], "tourney_name": h["tourney_name"], "level": h["tourney_level"],
                          "date": h["date"], "round": h["round"], "name": h[f"{side}_name"], "rank": pd.to_numeric(h[f"{side}_rank"], errors="coerce"),
                          "entry": h[f"{side}_entry"].astype(str).str.upper(), "w": h["winner_name"], "l": h["loser_name"]})
        rows.append(x)
    p = pd.concat(rows, ignore_index=True)
    # next Slam entry deadline relative to the event start
    def days_to_deadline(r):
        s = slams.get(r.tour)
        if s is None:
            return np.nan
        d = np.datetime64(r.date.date(), "D")
        later = s[s - np.timedelta64(42, "D") >= d]
        return np.nan if len(later) == 0 else float((later[0] - np.timedelta64(42, "D") - d).astype(int))
    def days_to_slam(r):
        s = slams.get(r.tour)
        if s is None:
            return np.nan
        d = np.datetime64(r.date.date(), "D")
        later = s[s > d]
        return np.nan if len(later) == 0 else float((later[0] - d).astype(int))
    ev = p.drop_duplicates(["tour", "tourney_id"])[["tour", "tourney_id", "date"]].copy()
    ev["dd"] = [days_to_deadline(r) for r in ev.itertuples()]
    ev["ds"] = [days_to_slam(r) for r in ev.itertuples()]
    p = p.merge(ev[["tour", "tourney_id", "dd", "ds"]], on=["tour", "tourney_id"], how="left")
    p["bubble_main"] = (p["rank"].between(95, 125) & p["dd"].between(0, 42)).astype(int)
    p["bubble_quali"] = (p["rank"].between(220, 260) & p["dd"].between(0, 42)).astype(int)
    p["pre_slam"] = ((p["rank"] <= 30) & (p["level"] != "G") & p["ds"].between(0, 15)).astype(int)   # event starts <= 15 days before (ends within ~8)
    p["season_end"] = ((p["date"].dt.month * 100 + p["date"].dt.day >= 1020) & p["rank"].between(31, 90)).astype(int)
    p["wildcard"] = (p["entry"] == "WC").astype(int)
    p["qualifier"] = p["entry"].isin(["Q", "LL"]).astype(int)
    # defending: reached SF or better at the same event name last year
    p["rr"] = p["round"].map(ROUND_RANK)
    best = p.groupby(["tour", "tourney_name", p["date"].dt.year, "name"])["rr"].max().rename("best").reset_index()
    won_final = p[(p["round"] == "F") & (p["name"] == p["w"])][["tour", "tourney_name", "date", "name"]]
    best = best.merge(won_final.assign(yr=won_final["date"].dt.year)[["tour", "tourney_name", "yr", "name"]].assign(champ=1),
                      left_on=["tour", "tourney_name", "date", "name"], right_on=["tour", "tourney_name", "yr", "name"], how="left").drop(columns=["yr"])
    best["date"] = best["date"] + 1
    p = p.merge(best.rename(columns={"date": "yr"}), left_on=["tour", "tourney_name", p["date"].dt.year, "name"],
                right_on=["tour", "tourney_name", "yr", "name"], how="left")
    p["defending"] = (p["best"].fillna(-1) >= ROUND_RANK["SF"]).astype(int)
    return p


def build(joined: pd.DataFrame, flags_by_match: pd.DataFrame) -> pd.DataFrame:
    j = joined.merge(flags_by_match, left_on=["tid", "wh_round", "winner_name", "loser_name"],
                     right_on=["tourney_id", "round", "w", "l"], how="inner").sort_values("match_key", kind="stable")
    flip = j["flip"].to_numpy(bool)
    out = pd.DataFrame({"match_key": j["match_key"].values, "year": pd.to_datetime(j["wh_date"]).dt.year.values,
                        "level": j["odds_level"].values, "y": (~flip).astype(int)})
    for f in FLAGS:
        a, b = orient(j[f"{f}_w"].to_numpy(), j[f"{f}_l"].to_numpy(), flip)
        out[f"a_{f}"], out[f"b_{f}"] = a, b
        out[f"d_{f}"] = a - b
    for book, (c1, c2) in BOOKS.items():
        oa, ob = orient(pd.to_numeric(j[c1], errors="coerce"), pd.to_numeric(j[c2], errors="coerce"), flip)
        out[f"p_{book}"] = devig(oa, ob)
        out[f"oa_{book}"], out[f"ob_{book}"] = oa, ob
    return out


def flags_per_match(p: pd.DataFrame) -> pd.DataFrame:
    w = p[p["name"] == p["w"]][["tourney_id", "round", "w", "l"] + FLAGS].rename(columns={f: f"{f}_w" for f in FLAGS})
    l = p[p["name"] == p["l"]][["tourney_id", "round", "w", "l"] + FLAGS].rename(columns={f: f"{f}_l" for f in FLAGS})
    return w.merge(l, on=["tourney_id", "round", "w", "l"]).drop_duplicates(["tourney_id", "round", "w", "l"])


def swap_source(joined: pd.DataFrame) -> pd.DataFrame:
    j = joined.copy()
    for a, b in [("winner_name", "loser_name"), *BOOKS.values()]:
        j[a], j[b] = joined[b].values, joined[a].values
    return j


def fit_predict(d, cols, y=None, extra=None):
    from sklearn.linear_model import LogisticRegression
    X = pd.DataFrame({"mkt": logit(d["p_bf_close"].to_numpy())})
    for c in cols:
        X[c] = d[c].to_numpy()
    if extra is not None:
        X["extra"] = extra
    yy = d["y"].to_numpy() if y is None else y
    return walk_forward(d["year"].to_numpy(), TEST_YEARS,
                        lambda tr, te: LogisticRegression(C=0.3, max_iter=1000).fit(X[tr], yy[tr]).predict_proba(X[te])[:, 1],
                        first_train_year=2016)


def main() -> int:
    joined_pkl, hist_dir, out_json = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
    joined = pd.read_pickle(joined_pkl)
    joined = joined[joined["tour"].isin(["ATP", "WTA"]) & joined["odds_level"].isin(["ATP main", "WTA main", "Challenger"])].reset_index(drop=True)
    joined = joined.assign(match_key=np.arange(len(joined)), flip=coin_flip(len(joined), SEED))
    fm = flags_per_match(player_rows(history(hist_dir)))
    df = build(joined, fm)
    df = df[(df["year"] >= 2016) & df["p_bf_close"].notna()].reset_index(drop=True)
    res = {"manifest": provenance.manifest({"joined": joined_pkl, "history": str(hist_dir)}, {"orientation": SEED, "bootstrap": SEED}, " ".join(["python"] + sys.argv)),
           "rows": int(len(df)), "by_level": df["level"].value_counts().to_dict(),
           "flag_rates": {f: round(float(((df[f"a_{f}"] + df[f"b_{f}"]) > 0).mean()), 4) for f in FLAGS}, "results": {}}
    R = res["results"]
    y = df["y"].to_numpy()
    test = df["year"].isin(TEST_YEARS).to_numpy()
    cols = [f"d_{f}" for f in FLAGS]
    p0, p1 = fit_predict(df, []), fit_predict(df, cols)
    m = test & np.isfinite(p1)
    R["PRIMARY M1 (seven incentive flags) minus M0, Betfair close, 2022-25 log loss"] = [round(v, 5) for v in boot_mean(log_loss(y[m], p1[m]) - log_loss(y[m], p0[m]), seed=SEED)] + [int(m.sum())]
    early = (df["year"] < 2022).to_numpy()
    for f in FLAGS:
        a_only, b_only = (df[f"d_{f}"] == 1).to_numpy(), (df[f"d_{f}"] == -1).to_numpy()
        # express from the flagged player's side
        resid = np.where(a_only, y - df["p_bf_close"], np.where(b_only, (1 - y) - (1 - df["p_bf_close"]), np.nan))
        r_all = resid[np.isfinite(resid)]
        r_early = resid[np.isfinite(resid) & early]
        R[f"{f}: flagged player won minus Betfair close (pts), 2016-25 / 2016-21"] = {
            "all": [round(100 * v, 2) for v in boot_mean(r_all, seed=SEED)] + [int(len(r_all))],
            "2016-21": [round(100 * v, 2) for v in boot_mean(r_early, seed=SEED)] + [int(len(r_early))]}
        e = R[f"{f}: flagged player won minus Betfair close (pts), 2016-25 / 2016-21"]["2016-21"]
        if abs(e[0]) >= 2:
            back_flagged = e[0] > 0
            for book in BOOKS:
                x = df[test & (a_only | b_only) & df[f"p_{book}"].notna().to_numpy()]
                a_flag = (x[f"d_{f}"] == 1).to_numpy()
                back_a = a_flag if back_flagged else ~a_flag
                o = np.where(back_a, x[f"oa_{book}"], x[f"ob_{book}"])
                won = np.where(back_a, x["y"] == 1, x["y"] == 0)
                pnl = np.where(won, (o - 1) * (1 - COMMISSION[book]), -1.0)
                mean, lo, hi = boot_mean(pnl, seed=SEED)
                R[f"MONEY {f}: back the {'flagged' if back_flagged else 'other'} player at {book}, 2022-25"] = {"n": int(len(x)), "roi": round(mean, 4), "range": [round(lo, 4), round(hi, 4)]}
    # season_end audit (it crossed the 2-point bar): by level and year, and who the opponents are
    se = df[(df["d_season_end"] != 0)].copy()
    se["flag_won"] = np.where(se["d_season_end"] == 1, se["y"], 1 - se["y"])
    se["flag_p"] = np.where(se["d_season_end"] == 1, se["p_bf_close"], 1 - se["p_bf_close"])
    R["season_end audit"] = {
        "by level": {lv: [int(len(g))] + [round(100 * v, 2) for v in boot_mean((g["flag_won"] - g["flag_p"]).to_numpy(), seed=SEED)] for lv, g in se.groupby("level")},
        "by year": {int(yr): [int(len(g)), round(100 * float((g["flag_won"] - g["flag_p"]).mean()), 2)] for yr, g in se.groupby("year")},
        "flagged player's mean closing chance": round(float(se["flag_p"].mean()), 3)}
    C = {}
    raw = joined[joined["tour"] == "WTA"]
    # the history file is winner-first too: a relabelled source swaps both files' sides
    fm_sw = fm.rename(columns={**{f"{f}_w": f"{f}_l" for f in FLAGS}, **{f"{f}_l": f"{f}_w" for f in FLAGS}, "w": "l", "l": "w"})
    C["swap_source"] = checks.swap_source(lambda r, f: build(r.assign(flip=f), fm_sw if "_swapped" in r else fm), raw,
                                          lambda r: swap_source(r).assign(_swapped=1), raw["flip"].to_numpy(bool),
                                          cols + ["p_bf_close", "oa_bf_close", "ob_bf_close"])
    p_mkt = df["p_bf_close"].to_numpy()

    def run(yy, z):
        a0, a1 = fit_predict(df, [], y=yy), fit_predict(df, cols, y=yy, extra=z)
        mm = test & np.isfinite(a1)
        return {"delta": boot_mean(log_loss(yy[mm], a1[mm]) - log_loss(yy[mm], a0[mm]), seed=SEED)}
    C["planted_edge"] = checks.planted_edge(run, p_mkt, size=0.15, seed=SEED)
    C["market_null"] = checks.market_null(run, p_mkt, seed=SEED + 1)
    C["known_answers"] = checks.known_answers(y[test], p_mkt[test], (0.55, 0.66))
    res["checks"] = C
    res["checks_passed"] = all(c["pass"] for c in C.values())
    Path(out_json).write_text(json.dumps(res, indent=1, default=str) + "\n")
    print(json.dumps({k: v for k, v in res.items() if k != "manifest"}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
