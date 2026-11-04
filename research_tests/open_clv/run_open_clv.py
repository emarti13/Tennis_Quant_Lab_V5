"""Betting early: does each signal (and the blend) get ahead of the close when you bet at the open?

Usage:  python research_tests/open_clv/run_open_clv.py JOINED_PKL CANON_PKL HISTORY_DIR EVENTS_CSV ELEV_CSV OUT_JSON

Pre-registered 2026-11-04, before any open-price result was seen for these inputs. The user will not bet
at the close. A signal the close already knows can still pay a bettor who acts earlier, if the price
moves toward the signal's side between the open and the close. Every earlier test (incentives, travel,
blend, scout batch 1) asked only whether the signal beats the close.

  PRICES    open = bet365 opening price (de-vigged; about 6.7% margin). The Kaggle "Betfair" opening column
            is not usable (median overround 1.88, both sides near 1.01: early thin-book prints) and is not used.
            close = the "Betfair"-labelled sportsbook close (about 3.2% margin), the sharpest close on file;
            bet365 close is reported next to it.
  INPUTS    every input from the earlier tests, built by the same code (A minus B):
            blend:      age_gap, qualifier (main tours), pre_slam, season_end, jet_lag, main_tour, age_known
            incentives: bubble_main, bubble_quali, defending, wildcard
            scout 1:    hangover, short_rest, altitude, venue, layoff, surface, freepass, rest_diff, surface_spec
  SET       ATP main, WTA main, Challenger with both prices, 2016-2025; test years 2022-2025.

  PER FLAG (binary flags; matches where exactly one side has it)
    move      de-vigged close minus de-vigged open on the flagged side, in points (95% range resampling
              flagged players), 2016-21 and 2022-25. Positive = the market moves toward the flagged player.
    clv_hit   share of those matches where the close is shorter on the flagged side than the open.
    direction fixed by the sign of the 2016-21 move (back the side the market moves toward).
    clv_roi   2022-25, back that side at the bet365 open: mean(close probability x open odds - 1), i.e. the
              expected return if the close is the truth. Far less noisy than results; the margin is in it.
    roi       2022-25, the same bets settled on results (realised return).
    Continuous inputs (age_gap, rest_diff, surface_spec): slope of move on the input, pts per unit.

  BLEND AT THE OPEN (PRIMARY)
    M0 = logistic on logit(open); M1 = M0 + all inputs above (L2, C=0.3); walk-forward from 2016,
    test 2022-2025. Report: log loss M1 - M0 (against the open); M1's log loss against the CLOSE's
    (does open + signals reach the close?); money: back the side M1 rates at least 2 / 3 / 5 points above
    the open's implied chance, at the bet365 open, with clv_roi, roi, mean move toward the bet, clv_hit.
    PRIMARY money = edge >= 3 points: clv_roi and roi with 95% ranges.
  CHECKS    swap-source on the price build; planted edge and market null on the open-price blend; known
            answers; the input builds are the ones whose own swap checks pass in their scripts.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
for sub in ("", "research_tests/incentives", "research_tests/travel", "research_tests/blend", "research_tests/scout"):
    sys.path.insert(0, str(ROOT / sub))
from research_kit import checks, provenance  # noqa: E402
from research_kit.core import boot_mean, coin_flip, devig, log_loss, logit, orient, walk_forward  # noqa: E402
import run_blend as bl  # noqa: E402
import run_incentives as inc  # noqa: E402
import run_scout as sc  # noqa: E402
import run_travel as trv  # noqa: E402

SEED = 20261103                       # same orientation as every earlier test
TEST_YEARS = range(2022, 2026)
OPEN, CLOSE, CLOSE2 = ("b365_w_opening", "b365_l_opening"), ("bf_w", "bf_l"), ("b365_w", "b365_l")
INC_EXTRA = ["bubble_main", "bubble_quali", "defending", "wildcard"]
SCOUT = ["hangover", "short_rest", "altitude", "venue", "layoff", "surface", "freepass"]
SCOUT_CONT = ["rest_diff", "surface_spec"]
BLEND = ["age_gap", "qualifier", "pre_slam", "season_end", "jet_lag", "main_tour", "age_known"]
BINARY = ["qualifier", "pre_slam", "season_end", "jet_lag"] + INC_EXTRA + SCOUT
CONT = ["age_gap"] + SCOUT_CONT


def prices(joined: pd.DataFrame) -> pd.DataFrame:
    j = joined.sort_values("match_key", kind="stable")
    flip = j["flip"].to_numpy(bool)
    out = pd.DataFrame({"match_key": j["match_key"].values})
    for lab, (c1, c2) in (("open", OPEN), ("close", CLOSE), ("close2", CLOSE2)):
        oa, ob = orient(pd.to_numeric(j[c1], errors="coerce"), pd.to_numeric(j[c2], errors="coerce"), flip)
        out[f"p_{lab}"] = devig(oa, ob)
        out[f"oa_{lab}"], out[f"ob_{lab}"] = oa, ob
    return out


def inc_extra(joined: pd.DataFrame, hist: pd.DataFrame) -> pd.DataFrame:
    j = joined.merge(hist, left_on=["tid", "wh_round", "winner_name", "loser_name"], right_on=["tourney_id", "round", "w", "l"],
                     how="inner").sort_values("match_key", kind="stable")
    flip = j["flip"].to_numpy(bool)
    out = pd.DataFrame({"match_key": j["match_key"].values})
    for f in INC_EXTRA:
        a, b = orient(j[f"{f}_w"].to_numpy(), j[f"{f}_l"].to_numpy(), flip)
        out[f] = a - b
    return out


def swap_source(joined):
    j = joined.copy()
    for a, b in [("winner_name", "loser_name"), OPEN, CLOSE, CLOSE2]:
        j[a], j[b] = joined[b].values, joined[a].values
    return j


def fit_predict(d, cols, y=None, extra=None):
    from sklearn.linear_model import LogisticRegression
    X = pd.DataFrame({"mkt": logit(d["p_open"].to_numpy())})
    for c in cols:
        X[c] = d[c].to_numpy()
    if extra is not None:
        X["extra"] = extra
    yy = d["y"].to_numpy() if y is None else y
    return walk_forward(d["year"].to_numpy(), TEST_YEARS,
                        lambda tr, te: LogisticRegression(C=0.3, max_iter=2000).fit(X[tr], yy[tr]).predict_proba(X[te])[:, 1],
                        first_train_year=2016)


def bet_stats(d: pd.DataFrame, back_a: np.ndarray, cluster=None) -> dict:
    """Bets at the bet365 open on the chosen side of every row of d."""
    o = np.where(back_a, d["oa_open"], d["ob_open"])
    pc = np.where(back_a, d["p_close"], 1 - d["p_close"])
    po = np.where(back_a, d["p_open"], 1 - d["p_open"])
    won = np.where(back_a, d["y"] == 1, d["y"] == 0)
    ok = np.isfinite(o) & np.isfinite(pc)
    o, pc, po, won = o[ok], pc[ok], po[ok], won[ok]
    cl = None if cluster is None else np.asarray(cluster)[ok]
    if len(o) == 0:
        return {"n": 0}
    clv = pc * o - 1
    pnl = np.where(won, o - 1, -1.0)
    r = lambda x, k=4: [round(v, k) for v in boot_mean(x, seed=SEED, cluster=cl)]
    return {"n": int(len(o)), "clv_roi": r(clv), "roi": r(pnl), "move_pts": [round(100 * v, 2) for v in boot_mean(pc - po, seed=SEED, cluster=cl)],
            "clv_hit": round(float((pc > po).mean()), 3), "mean_open_odds": round(float(o.mean()), 2)}


def main() -> int:
    joined_pkl, canon_pkl, hist_dir, events_csv, elev_csv, out_json = sys.argv[1:7]
    joined = pd.read_pickle(joined_pkl)
    joined = joined[joined["tour"].isin(["ATP", "WTA"]) & joined["odds_level"].isin(["ATP main", "WTA main", "Challenger"])].reset_index(drop=True)
    joined = joined.assign(match_key=np.arange(len(joined)), flip=coin_flip(len(joined), SEED))
    # blend inputs (same code as run_blend)
    hist = bl.history_table(Path(hist_dir))
    ev = pd.read_csv(events_csv)
    travel = trv.player_flags(joined, ev)[["match_key", "jet_east_1", "jet_west_1", "jet_east_2", "jet_west_2"]]
    b = bl.build(joined, hist, travel)[["match_key", "year", "level", "y"] + BLEND]
    ie = inc_extra(joined, hist)
    # scout inputs (same code as run_scout)
    canon = pd.read_pickle(canon_pkl)
    ck = canon[["tid", "round", "winner_name", "loser_name", "key", "minutes"]].drop_duplicates(["tid", "round", "winner_name", "loser_name"])
    jj = joined.merge(ck.rename(columns={"round": "wh_round", "key": "ckey", "minutes": "c_minutes"}), on=["tid", "wh_round", "winner_name", "loser_name"], how="left")
    el = pd.read_csv(elev_csv)
    evs = ev.assign(latitude=ev["latitude"].round(4), longitude=ev["longitude"].round(4)).merge(el, on=["latitude", "longitude"], how="left")
    evs.loc[evs["tournament"].str.contains("|".join(sc.ALT_OVERRIDE), case=False, na=False), "elev_m"] = 0.0
    elev = dict(zip(evs["tournament"], evs["elev_m"]))
    cf = sc.canon_match_flags(sc.player_table(canon, sc.history_attrs(Path(hist_dir))))
    s = sc.build(jj, cf, ck.set_index("key")["minutes"], elev)
    s = s[["match_key", "y", "name_a", "name_b"] + [f"d_{f}" for f in SCOUT + SCOUT_CONT]].rename(columns={f"d_{f}": f for f in SCOUT + SCOUT_CONT})
    df = b.merge(ie, on="match_key").merge(s, on="match_key", suffixes=("", "_s")).merge(prices(joined), on="match_key")
    orient_ok = bool((df["y"] == df["y_s"]).all())
    df = df[(df["year"] >= 2016) & df["p_open"].notna() & df["p_close"].notna()].reset_index(drop=True)
    cols = BLEND + INC_EXTRA + SCOUT + SCOUT_CONT

    res = {"manifest": provenance.manifest({"joined": joined_pkl, "canon": canon_pkl, "history": hist_dir, "events": events_csv, "elev": elev_csv},
                                           {"orientation": SEED, "bootstrap": SEED}, " ".join(["python"] + sys.argv)),
           "rows": int(len(df)), "by_level": df["level"].value_counts().to_dict(), "orientation agrees across builds": orient_ok,
           "median overround": {"bet365 open": round(float(np.median(1 / df["oa_open"] + 1 / df["ob_open"])), 4),
                                "bf close": round(float(np.median(1 / df["oa_close"] + 1 / df["ob_close"])), 4)}}
    y = df["y"].to_numpy()
    test = df["year"].isin(TEST_YEARS).to_numpy()
    early = (df["year"] < 2022).to_numpy()
    R = res["results"] = {}
    R["market benchmark, 2022-25 log loss"] = {"bet365 open": round(float(log_loss(y[test], df["p_open"][test]).mean()), 5),
                                              "bf close": round(float(log_loss(y[test], df["p_close"][test]).mean()), 5)}
    # ---- per flag
    F = R["per flag (move = close minus open on the flagged side, pts; money at bet365 open, 2022-25)"] = {}
    for f in BINARY:
        a_only, b_only = (df[f] >= 1).to_numpy(), (df[f] <= -1).to_numpy()
        sel = a_only | b_only
        who = np.where(a_only, df["name_a"], df["name_b"])
        mv = np.where(a_only, df["p_close"] - df["p_open"], df["p_open"] - df["p_close"])
        e = sel & early
        t = sel & test
        mv_e = [round(100 * v, 2) for v in boot_mean(mv[e], seed=SEED, cluster=who[e])] + [int(e.sum())]
        mv_t = [round(100 * v, 2) for v in boot_mean(mv[t], seed=SEED, cluster=who[t])] + [int(t.sum())]
        back_flagged = mv_e[0] > 0
        d = df[t]
        back_a = (d[f] >= 1).to_numpy() if back_flagged else (d[f] <= -1).to_numpy()
        F[f] = {"move 2016-21": mv_e, "move 2022-25": mv_t,
                "clv_hit 2022-25": round(float((mv[t] > 0).mean()), 3) if t.any() else None,
                "back": "flagged" if back_flagged else "other",
                "bets at bet365 open 2022-25": bet_stats(d, back_a, cluster=who[t])}
    for f in CONT:
        mv = (df["p_close"] - df["p_open"]).to_numpy()
        x = df[f].to_numpy()
        ok = np.isfinite(x) & (x != 0)
        out = {}
        for lab, m in (("2016-21", ok & early), ("2022-25", ok & test)):
            out[lab] = {"n": int(m.sum()), "slope_pts_per_unit": round(100 * float(np.polyfit(x[m], mv[m], 1)[0]), 3) if m.sum() > 10 else None}
        F[f] = out
    # ---- blend at the open
    p0, p1 = fit_predict(df, []), fit_predict(df, cols)
    m = test & np.isfinite(p1)
    R["PRIMARY blend at open: M1 minus M0 (against the open), 2022-25 log loss"] = [round(v, 5) for v in boot_mean(log_loss(y[m], p1[m]) - log_loss(y[m], p0[m]), seed=SEED)] + [int(m.sum())]
    R["blend at open M1 minus the CLOSE, 2022-25 log loss (negative = open + signals beats the close)"] = [round(v, 5) for v in boot_mean(log_loss(y[m], p1[m]) - log_loss(y[m], df["p_close"].to_numpy()[m]), seed=SEED)]
    R["open recalibrated M0 minus the CLOSE (how far behind the open starts)"] = [round(v, 5) for v in boot_mean(log_loss(y[m], p0[m]) - log_loss(y[m], df["p_close"].to_numpy()[m]), seed=SEED)]
    sub = df[m].reset_index(drop=True)
    pm, p0m = p1[m], p0[m]
    for lab, pp in (("blend", pm), ("open recalibrated only (control)", p0m)):
        for edge in (0.02, 0.03, 0.05):
            ea, eb = pp - 1 / sub["oa_open"], (1 - pp) - 1 / sub["ob_open"]
            side_a = (ea >= edge) & (ea >= eb)
            side_b = (eb >= edge) & (eb > ea)
            pick = (side_a | side_b).to_numpy()
            key = f"{'PRIMARY ' if (edge == 0.03 and lab == 'blend') else ''}{lab}: edge >= {int(100 * edge)} pts at bet365 open, 2022-25"
            R[key] = bet_stats(sub[pick].reset_index(drop=True), side_a.to_numpy()[pick])
        for lv in ("ATP main", "WTA main", "Challenger"):
            ea, eb = pp - 1 / sub["oa_open"], (1 - pp) - 1 / sub["ob_open"]
            side_a = (ea >= 0.03) & (ea >= eb)
            pick = ((side_a | ((eb >= 0.03) & (eb > ea))) & (sub["level"] == lv)).to_numpy()
            if lab == "blend":
                R[f"blend edge >= 3 at bet365 open, {lv}"] = bet_stats(sub[pick].reset_index(drop=True), side_a.to_numpy()[pick])
    from sklearn.linear_model import LogisticRegression
    tr = early & (df["year"] >= 2016).to_numpy()
    X = np.column_stack([logit(df["p_open"].to_numpy())] + [df[c].to_numpy() for c in cols])
    lr = LogisticRegression(C=0.3, max_iter=2000).fit(X[tr], y[tr])
    R["blend-at-open weights fitted on 2016-21"] = dict(zip(["open"] + cols, [round(float(v), 4) for v in lr.coef_[0]]))
    # ---- checks
    C = {}
    raw = joined[joined["tour"] == "WTA"]
    C["swap_source (prices)"] = checks.swap_source(lambda r, f: prices(r.assign(flip=f)), raw, swap_source, raw["flip"].to_numpy(bool),
                                                   ["p_open", "p_close", "oa_open", "ob_open"])
    p_mkt = df["p_open"].to_numpy()

    def run(yy, z):
        a0, a1 = fit_predict(df, [], y=yy), fit_predict(df, cols, y=yy, extra=z)
        mm = test & np.isfinite(a1)
        return {"delta": boot_mean(log_loss(yy[mm], a1[mm]) - log_loss(yy[mm], a0[mm]), seed=SEED)}
    C["planted_edge"] = checks.planted_edge(run, p_mkt, size=0.15, seed=SEED)
    C["market_null"] = checks.market_null(run, p_mkt, seed=SEED + 1)
    C["known_answers"] = checks.known_answers(y[test], df["p_close"].to_numpy()[test], (0.55, 0.66))
    C["orientation agrees across builds"] = {"pass": orient_ok}
    res["checks"] = C
    res["checks_passed"] = all(c["pass"] for c in C.values())
    Path(out_json).write_text(json.dumps(res, indent=1, default=str) + "\n")
    print(json.dumps({k: v for k, v in res.items() if k != "manifest"}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
