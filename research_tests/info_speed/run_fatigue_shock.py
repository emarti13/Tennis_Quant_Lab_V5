"""Fatigue shocks: does the price fully account for a player coming off a much longer match?

Usage:  python research_tests/info_speed/run_fatigue_shock.py MATCHES_PKL JOINED_PKL OUT_JSON

MATCHES_PKL  warehouse matches with minutes, round, tid, winner_key/loser_key, retired/walkover
JOINED_PKL   the Kaggle odds join (research_tests/kaggle_join): bet365 / Betfair / best open
             and close, 2014-2025; the first player is always the winner.

Pre-registered 2026-10-31, before any result was seen. This test fits no model: it asks whether
the market's own price is right on a specific kind of match.

  SET       ATP and WTA main and Challenger matches with odds, 2014-2025, both players with a
            previous match in the same event (rounds ordered; same event only, so the
            information was public before this match), minutes known for both, neither
            previous match a walkover or retirement. Round-robin events are left out (no order).
  SHOCK     minutes gap = tired player's previous match minutes - fresh player's.
  PRIMARY   gap >= 45 minutes. Residual = mean(tired won - tired's de-vigged Betfair closing
            probability), 95% range by match. A negative range means the close overrates the
            tired player (the market does not fully price fatigue). Betting the fresh player at
            Betfair close with 2% commission is the money version.
  SECONDARY gap >= 30 / 60 / 90; main tours vs Challenger; best of 5; bet365 open and close;
            the open-to-close move (does the price move against the tired player before the
            start, i.e. does the market react, and how much is left at the close?).
  CHECKS    swap-source (inputs independent of which side the source listed first);
            time-travel (a previous match is from an earlier round of the same event);
            planted shift (draw results from the close with the tired player 3 points worse:
            the test must find about -0.03); market null (results drawn from the close: about 0);
            known answers (Betfair close log loss in range).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research_kit import checks, provenance  # noqa: E402
from research_kit.core import boot_mean, coin_flip, devig, orient  # noqa: E402

SEED = 20261031
RANK = {"Q1": 0, "Q2": 1, "Q3": 2, "R128": 3, "R64": 4, "R32": 5, "R16": 6, "QF": 7, "SF": 8, "F": 9}
BOOKS = {"bf_close": ("bf_w", "bf_l"), "b365_close": ("b365_w", "b365_l"), "b365_open": ("b365_w_opening", "b365_l_opening"),
         "best_close": ("best_w", "best_l")}
COMMISSION = {"bf_close": 0.02, "b365_close": 0.0, "b365_open": 0.0, "best_close": 0.0}


def previous_matches(m: pd.DataFrame) -> pd.DataFrame:
    """Each player's previous match in the same event (latest earlier round): minutes, whether it
    ended early. One row per (tid, round rank, player)."""
    m = m[m["round"].isin(RANK)].copy()
    m["rk"] = m["round"].map(RANK)
    early = m["retired"].fillna(False).astype(bool) | m["walkover"].fillna(False).astype(bool)
    rows = pd.concat([pd.DataFrame({"tid": m["tid"], "rk": m["rk"], "pk": m[k], "minutes": m["minutes"], "early": early})
                      for k in ("winner_key", "loser_key")])
    # a player listed twice in one round of one event (duplicate rows, lucky losers) makes
    # "previous match" ambiguous: that player's whole event is left out (found by the checks)
    dup = rows.duplicated(["tid", "rk", "pk"], keep=False)
    bad = set(map(tuple, rows.loc[dup, ["tid", "pk"]].drop_duplicates().to_numpy()))
    rows = rows[~pd.Series(list(zip(rows["tid"], rows["pk"])), index=rows.index).isin(bad)]
    rows = rows.sort_values(["tid", "pk", "rk"])
    g = rows.groupby(["tid", "pk"])
    rows["prev_minutes"] = g["minutes"].shift(1)
    rows["prev_early"] = g["early"].shift(1).astype(float)
    rows["prev_rk"] = g["rk"].shift(1)
    return rows[["tid", "rk", "pk", "prev_minutes", "prev_early", "prev_rk"]]


def build(joined: pd.DataFrame, prev: pd.DataFrame) -> pd.DataFrame:
    """One oriented row per match (joined["flip"]: True = the source's second player is A)."""
    j = joined[joined["wh_round"].isin(RANK)].copy()
    j["rk"] = j["wh_round"].map(RANK)
    for side, k in (("1", "winner_key"), ("2", "loser_key")):
        p = prev.rename(columns={"pk": k, "prev_minutes": f"pm{side}", "prev_early": f"pe{side}", "prev_rk": f"pr{side}"})
        j = j.merge(p, on=["tid", "rk", k], how="left")
    j = j.sort_values("match_key", kind="stable")
    flip = j["flip"].to_numpy(bool)
    out = pd.DataFrame({"match_key": j["match_key"].values, "year": pd.to_datetime(j["wh_date"]).dt.year.values,
                        "level": j["odds_level"].values, "tour": j["tour"].values, "bo": j["match_format"].values,
                        "rk": j["rk"].values, "y": (~flip).astype(int)})
    for c in ("pm", "pe", "pr"):
        out[f"a_{c}"], out[f"b_{c}"] = orient(j[f"{c}1"], j[f"{c}2"], flip)
    for book, (c1, c2) in BOOKS.items():
        oa, ob = orient(pd.to_numeric(j[c1], errors="coerce"), pd.to_numeric(j[c2], errors="coerce"), flip)
        out[f"p_{book}"] = devig(oa, ob)
        out[f"oa_{book}"], out[f"ob_{book}"] = oa, ob
    return out


def swap_source(joined: pd.DataFrame) -> pd.DataFrame:
    j = joined.copy()
    for a, b in [("winner_key", "loser_key"), *BOOKS.values()]:
        j[a], j[b] = joined[b].values, joined[a].values
    return j


def shock_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Re-express each eligible match from the tired player's side."""
    ok = (df["a_pm"].notna() & df["b_pm"].notna() & (df["a_pe"] == 0) & (df["b_pe"] == 0)
          & df["level"].isin(["ATP main", "WTA main", "Challenger"]))
    d = df[ok].copy()
    a_tired = d["a_pm"] >= d["b_pm"]
    t = pd.DataFrame({"match_key": d["match_key"], "year": d["year"], "level": d["level"], "bo": d["bo"],
                      "gap": np.abs(d["a_pm"] - d["b_pm"]), "tired_won": np.where(a_tired, d["y"], 1 - d["y"])})
    for book in BOOKS:
        t[f"p_{book}"] = np.where(a_tired, d[f"p_{book}"], 1 - d[f"p_{book}"])     # analysis only, not a model input
        t[f"odds_fresh_{book}"] = np.where(a_tired, d[f"ob_{book}"], d[f"oa_{book}"])
    return t.reset_index(drop=True)


def residual(t: pd.DataFrame, book: str, y=None) -> list:
    m = t[f"p_{book}"].notna().to_numpy()
    yy = (t["tired_won"].to_numpy() if y is None else y)[m]
    return [round(v, 4) for v in boot_mean(yy - t[f"p_{book}"].to_numpy()[m], seed=SEED)] + [int(m.sum())]


def fresh_bets(t: pd.DataFrame, book: str) -> dict:
    o = t[f"odds_fresh_{book}"].to_numpy(float)
    m = np.isfinite(o) & (o > 1)
    won = (t["tired_won"].to_numpy() == 0)[m]
    pnl = np.where(won, (o[m] - 1) * (1 - COMMISSION[book]), -1.0)
    mean, lo, hi = boot_mean(pnl, seed=SEED)
    return {"n": int(m.sum()), "roi": round(mean, 4), "range": [round(lo, 4), round(hi, 4)]}


def main() -> int:
    matches_pkl, joined_pkl, out_json = sys.argv[1:4]
    m = pd.read_pickle(matches_pkl)
    joined = pd.read_pickle(joined_pkl)
    joined = joined[joined["tour"].isin(["ATP", "WTA"])].reset_index(drop=True)
    joined = joined.assign(match_key=np.arange(len(joined)), flip=coin_flip(len(joined), SEED))
    prev = previous_matches(m)
    df = build(joined, prev)
    t = shock_frame(df)
    res = {"manifest": provenance.manifest({"matches": matches_pkl, "joined": joined_pkl}, {"orientation": SEED, "bootstrap": SEED},
                                          " ".join(["python"] + sys.argv)),
           "eligible_matches": len(t), "results": {}}
    R = res["results"]
    P = t["gap"] >= 45
    R["PRIMARY gap>=45, Betfair close: residual (tired won - close prob) [mean, lo, hi, n]"] = residual(t[P], "bf_close")
    R["PRIMARY money: back the fresh player at Betfair close, 2% commission"] = fresh_bets(t[P], "bf_close")
    for g in (30, 60, 90):
        R[f"gap>={g}, Betfair close residual"] = residual(t[t["gap"] >= g], "bf_close")
    for lv in ("ATP main", "WTA main", "Challenger"):
        R[f"gap>=45, {lv}, Betfair close residual"] = residual(t[P & (t["level"] == lv)], "bf_close")
        R[f"gap>=45, {lv}, back fresh at Betfair close"] = fresh_bets(t[P & (t["level"] == lv)], "bf_close")
    R["gap>=45, best of 5, Betfair close residual"] = residual(t[P & (t["bo"] == 5)], "bf_close")
    for book in ("b365_open", "b365_close", "best_close"):
        R[f"gap>=45, {book} residual"] = residual(t[P], book)
        R[f"gap>=45, back fresh at {book}"] = fresh_bets(t[P], book)
    mv = (t["p_b365_close"] - t["p_b365_open"])[P].dropna()
    R["gap>=45, bet365 open->close move of the tired player's prob (pts) [mean, lo, hi]"] = [round(100 * v, 3) for v in boot_mean(mv.to_numpy(), seed=SEED)]
    R["control gap<10 (similar previous match), Betfair close residual"] = residual(t[t["gap"] < 10], "bf_close")
    # residual by gap decile, for the picture
    t["gap_bin"] = pd.cut(t["gap"], [0, 15, 30, 45, 60, 90, 600], right=False)
    R["by gap, Betfair close"] = {str(k): residual(g, "bf_close") for k, g in t.groupby("gap_bin", observed=True)}

    # ---------------------------------------------------------------- checks
    C = {}
    raw = joined[joined["tour"] == "WTA"]
    cols = ["a_pm", "b_pm", "a_pe", "b_pe", "p_bf_close", "p_b365_open", "oa_bf_close", "ob_bf_close"]
    C["swap_source"] = checks.swap_source(lambda r, f: build(r.assign(flip=f), prev), raw, swap_source, raw["flip"].to_numpy(bool), cols)
    # time travel: a previous match must come from an earlier round of the same event
    later = sum(int((df[f"{s}_pr"].notna() & (df[f"{s}_pr"] >= df["rk"])).sum()) for s in ("a", "b"))
    dup = int(prev.duplicated(["tid", "rk", "pk"]).sum())
    C["time_travel"] = {"pass": later == 0 and dup == 0, "previous_not_earlier": later, "duplicate_player_rounds": dup,
                        "rule": "the previous match is from an earlier round of the same event (merge on tid)"}
    pc = t.loc[P, "p_bf_close"].dropna()
    g = np.random.default_rng(SEED)
    p_true = np.clip(pc.to_numpy() - 0.03, 0.001, 0.999)
    y_pl = (g.random(len(pc)) < p_true).astype(int)
    found = boot_mean(y_pl - pc.to_numpy(), seed=SEED)
    C["planted_shift"] = {"pass": bool(found[2] < 0 and abs(found[0] + 0.03) < 0.015), "planted": -0.03, "found": [round(v, 4) for v in found]}
    y_null = (g.random(len(pc)) < pc.to_numpy()).astype(int)
    found0 = boot_mean(y_null - pc.to_numpy(), seed=SEED)
    C["market_null"] = {"pass": bool(found0[1] < 0 < found0[2]), "found": [round(v, 4) for v in found0]}
    allm = df[df["p_bf_close"].notna() & df["level"].isin(["ATP main", "WTA main", "Challenger"])]
    C["known_answers"] = checks.known_answers(allm["y"].to_numpy(), allm["p_bf_close"].to_numpy(), (0.56, 0.66))
    res["checks"] = C
    res["checks_passed"] = all(c["pass"] for c in C.values())
    prim = R["PRIMARY money: back the fresh player at Betfair close, 2% commission"]
    res["alarms"] = checks.alarms((0, 0, 0), prim["roi"] if prim["n"] >= 100 else None)
    Path(out_json).write_text(json.dumps(res, indent=1, default=str) + "\n")
    print(json.dumps({k: res[k] for k in ("eligible_matches", "results", "checks", "checks_passed", "alarms")}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
