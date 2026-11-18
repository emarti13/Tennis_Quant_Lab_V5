"""Can players serve it out? Hold rates when serving for the set / match against what their own serve
predicts, women against men (Match Charting Project, point by point).

Usage:  python research_tests/pressure/run_serve_out.py MCP_DIR OUT_JSON

MCP_DIR   a clone of github.com/JeffSackmann/tennis_MatchChartingProject (CC BY-NC-SA 4.0; research use)

Written 2026-11-18, before any result. User's hypothesis: "women can't serve out when the pressure
rises". Exploratory (historical data, all before 2026-11-01).

  GAMES     every service game of every charted match (charting-{w,m}-points-*.csv), tie-breaks
            (6-6) excluded. Game winner = winner of its last point. Server's games s and receiver's
            games r before the game, from the server's side; server's sets and the match's best-of.
  STATES    serve_for_set   s = 5 and r <= 4, or s = 6 and r = 5 (winning the game wins the set);
                            serve_for_match is the subset where that set wins the match.
            leading         s > r and 3 <= s <= 4: ahead in the set, not yet serving for it
                            (CONTROL: the same "has been playing well" selection, less at stake).
            stay_in_set     r = 5 and s <= 4, or r = 6 and s = 5 (serving to stay in the set).
            five_all        s = r = 5.
            other           everything else.
  EXPECTED  the server's share of serve points won in that match, leaving out this game's points,
            p; expected hold = P(server wins a game | p) (research_kit.inplay.p_game, points
            independent). deviation = held - expected.
  PRIMARY   pressure effect = mean deviation (serve_for_set) - mean deviation (leading), per tour;
            and WOMEN minus MEN. 95% ranges resample whole matches (2,000 draws, seed 20261118).
            The hypothesis predicts a negative women's effect, below the men's.
  ALSO      raw hold rates per state; serve_for_match alone; stay_in_set and five_all.
  CAVEATS   charted matches lean toward top players and big events; the baseline comes from the same
            match, so player and court are controlled.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research_kit.inplay import p_game  # noqa: E402

SEED, BOOT = 20261118, 2000


def games_table(mcp: Path, tour: str) -> pd.DataFrame:
    pts = pd.concat([pd.read_csv(f, low_memory=False, usecols=["match_id", "Pt", "Set1", "Set2", "Gm1", "Gm2", "Svr", "PtWinner"])
                     for f in sorted(mcp.glob(f"charting-{tour}-points-*.csv"))], ignore_index=True)
    for c in ("Pt", "Set1", "Set2", "Gm1", "Gm2", "Svr", "PtWinner"):
        pts[c] = pd.to_numeric(pts[c], errors="coerce")
    pts = pts.dropna().astype({c: int for c in ("Pt", "Set1", "Set2", "Gm1", "Gm2", "Svr", "PtWinner")})
    pts = pts[pts["Svr"].isin([1, 2]) & pts["PtWinner"].isin([1, 2])]
    mt = pd.read_csv(mcp / f"charting-{tour}-matches.csv", low_memory=False)
    bo = pd.to_numeric(mt.drop_duplicates("match_id").set_index("match_id")["Best of"], errors="coerce")
    pts = pts.sort_values(["match_id", "Pt"], kind="stable")
    key = ["match_id", "Set1", "Set2", "Gm1", "Gm2"]
    g = pts.groupby(key, sort=False).agg(server=("Svr", "first"), n_srv=("Svr", "nunique"), winner=("PtWinner", "last"),
                                         pts=("Pt", "size"), srv_won=("PtWinner", lambda s: 0)).reset_index()
    # points won by the server in each game
    pts["srv_won_pt"] = (pts["PtWinner"] == pts["Svr"]).astype(int)
    g["srv_won"] = pts.groupby(key, sort=False)["srv_won_pt"].sum().to_numpy()
    g = g[(g["n_srv"] == 1) & ~((g["Gm1"] == 6) & (g["Gm2"] == 6))].copy()   # one server per game; no tie-breaks
    s1 = g["server"] == 1
    g["s"] = np.where(s1, g["Gm1"], g["Gm2"])
    g["r"] = np.where(s1, g["Gm2"], g["Gm1"])
    g["s_sets"] = np.where(s1, g["Set1"], g["Set2"])
    g["held"] = (g["winner"] == g["server"]).astype(int)
    g["best_of"] = g["match_id"].map(bo)
    g = g[g["best_of"].isin([3, 5])]
    stw = (g["best_of"] + 1) // 2
    # expected hold from the server's other service points in the match
    tot = g.groupby(["match_id", "server"])[["srv_won", "pts"]].transform("sum")
    p = (tot["srv_won"] - g["srv_won"]) / (tot["pts"] - g["pts"])
    g = g[(tot["pts"] - g["pts"]) >= 20].copy()
    p = p.loc[g.index].clip(0.05, 0.95)
    g["expected"] = [p_game(float(x)) for x in p]
    g["dev"] = g["held"] - g["expected"]
    sfs = ((g["s"] == 5) & (g["r"] <= 4)) | ((g["s"] == 6) & (g["r"] == 5))
    g["state"] = np.select([sfs, (g["s"] > g["r"]) & g["s"].between(3, 4), ((g["r"] == 5) & (g["s"] <= 4)) | ((g["r"] == 6) & (g["s"] == 5)),
                            (g["s"] == 5) & (g["r"] == 5)], ["serve_for_set", "leading", "stay_in_set", "five_all"], "other")
    g["for_match"] = sfs & (g["s_sets"] == stw.loc[g.index] - 1)
    g["tour"] = "WTA" if tour == "w" else "ATP"
    return g


def boot_diff(a: pd.DataFrame, b: pd.DataFrame | None, rng_seed=SEED) -> list:
    """mean(a.dev) - mean(b.dev) with whole-match resampling (b may be None)."""
    ids = pd.Index(sorted(set(a["match_id"]) | (set(b["match_id"]) if b is not None else set())))
    def per(x):
        s = x.groupby("match_id")["dev"].agg(["sum", "count"]).reindex(ids, fill_value=0)
        return s["sum"].to_numpy(float), s["count"].to_numpy(float)
    sa, ca = per(a)
    sb, cb = per(b) if b is not None else (np.zeros(len(ids)), np.zeros(len(ids)))
    g = np.random.default_rng(rng_seed)
    out = []
    for _ in range(BOOT):
        i = g.integers(0, len(ids), len(ids))
        ma = sa[i].sum() / max(ca[i].sum(), 1)
        mb = sb[i].sum() / max(cb[i].sum(), 1) if b is not None else 0.0
        out.append(ma - mb)
    point = a["dev"].mean() - (b["dev"].mean() if b is not None else 0.0)
    lo, hi = np.percentile(out, [2.5, 97.5])
    return [round(100 * float(point), 2), round(100 * float(lo), 2), round(100 * float(hi), 2)]


def main() -> int:
    mcp, out = Path(sys.argv[1]), Path(sys.argv[2])
    res = {"source": "Match Charting Project", "results": {}}
    tabs = {}
    for t in ("w", "m"):
        g = games_table(mcp, t)
        tour = g["tour"].iloc[0]
        tabs[tour] = g
        R = res["results"][tour] = {"matches": int(g["match_id"].nunique()), "service_games": int(len(g))}
        for st, x in g.groupby("state"):
            R[f"state {st}"] = {"games": int(len(x)), "held": round(float(x["held"].mean()), 4), "expected": round(float(x["expected"].mean()), 4),
                                "deviation_pts": boot_diff(x, None)}
        fm = g[g["for_match"]]
        R["serve_for_match"] = {"games": int(len(fm)), "held": round(float(fm["held"].mean()), 4), "expected": round(float(fm["expected"].mean()), 4),
                                "deviation_pts": boot_diff(fm, None)}
        R["PRIMARY pressure effect: serve_for_set minus leading (pts)"] = boot_diff(g[g["state"] == "serve_for_set"], g[g["state"] == "leading"])
        R["serve_for_match minus leading (pts)"] = boot_diff(fm, g[g["state"] == "leading"])
    # women minus men, resampling matches within each tour
    def eff(g, seed):
        a, b = g[g["state"] == "serve_for_set"], g[g["state"] == "leading"]
        ids = g["match_id"].unique()
        rng = np.random.default_rng(seed)
        sa = a.groupby("match_id")["dev"].agg(["sum", "count"]).reindex(ids, fill_value=0)
        sb = b.groupby("match_id")["dev"].agg(["sum", "count"]).reindex(ids, fill_value=0)
        vals = []
        for _ in range(BOOT):
            i = rng.integers(0, len(ids), len(ids))
            vals.append(sa["sum"].to_numpy()[i].sum() / sa["count"].to_numpy()[i].sum() - sb["sum"].to_numpy()[i].sum() / sb["count"].to_numpy()[i].sum())
        return np.array(vals), a["dev"].mean() - b["dev"].mean()
    vw, pw = eff(tabs["WTA"], SEED)
    vm, pm = eff(tabs["ATP"], SEED + 1)
    d = vw - vm
    res["results"]["PRIMARY women minus men, pressure effect (pts)"] = [round(100 * float(pw - pm), 2)] + [round(100 * float(v), 2) for v in np.percentile(d, [2.5, 97.5])]
    out.write_text(json.dumps(res, indent=1) + "\n")
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
