"""Does serving get worse the longer the set goes? Hold rate and double faults by game number in the set,
against the server's own level in the match (Match Charting Project).

Usage:  python research_tests/pressure/run_set_length.py MCP_DIR OUT_JSON

Written 2026-11-19, before any result. User's hypothesis: "the longer the set goes, the more pressure
builds and the more serving errors occur". Exploratory (historical data before 2026-11-01).

  GAMES     every service game (tie-breaks excluded), with its number in the set: n = games already
            played in the set + 1. Stages: 1-4, 5-8, 9-10, 11-12 (5-5 and 6-5 / 5-6).
  HOLD      deviation = held - expected; expected = P(win a game | the server's share of serve points
            won in the match, leaving out this game) (research_kit.inplay.p_game).
  DF        a double fault = first and second serve both faults (serve code, after any lets "c", is a
            direction digit or none followed only by fault letters n w d x g e !). Rate per service
            point; deviation = rate in the stage - the same server's rate in the rest of the match.
  PRIMARY   per tour: hold deviation in games 11-12 minus games 1-4, and double-fault deviation in
            games 11-12 minus games 1-4; 95% ranges resampling whole matches (2,000, seed 20261119).
  ALSO      every stage; the same split by set number (first set / later sets) to separate set length
            from match length (fatigue).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research_kit.inplay import p_game  # noqa: E402

SEED, BOOT = 20261119, 2000
FAULT = re.compile(r"c*[0456]?[nwdxge!]+")
STAGES = [(1, 4, "games 1-4"), (5, 8, "games 5-8"), (9, 10, "games 9-10"), (11, 12, "games 11-12")]


def is_fault(s) -> bool:
    return isinstance(s, str) and bool(FAULT.fullmatch(s.strip()))


def load(mcp: Path, tour: str) -> pd.DataFrame:
    p = pd.concat([pd.read_csv(f, low_memory=False, usecols=["match_id", "Pt", "Set1", "Set2", "Gm1", "Gm2", "Svr", "1st", "2nd", "PtWinner"])
                   for f in sorted(mcp.glob(f"charting-{tour}-points-*.csv"))], ignore_index=True)
    for c in ("Pt", "Set1", "Set2", "Gm1", "Gm2", "Svr", "PtWinner"):
        p[c] = pd.to_numeric(p[c], errors="coerce")
    p = p.dropna(subset=["Pt", "Set1", "Set2", "Gm1", "Gm2", "Svr", "PtWinner"])
    p = p[p["Svr"].isin([1, 2]) & p["PtWinner"].isin([1, 2])].astype({c: int for c in ("Pt", "Set1", "Set2", "Gm1", "Gm2", "Svr", "PtWinner")})
    p = p[~((p["Gm1"] == 6) & (p["Gm2"] == 6))].sort_values(["match_id", "Pt"], kind="stable")
    p["sw"] = (p["PtWinner"] == p["Svr"]).astype(int)
    p["df"] = (p["1st"].map(is_fault) & p["2nd"].map(is_fault)).astype(int)
    return p


def table(p: pd.DataFrame) -> pd.DataFrame:
    key = ["match_id", "Set1", "Set2", "Gm1", "Gm2"]
    g = p.groupby(key, sort=False).agg(server=("Svr", "first"), nsrv=("Svr", "nunique"), winner=("PtWinner", "last"),
                                        pts=("Pt", "size"), sw=("sw", "sum"), df=("df", "sum")).reset_index()
    g = g[g["nsrv"] == 1].copy()
    g["n"] = g["Gm1"] + g["Gm2"] + 1
    g["held"] = (g["winner"] == g["server"]).astype(int)
    tot = g.groupby(["match_id", "server"])[["sw", "pts", "df"]].transform("sum")
    rest_pts = tot["pts"] - g["pts"]
    g = g[rest_pts >= 20].copy()
    rest_pts = rest_pts.loc[g.index]
    p_rest = ((tot["sw"] - g["sw"]).loc[g.index] / rest_pts).clip(0.05, 0.95)
    g["expected"] = [p_game(float(x)) for x in p_rest]
    g["hold_dev"] = g["held"] - g["expected"]
    g["df_rate"] = g["df"] / g["pts"]
    g["df_dev"] = g["df_rate"] - (tot["df"] - g["df"]).loc[g.index] / rest_pts
    g["stage"] = None
    for lo, hi, name in STAGES:
        g.loc[g["n"].between(lo, hi), "stage"] = name
    g["first_set"] = (g["Set1"] + g["Set2"]) == 0
    return g.dropna(subset=["stage"])


def boot_diff(a: pd.DataFrame, b: pd.DataFrame, col: str, seed=SEED) -> list:
    ids = pd.Index(sorted(set(a["match_id"]) | set(b["match_id"])))
    def per(x):
        s = x.groupby("match_id")[col].agg(["sum", "count"]).reindex(ids, fill_value=0)
        return s["sum"].to_numpy(float), s["count"].to_numpy(float)
    sa, ca = per(a)
    sb, cb = per(b)
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(BOOT):
        i = rng.integers(0, len(ids), len(ids))
        vals.append(sa[i].sum() / ca[i].sum() - sb[i].sum() / cb[i].sum())
    lo, hi = np.percentile(vals, [2.5, 97.5])
    return [round(100 * float(a[col].mean() - b[col].mean()), 3), round(100 * float(lo), 3), round(100 * float(hi), 3)]


def main() -> int:
    mcp, outp = Path(sys.argv[1]), Path(sys.argv[2])
    res = {}
    for t, name in (("w", "WTA"), ("m", "ATP")):
        g = table(load(mcp, t))
        R = res[name] = {"matches": int(g["match_id"].nunique()), "service_games": int(len(g)), "stages": {}}
        for _, _, st in STAGES:
            x = g[g["stage"] == st]
            R["stages"][st] = {"games": int(len(x)), "held": round(float(x["held"].mean()), 4), "expected": round(float(x["expected"].mean()), 4),
                               "hold_dev_pts": round(100 * float(x["hold_dev"].mean()), 2),
                               "df_per_100_serve_points": round(100 * float(x["df"].sum() / x["pts"].sum()), 3),
                               "df_dev_per_100_points": round(100 * float(x["df_dev"].mean()), 3)}
        late, early = g[g["stage"] == "games 11-12"], g[g["stage"] == "games 1-4"]
        R["PRIMARY hold deviation, games 11-12 minus games 1-4 (pts)"] = boot_diff(late, early, "hold_dev")
        R["PRIMARY double-fault deviation, games 11-12 minus games 1-4 (per 100 serve points)"] = boot_diff(late, early, "df_dev")
        R["games 9-10 minus games 1-4, hold (pts)"] = boot_diff(g[g["stage"] == "games 9-10"], early, "hold_dev")
        for fs, lab in ((True, "first set"), (False, "later sets")):
            gg = g[g["first_set"] == fs]
            R[f"{lab}: hold deviation, games 11-12 minus games 1-4 (pts)"] = boot_diff(gg[gg["stage"] == "games 11-12"], gg[gg["stage"] == "games 1-4"], "hold_dev")
    outp.write_text(json.dumps(res, indent=1) + "\n")
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
