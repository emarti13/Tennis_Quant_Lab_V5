"""Travel and body clock: does the price miss jet lag and playing in the middle of a player's night?

Usage:  python research_tests/travel/run_travel.py JOINED_PKL EVENTS_CSV OUT_JSON

JOINED_PKL  the Kaggle odds join (2014-2025; match start times in UTC+9 from tennisexplorer; Betfair, bet365)
EVENTS_CSV  geocode_events.py output: tournament -> latitude, longitude, time zone

Pre-registered 2026-11-03, before any result was seen. Fatigue tests used match minutes; these use the
clock. For each player, the previous match in the odds data that started before this one (real start
times: no ordering leak), its location's UTC offset at that date, and this match's.

  jet_east    moved 5+ hours east since the previous match, which was 5 days ago or less
  jet_west    moved 5+ hours west, same window
  body_night  this match starts between 00:00 and 07:00 on the clock of the player's previous location,
              previous match 5 days ago or less (playing in the body's night)
  night       this match starts at 21:00 or later local time
Flags are A's minus B's (night is the same for both, so it enters as night x (A's jet lag - B's)).

  SET       ATP main, WTA main, Challenger; 2016-2025; walk-forward by year, test 2022-2025.
  PRIMARY   M0 = logistic on logit(Betfair close); M1 = M0 + jet_east, jet_west, body_night differences
            (L2): log loss M1 - M0 on 2022-2025, 95% range resampling matches.
  SECONDARY each flag: flagged player won minus Betfair close where one player has it, 2016-2025 and
            2016-2021; money (Betfair close after 2% commission, bet365 close) on 2022-2025 for any flag
            whose 2016-21 residual is beyond 2 points.
  CHECKS    swap-source; planted edge; market null; known answers.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research_kit import checks, provenance  # noqa: E402
from research_kit.core import boot_mean, coin_flip, devig, log_loss, logit, orient, walk_forward  # noqa: E402

SEED = 20261103
TEST_YEARS = range(2022, 2026)
FLAGS = ["jet_east", "jet_west", "body_night"]
BOOKS = {"bf_close": ("bf_w", "bf_l"), "b365_close": ("b365_w", "b365_l")}
COMMISSION = {"bf_close": 0.02, "b365_close": 0.0}


def utc_offset(tz: str, t: pd.Timestamp) -> float:
    try:
        return ZoneInfo(tz).utcoffset(t.to_pydatetime().replace(tzinfo=None)).total_seconds() / 3600
    except Exception:
        return np.nan


def player_flags(j: pd.DataFrame, ev: pd.DataFrame) -> pd.DataFrame:
    """Per match (match_key) and side (1 = source winner, 2 = loser): travel flags from the previous match."""
    tz = dict(zip(ev["tournament"], ev["timezone"]))
    j = j.copy()
    j["utc"] = pd.to_datetime(j["match_date_formatted"], errors="coerce") - pd.Timedelta(hours=9)
    j["tz"] = j["tournament"].map(tz)
    j = j.dropna(subset=["utc", "tz"])
    off = {}
    for (z, d) in set(zip(j["tz"], j["utc"].dt.date)):
        off[(z, d)] = utc_offset(z, pd.Timestamp(d) + pd.Timedelta(hours=12))
    j["off"] = [off[(z, d)] for z, d in zip(j["tz"], j["utc"].dt.date)]
    j["local_hour"] = (j["utc"].dt.hour + j["utc"].dt.minute / 60 + j["off"]) % 24
    rows = pd.concat([pd.DataFrame({"match_key": j["match_key"], "side": s, "player": j[c], "utc": j["utc"], "off": j["off"]})
                      for s, c in ((1, "winner_name"), (2, "loser_name"))], ignore_index=True)
    rows = rows.sort_values(["player", "utc", "match_key"])
    g = rows.groupby("player")
    rows["prev_utc"], rows["prev_off"] = g["utc"].shift(1), g["off"].shift(1)
    days = (rows["utc"] - rows["prev_utc"]).dt.total_seconds() / 86400
    shift = rows["off"] - rows["prev_off"]
    recent = days.between(0.01, 5)
    rows["jet_east"] = (recent & (shift >= 5)).astype(int)
    rows["jet_west"] = (recent & (shift <= -5)).astype(int)
    body_hour = (rows["utc"].dt.hour + rows["utc"].dt.minute / 60 + rows["prev_off"]) % 24
    rows["body_night"] = (recent & (body_hour < 7) & (shift.abs() >= 3)).astype(int)
    out = rows.pivot_table(index="match_key", columns="side", values=FLAGS, aggfunc="first")
    out.columns = [f"{f}_{s}" for f, s in out.columns]
    out = out.join(j.set_index("match_key")[["local_hour"]])
    return out.reset_index()


def build(joined: pd.DataFrame, fl: pd.DataFrame) -> pd.DataFrame:
    j = joined.merge(fl, on="match_key", how="inner").sort_values("match_key", kind="stable")
    flip = j["flip"].to_numpy(bool)
    out = pd.DataFrame({"match_key": j["match_key"].values, "year": pd.to_datetime(j["wh_date"]).dt.year.values,
                        "level": j["odds_level"].values, "y": (~flip).astype(int), "night": (j["local_hour"] >= 21).astype(int).values})
    for f in FLAGS:
        a, b = orient(j[f"{f}_1"].to_numpy(), j[f"{f}_2"].to_numpy(), flip)
        out[f"d_{f}"] = a - b
    out["d_night_x_jet"] = out["night"] * (out["d_jet_east"] + out["d_jet_west"])
    for book, (c1, c2) in BOOKS.items():
        oa, ob = orient(pd.to_numeric(j[c1], errors="coerce"), pd.to_numeric(j[c2], errors="coerce"), flip)
        out[f"p_{book}"] = devig(oa, ob)
        out[f"oa_{book}"], out[f"ob_{book}"] = oa, ob
    return out


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


def flag_report(df, f, test, R):
    y = df["y"].to_numpy()
    early = (df["year"] < 2022).to_numpy()
    a_only, b_only = (df[f"d_{f}"] == 1).to_numpy(), (df[f"d_{f}"] == -1).to_numpy()
    resid = np.where(a_only, y - df["p_bf_close"], np.where(b_only, (1 - y) - (1 - df["p_bf_close"]), np.nan))
    ra, re = resid[np.isfinite(resid)], resid[np.isfinite(resid) & early]
    key = f"{f}: flagged player won minus Betfair close (pts)"
    R[key] = {"all": [round(100 * v, 2) for v in boot_mean(ra, seed=SEED)] + [int(len(ra))],
              "2016-21": [round(100 * v, 2) for v in boot_mean(re, seed=SEED)] + [int(len(re))]}
    e = R[key]["2016-21"]
    if len(re) and abs(e[0]) >= 2:
        back_flagged = e[0] > 0
        for book in BOOKS:
            x = df[test & (a_only | b_only) & df[f"p_{book}"].notna().to_numpy()]
            a_flag = (x[f"d_{f}"] == 1).to_numpy()
            back_a = a_flag if back_flagged else ~a_flag
            o = np.where(back_a, x[f"oa_{book}"], x[f"ob_{book}"])
            won = np.where(back_a, x["y"] == 1, x["y"] == 0)
            pnl = np.where(won, (o - 1) * (1 - COMMISSION[book]), -1.0)
            m, lo, hi = boot_mean(pnl, seed=SEED)
            R[f"MONEY {f}: back the {'flagged' if back_flagged else 'other'} player at {book}, 2022-25"] = {"n": int(len(x)), "roi": round(m, 4), "range": [round(lo, 4), round(hi, 4)]}


def main() -> int:
    joined_pkl, events_csv, out_json = sys.argv[1], sys.argv[2], sys.argv[3]
    joined = pd.read_pickle(joined_pkl)
    joined = joined[joined["tour"].isin(["ATP", "WTA"]) & joined["odds_level"].isin(["ATP main", "WTA main", "Challenger"])].reset_index(drop=True)
    joined = joined.assign(match_key=np.arange(len(joined)), flip=coin_flip(len(joined), SEED))
    ev = pd.read_csv(events_csv)
    fl = player_flags(joined, ev)
    df = build(joined, fl)
    df = df[(df["year"] >= 2016) & df["p_bf_close"].notna()].reset_index(drop=True)
    res = {"manifest": provenance.manifest({"joined": joined_pkl, "events": events_csv}, {"orientation": SEED, "bootstrap": SEED}, " ".join(["python"] + sys.argv)),
           "rows": int(len(df)), "flag_rates": {f: round(float((df[f"d_{f}"] != 0).mean()), 4) for f in FLAGS}, "results": {}}
    R = res["results"]
    y = df["y"].to_numpy()
    test = df["year"].isin(TEST_YEARS).to_numpy()
    cols = [f"d_{f}" for f in FLAGS]
    p0, p1 = fit_predict(df, []), fit_predict(df, cols)
    m = test & np.isfinite(p1)
    R["PRIMARY M1 (travel flags) minus M0, Betfair close, 2022-25 log loss"] = [round(v, 5) for v in boot_mean(log_loss(y[m], p1[m]) - log_loss(y[m], p0[m]), seed=SEED)] + [int(m.sum())]
    for f in FLAGS:
        flag_report(df, f, test, R)
    df["d_night_jet"] = df["d_night_x_jet"].clip(-1, 1)
    FLAGS_X = FLAGS + ["night_jet"]
    flag_report(df, "night_jet", test, R)
    C = {}
    raw = joined[joined["tour"] == "WTA"]
    # flags are recomputed from the relabelled table itself (side 1 is whoever the source lists first)
    C["swap_source"] = checks.swap_source(lambda r, f: build(r.assign(flip=f), player_flags(r, ev)), raw, swap_source,
                                          raw["flip"].to_numpy(bool), cols + ["p_bf_close", "oa_bf_close", "ob_bf_close"])
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
    res["flags_reported"] = FLAGS_X
    Path(out_json).write_text(json.dumps(res, indent=1, default=str) + "\n")
    print(json.dumps({k: v for k, v in res.items() if k != "manifest"}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
