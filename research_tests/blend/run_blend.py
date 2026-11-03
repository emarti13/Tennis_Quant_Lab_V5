"""Blend: the small signals together on top of the closing price, and the money at executable prices.

Usage:  python research_tests/blend/run_blend.py JOINED_PKL HISTORY_DIR EVENTS_CSV OUT_JSON

Pre-registered 2026-11-03, after the audit (research_tests/README.md, docs/experiments/2026-11-03-*):
each signal is too small alone at a 3% margin; this asks whether together they clear it. The inputs were
chosen from the 2016-2025 exploration, so the test years 2022-2025 here are not a clean hold-out for the
choice of inputs (only for the fitted weights); anything that passes goes to a registered forward test.

  INPUTS (A minus B; public before the match)
    age_gap      (age A - age B) / 5, clipped to [-3, 3]           (older overpriced: -1.4 pts, n=35k)
    qualifier    qualifier or lucky loser, A minus B; ATP and WTA main only (no entry data for Challengers:
                 0 there, with a main-tour indicator)                (+1.2 pts)
    pre_slam     top 30 in an event starting <= 15 days before a Slam (-2.5 pts on ATP main)
    season_end   ranked 31-90 after October 20                      (-4.1 pts)
    jet_lag      moved 5+ hours (either way) since a previous match 5 days ago or less (-3.7 pts)
  "Betfair" in the Kaggle data is a sportsbook price with its margin in it: no commission is charged.

  SET       ATP main, WTA main, Challenger with odds, 2016-2025; walk-forward by year from 2016, test 2022-2025.
  PRIMARY   M0 = logistic on logit(close); M1 = M0 + the five inputs (L2, C=0.3): log loss M1 - M0 on
            2022-2025 at the "Betfair" close, 95% range resampling matches; and the money: back the side
            the model rates at least 3 points above the price's implied chance (one bet per match, the
            larger edge), at the "Betfair" close and bet365 close, 2022-2025.
  SECONDARY edge thresholds 2 / 5 points; by level; the fitted weights.
  CHECKS    swap-source; planted edge; market null; known answers.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "research_tests" / "incentives"))
sys.path.insert(0, str(ROOT / "research_tests" / "travel"))
from research_kit import checks, provenance  # noqa: E402
from research_kit.core import boot_mean, coin_flip, devig, log_loss, logit, orient, walk_forward  # noqa: E402
import run_incentives as inc  # noqa: E402
import run_travel as trv  # noqa: E402

SEED = 20261103
TEST_YEARS = range(2022, 2026)
BOOKS = {"bf_close": ("bf_w", "bf_l"), "b365_close": ("b365_w", "b365_l")}
INPUTS = ["age_gap", "qualifier", "pre_slam", "season_end", "jet_lag", "main_tour"]


def history_table(hist_dir: Path) -> pd.DataFrame:
    """Per (tourney_id, round, winner, loser): incentive flags and ages for both players."""
    h = inc.history(hist_dir)
    p = inc.player_rows(h)
    fm = inc.flags_per_match(p)
    ages = h[["tourney_id", "round", "winner_name", "loser_name", "winner_age", "loser_age"]].rename(
        columns={"winner_name": "w", "loser_name": "l", "winner_age": "age_w", "loser_age": "age_l"})
    return fm.merge(ages.drop_duplicates(["tourney_id", "round", "w", "l"]), on=["tourney_id", "round", "w", "l"], how="left")


def build(joined: pd.DataFrame, hist: pd.DataFrame, travel: pd.DataFrame) -> pd.DataFrame:
    j = joined.merge(hist, left_on=["tid", "wh_round", "winner_name", "loser_name"], right_on=["tourney_id", "round", "w", "l"], how="inner")
    j = j.merge(travel, on="match_key", how="left").sort_values("match_key", kind="stable")
    flip = j["flip"].to_numpy(bool)
    main = j["odds_level"].isin(["ATP main", "WTA main"]).to_numpy()
    out = pd.DataFrame({"match_key": j["match_key"].values, "year": pd.to_datetime(j["wh_date"]).dt.year.values,
                        "level": j["odds_level"].values, "y": (~flip).astype(int), "main_tour": main.astype(int)})
    aa, ab = orient(pd.to_numeric(j["age_w"], errors="coerce").to_numpy(), pd.to_numeric(j["age_l"], errors="coerce").to_numpy(), flip)
    out["age_known"] = (np.isfinite(aa) & np.isfinite(ab)).astype(int)
    out["age_gap"] = np.clip(np.nan_to_num((aa - ab) / 5, nan=0.0), -3, 3)          # unknown age -> 0, flagged by age_known
    for f in ("qualifier", "pre_slam", "season_end"):
        a, b = orient(j[f"{f}_w"].to_numpy(), j[f"{f}_l"].to_numpy(), flip)
        out[f] = (a - b) * (main if f == "qualifier" else 1)
    je = j[["jet_east_1", "jet_west_1"]].fillna(0).max(axis=1).to_numpy()
    jw = j[["jet_east_2", "jet_west_2"]].fillna(0).max(axis=1).to_numpy()
    a, b = orient(je, jw, flip)
    out["jet_lag"] = a - b
    for book, (c1, c2) in BOOKS.items():
        oa, ob = orient(pd.to_numeric(j[c1], errors="coerce"), pd.to_numeric(j[c2], errors="coerce"), flip)
        out[f"p_{book}"] = devig(oa, ob)
        out[f"oa_{book}"], out[f"ob_{book}"] = oa, ob
    return out


def fit_predict(d, cols, y=None, extra=None, return_model=False):
    from sklearn.linear_model import LogisticRegression
    X = pd.DataFrame({"mkt": logit(d["p_bf_close"].to_numpy())})
    for c in cols:
        X[c] = d[c].to_numpy()
    if extra is not None:
        X["extra"] = extra
    yy = d["y"].to_numpy() if y is None else y
    if return_model:
        return LogisticRegression(C=0.3, max_iter=2000).fit(X, yy), list(X.columns)
    return walk_forward(d["year"].to_numpy(), TEST_YEARS,
                        lambda tr, te: LogisticRegression(C=0.3, max_iter=2000).fit(X[tr], yy[tr]).predict_proba(X[te])[:, 1],
                        first_train_year=2016)


def money(d, p, book, edge):
    oa, ob = d[f"oa_{book}"].to_numpy(), d[f"ob_{book}"].to_numpy()
    ea, eb = p - 1 / oa, (1 - p) - 1 / ob
    ok = np.isfinite(p) & np.isfinite(oa) & np.isfinite(ob)
    side_a = ok & (ea >= edge) & (ea >= eb)
    side_b = ok & (eb >= edge) & (eb > ea)
    y = d["y"].to_numpy()
    o = np.where(side_a, oa, ob)
    won = np.where(side_a, y == 1, y == 0)
    pnl = np.where(won, o - 1, -1.0)[side_a | side_b]
    if len(pnl) == 0:
        return {"n": 0}
    m, lo, hi = boot_mean(pnl, seed=SEED)
    return {"n": int(len(pnl)), "roi": round(m, 4), "range": [round(lo, 4), round(hi, 4)], "share_on_A_side": round(float(side_a.sum() / len(pnl)), 3)}


def swap_source(joined):
    j = joined.copy()
    for a, b in [("winner_name", "loser_name"), *BOOKS.values()]:
        j[a], j[b] = joined[b].values, joined[a].values
    return j.assign(_swapped=1)


def main() -> int:
    joined_pkl, hist_dir, events_csv, out_json = sys.argv[1], Path(sys.argv[2]), sys.argv[3], sys.argv[4]
    joined = pd.read_pickle(joined_pkl)
    joined = joined[joined["tour"].isin(["ATP", "WTA"]) & joined["odds_level"].isin(["ATP main", "WTA main", "Challenger"])].reset_index(drop=True)
    joined = joined.assign(match_key=np.arange(len(joined)), flip=coin_flip(len(joined), SEED))
    hist = history_table(hist_dir)
    ev = pd.read_csv(events_csv)
    travel = trv.player_flags(joined, ev)[["match_key", "jet_east_1", "jet_west_1", "jet_east_2", "jet_west_2"]]
    df = build(joined, hist, travel)
    df = df[(df["year"] >= 2016) & df["p_bf_close"].notna()].reset_index(drop=True)
    cols = INPUTS + ["age_known"]
    res = {"manifest": provenance.manifest({"joined": joined_pkl, "history": str(hist_dir), "events": events_csv}, {"orientation": SEED, "bootstrap": SEED},
                                          " ".join(["python"] + sys.argv)),
           "rows": int(len(df)), "by_level": df["level"].value_counts().to_dict(),
           "input_nonzero_share": {c: round(float((df[c] != 0).mean()), 4) for c in INPUTS}, "results": {}}
    R = res["results"]
    y = df["y"].to_numpy()
    test = df["year"].isin(TEST_YEARS).to_numpy()
    p0, p1 = fit_predict(df, []), fit_predict(df, cols)
    m = test & np.isfinite(p1)
    R["PRIMARY M1 (blend) minus M0, 'Betfair' close, 2022-25 log loss"] = [round(v, 5) for v in boot_mean(log_loss(y[m], p1[m]) - log_loss(y[m], p0[m]), seed=SEED)] + [int(m.sum())]
    sub = df[m].reset_index(drop=True)
    for book in BOOKS:
        for e in (0.02, 0.03, 0.05):
            key = f"{'PRIMARY ' if e == 0.03 else ''}money: model edge >= {int(100 * e)} pts at {book}, 2022-25"
            R[key] = money(sub, p1[m], book, e)
            R[f"  (market-only recalibration, same rule) edge >= {int(100 * e)} at {book}"] = money(sub, p0[m], book, e)
    for lv in ("ATP main", "WTA main", "Challenger"):
        mm = m & (df["level"] == lv).to_numpy()
        R[f"M1 minus M0 by level: {lv}"] = [round(v, 5) for v in boot_mean(log_loss(y[mm], p1[mm]) - log_loss(y[mm], p0[mm]), seed=SEED)] + [int(mm.sum())]
        s2 = df[mm].reset_index(drop=True)
        R[f"money edge >= 3 at bf_close, {lv}"] = money(s2, p1[mm], "bf_close", 0.03)
    mdl, names = fit_predict(df[df["year"] < 2022], cols, return_model=True)
    R["weights fitted on 2016-21 (log-odds per unit)"] = {n: round(float(c), 4) for n, c in zip(names, mdl.coef_[0])}
    # checks
    C = {}
    raw = joined[joined["tour"] == "WTA"]
    hist_sw = hist.rename(columns={"w": "l", "l": "w", "age_w": "age_l", "age_l": "age_w",
                                   **{f"{f}_w": f"{f}_l" for f in inc.FLAGS}, **{f"{f}_l": f"{f}_w" for f in inc.FLAGS}})
    C["swap_source"] = checks.swap_source(
        lambda r, f: build(r.assign(flip=f), hist_sw if "_swapped" in r else hist,
                           trv.player_flags(r, ev)[["match_key", "jet_east_1", "jet_west_1", "jet_east_2", "jet_west_2"]]),
        raw, swap_source, raw["flip"].to_numpy(bool), cols + ["p_bf_close", "oa_bf_close", "ob_bf_close"])
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
    prim = R["PRIMARY money: model edge >= 3 pts at bf_close, 2022-25"]
    res["alarms"] = checks.alarms(tuple(R["PRIMARY M1 (blend) minus M0, 'Betfair' close, 2022-25 log loss"][:3]), prim.get("roi") if prim.get("n", 0) >= 100 else None)
    Path(out_json).write_text(json.dumps(res, indent=1, default=str) + "\n")
    print(json.dumps({k: v for k, v in res.items() if k != "manifest"}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
