"""Compatriots: when both players share a nationality (often friends, training partners, Davis Cup team-mates),
does the market favourite underperform its price?

Usage:  python research_tests/tells/run_compatriots.py JOINED_PKL HISTORY_DIR OUT_JSON

Pre-registered 2026-11-03, before any result was seen. Nationality (IOC code) from the history file at
the match. The effect, if any, is symmetric in the players, so the test is on the favourite's side.

  SET       ATP main, WTA main, Challenger with odds, 2016-2025.
  PRIMARY   favourite (by Betfair close) won minus its closing chance, compatriot matches against all
            others, 2016-2025; 95% range resampling matches.
  SECONDARY 2016-2021 and 2022-2025 separately; by level; money on 2022-2025 if the 2016-21 compatriot
            residual is beyond 2 points: back the underdog (if favourites underperform) at Betfair close
            (2% commission) and bet365 close.
  CHECKS    planted shift (favourites made 3 points worse in compatriot matches: found); market null.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research_kit import provenance  # noqa: E402
from research_kit.core import boot_mean, devig  # noqa: E402

SEED = 20261103


def main() -> int:
    joined_pkl, hist_dir, out_json = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
    j = pd.read_pickle(joined_pkl)
    j = j[j["tour"].isin(["ATP", "WTA"]) & j["odds_level"].isin(["ATP main", "WTA main", "Challenger"])].copy()
    h = pd.concat([pd.read_csv(hist_dir / f, low_memory=False) for f in ("ATP.csv", "WTA.csv", "Challenger.csv")], ignore_index=True)
    h = h[["tourney_id", "round", "winner_name", "loser_name", "winner_ioc", "loser_ioc"]].drop_duplicates(["tourney_id", "round", "winner_name", "loser_name"])
    j = j.merge(h, left_on=["tid", "wh_round", "winner_name", "loser_name"], right_on=["tourney_id", "round", "winner_name", "loser_name"], how="inner")
    j["year"] = pd.to_datetime(j["wh_date"]).dt.year
    j = j[j["year"] >= 2016]
    # the winner's closing chance, then the favourite's view (symmetric: no orientation needed)
    pw = devig(pd.to_numeric(j["bf_w"], errors="coerce"), pd.to_numeric(j["bf_l"], errors="coerce"))
    j["p_fav"] = np.maximum(pw, 1 - pw)
    j["fav_won"] = (pw >= 0.5).astype(int)
    j["comp"] = (j["winner_ioc"] == j["loser_ioc"]) & j["winner_ioc"].notna()
    j = j[np.isfinite(j["p_fav"])].reset_index(drop=True)
    r = (j["fav_won"] - j["p_fav"]).to_numpy()
    comp = j["comp"].to_numpy()
    res = {"manifest": provenance.manifest({"joined": joined_pkl, "history": str(hist_dir)}, {"bootstrap": SEED}, " ".join(["python"] + sys.argv)),
           "rows": int(len(j)), "compatriot_share": round(float(comp.mean()), 4), "results": {}}
    R = res["results"]
    f = lambda x: [round(100 * v, 2) for v in boot_mean(x, seed=SEED)] + [int(len(x))]  # noqa: E731
    R["PRIMARY favourite won minus close (pts): compatriot matches"] = f(r[comp])
    R["favourite won minus close (pts): other matches"] = f(r[~comp])
    R["difference compatriot minus other (pts)"] = round(100 * float(r[comp].mean() - r[~comp].mean()), 2)
    for lab, m in (("2016-21", j["year"] < 2022), ("2022-25", j["year"] >= 2022)):
        R[f"{lab}: compatriot / other"] = [f(r[comp & m.to_numpy()]), f(r[~comp & m.to_numpy()])]
    for lv, g in j.groupby("odds_level"):
        R[f"by level {lv}: compatriot"] = f((g["fav_won"] - g["p_fav"]).to_numpy()[g["comp"].to_numpy()])
    e = R["2016-21: compatriot / other"][0][0]
    if abs(e) >= 2:
        x = j[(j["year"] >= 2022) & j["comp"]]
        for book, (cw, cl) in {"bf_close": ("bf_w", "bf_l"), "b365_close": ("b365_w", "b365_l")}.items():
            ow, ol = pd.to_numeric(x[cw], errors="coerce").to_numpy(), pd.to_numeric(x[cl], errors="coerce").to_numpy()
            fav_is_w = devig(ow, ol) >= 0.5
            back_dog = e < 0
            o = np.where(fav_is_w == back_dog, ol, ow)                 # backing the underdog: the loser's odds when the favourite is the winner
            won = np.where(back_dog, x["fav_won"] == 0, x["fav_won"] == 1)
            ok = np.isfinite(o) & (o > 1)
            pnl = np.where(won, (o - 1) * (1 - 0.0), -1.0)[ok]
            mm, lo, hi = boot_mean(pnl, seed=SEED)
            R[f"MONEY compatriot matches: back the {'underdog' if back_dog else 'favourite'} at {book}, 2022-25"] = {"n": int(ok.sum()), "roi": round(mm, 4), "range": [round(lo, 4), round(hi, 4)]}
    g = np.random.default_rng(SEED)
    p = j["p_fav"].to_numpy()
    y_pl = (g.random(len(p)) < np.where(comp, p - 0.03, p)).astype(int)
    pl = boot_mean((y_pl - p)[comp], seed=SEED)
    y0 = (g.random(len(p)) < p).astype(int)
    n0 = boot_mean((y0 - p)[comp], seed=SEED)
    res["checks"] = {"planted_shift": {"pass": bool(pl[2] < 0 and abs(pl[0] + 0.03) < 0.015), "found": [round(100 * v, 2) for v in pl]},
                     "market_null": {"pass": bool(n0[1] < 0 < n0[2]), "found": [round(100 * v, 2) for v in n0]}}
    res["checks_passed"] = all(c["pass"] for c in res["checks"].values())
    Path(out_json).write_text(json.dumps(res, indent=1, default=str) + "\n")
    print(json.dumps({k: v for k, v in res.items() if k != "manifest"}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
