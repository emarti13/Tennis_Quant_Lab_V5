"""Do courts at the same event play at different speeds? Main court against the other courts, same event
and year, against the players' own levels (Match Charting Project).

Usage:  python research_tests/courts/run_court_speed.py MCP_DIR OUT_JSON

Written 2026-11-21, before any result. The user (2026-11-06, Fritz at the Paris Masters: "the main court
plays a lot quicker than Court 2"). Parked idea, now with data: the Match Charting Project names the court.
Exploratory (historical, all before 2026-11-01).

  MATCHES   charted matches with a court name, tie-break points included, retirements kept (per-point
            measures).
  MAIN      per event and year: the court whose name matches the event's main court (Centre, Center,
            Central, Centre Court, Court Central, Stadium, Stadium 1, Rod Laver Arena, Laver, Arthur Ashe
            Stadium, Ashe, Philippe Chatrier, Chatrier); if none matches, the court with most charted
            matches. OTHER = every other court at that event and year.
  MEASURES  per match: (a) rally length = shots per point after the serve (letters f b r s v z o p u y l m
            h i j k t q in the point's code), mean over points; (b) share of serve points won (both
            players); (c) aces per serve point.
  BASELINE  for each player, the mean of the measure over their OTHER charted matches on the same
            surface (at least 3); match baseline = mean of the two players' baselines; residual = match
            measure - baseline.
  PRIMARY   per event-year with at least one MAIN and one OTHER match: mean residual on MAIN minus mean
            residual on OTHER; averaged over event-years, 95% range resampling event-years (2,000, seed
            20261121), for rally length and for serve points won, men and women separately. The idea
            predicts shorter rallies and more serve points won on the main court.
  ALSO      aces; by surface; the same comparison for named courts with at least 30 charted matches
            against their event-years' other courts.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

SEED, BOOT = 20261121, 2000
MAIN_NAMES = {"centre", "center", "central", "centre court", "court central", "stadium", "stadium 1", "rod laver arena", "laver",
              "arthur ashe stadium", "ashe", "philippe chatrier", "chatrier", "court philippe chatrier"}
SHOT = re.compile(r"[fbrsvzopuylmhijktq]")


def rally(code) -> float | None:
    if not isinstance(code, str) or not code:
        return None
    body = code.lstrip("c")
    body = body[1:] if body[:1] in "0456" else body                 # serve direction
    return float(len(SHOT.findall(body)))


def per_match(mcp: Path, t: str) -> pd.DataFrame:
    pts = pd.concat([pd.read_csv(f, low_memory=False, usecols=["match_id", "Svr", "1st", "2nd", "PtWinner"])
                     for f in sorted(mcp.glob(f"charting-{t}-points-*.csv"))], ignore_index=True)
    pts["Svr"] = pd.to_numeric(pts["Svr"], errors="coerce")
    pts["PtWinner"] = pd.to_numeric(pts["PtWinner"], errors="coerce")
    pts = pts[pts["Svr"].isin([1, 2]) & pts["PtWinner"].isin([1, 2])]
    played = np.where(pts["2nd"].notna(), pts["2nd"], pts["1st"])
    pts["rally"] = [rally(x) for x in played]
    pts["srv_won"] = (pts["Svr"] == pts["PtWinner"]).astype(int)
    pts["ace"] = pd.Series(played).astype(str).str.contains(r"\*", regex=True).to_numpy().astype(int) & pts["srv_won"].to_numpy()
    g = pts.groupby("match_id").agg(rally=("rally", "mean"), srv_won=("srv_won", "mean"), ace=("ace", "mean"), points=("srv_won", "size"))
    mt = pd.read_csv(mcp / f"charting-{t}-matches.csv", low_memory=False).drop_duplicates("match_id").set_index("match_id")
    g = g.join(mt[["Player 1", "Player 2", "Tournament", "Date", "Court", "Surface"]], how="inner")
    g["court"] = g["Court"].astype(str).str.strip()
    g = g[~g["court"].isin(["", "nan", "NaN"]) & (g["points"] >= 40)].copy()
    g["year"] = g["Date"].astype(str).str[:4]
    g["event"] = g["Tournament"].astype(str) + " " + g["year"]
    return g.reset_index()


def add_baseline(g: pd.DataFrame, cols) -> pd.DataFrame:
    long = pd.concat([g[["match_id", "Surface"] + cols].assign(player=g["Player 1"]), g[["match_id", "Surface"] + cols].assign(player=g["Player 2"])])
    s = long.groupby(["player", "Surface"])[cols].transform("sum")
    n = long.groupby(["player", "Surface"])[cols[0]].transform("count")
    for c in cols:
        long[f"{c}_base"] = np.where(n - 1 >= 3, (s[c] - long[c]) / (n - 1), np.nan)
    b = long.groupby("match_id")[[f"{c}_base" for c in cols]].mean(numeric_only=True)
    g = g.join(b, on="match_id")
    for c in cols:
        g[f"{c}_res"] = g[c] - g[f"{c}_base"]
    return g


def main_flag(g: pd.DataFrame) -> pd.Series:
    flag = pd.Series(False, index=g.index)
    for ev, x in g.groupby("event"):
        names = x["court"].str.lower()
        hit = names.isin(MAIN_NAMES)
        if hit.any():
            flag.loc[x.index] = hit
        else:
            vc = names.dropna().value_counts()
            if len(vc):
                flag.loc[x.index] = names == vc.index[0]
    return flag


def paired(g: pd.DataFrame, col: str, mask_a: pd.Series, mask_b: pd.Series) -> list:
    rows = []
    for ev, x in g.groupby("event"):
        a, b = x.loc[mask_a.loc[x.index], col].dropna(), x.loc[mask_b.loc[x.index], col].dropna()
        if len(a) and len(b):
            rows.append(a.mean() - b.mean())
    v = np.array(rows)
    if len(v) == 0:
        return [None, None, None, 0]
    rng = np.random.default_rng(SEED)
    bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(BOOT)]
    lo, hi = np.percentile(bs, [2.5, 97.5])
    return [round(float(v.mean()), 4), round(float(lo), 4), round(float(hi), 4), int(len(v))]


def main() -> int:
    mcp, outp = Path(sys.argv[1]), Path(sys.argv[2])
    cols = ["rally", "srv_won", "ace"]
    res = {}
    for t, name in (("w", "WTA"), ("m", "ATP")):
        g = add_baseline(per_match(mcp, t), cols)
        g["main"] = main_flag(g)
        R = res[name] = {"matches_with_court": int(len(g)), "with_baseline": int(g["rally_res"].notna().sum()),
                         "main_court_matches": int(g["main"].sum())}
        R["PRIMARY rally length (shots per point), main minus other courts [mean, lo, hi, event-years]"] = paired(g, "rally_res", g["main"], ~g["main"])
        R["PRIMARY serve points won (share x 100), main minus other courts"] = [None if v is None else round(100 * v, 2) if i < 3 else v
                                                                                 for i, v in enumerate(paired(g, "srv_won_res", g["main"], ~g["main"]))]
        R["aces per 100 serve points, main minus other"] = [None if v is None else round(100 * v, 2) if i < 3 else v
                                                            for i, v in enumerate(paired(g, "ace_res", g["main"], ~g["main"]))]
        for sf, x in g.groupby("Surface"):
            if len(x) >= 300:
                R[f"rally length main minus other, {sf}"] = paired(x, "rally_res", x["main"], ~x["main"])
        named = {}
        for c, x in g.groupby(g["court"].str.lower()):
            if len(x) >= 30:
                evs = g["event"].isin(x["event"].unique())
                gg = g[evs]
                named[c] = paired(gg, "rally_res", gg["court"].str.lower() == c, gg["court"].str.lower() != c)
        R["rally length, named court minus other courts at its events (courts with 30+ matches)"] = named
    outp.write_text(json.dumps(res, indent=1, default=str) + "\n")
    print(json.dumps(res, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
