"""Point table from the Match Charting Project (Tennis Abstract), linked to our leak-free Elo.

Source: github.com/JeffSackmann/tennis_MatchChartingProject, CC BY-NC-SA 4.0 (attribution
required, non-commercial). The raw data is NOT copied into this repository; set MCP_DIR to a
local clone. Output (scratch, not committed): points.pkl, one row per point, player 1's view:
  match_id, tour, date, best_of, final_rule, surface, p_elo (P1 wins, pre-match production
  Elo), sa, sb, ga, gb, p1_srv, i, j (server's points first; in a tiebreak P1's then P2's),
  tb_first_p1 (P1 served the tiebreak's first point), p1_won_point, y (P1 won the match).

Checks (research_tests/qa.py): each match's score sequence must follow from the point winners
(a point changes only the expected counters); a match is kept only if fewer than 1% of its
points break that rule and it ends with someone reaching the needed sets (no retirements).
Elo link: our match whose two player names (surname + first initial, accents stripped) and
event date (within 16 days) agree; one candidate only. Elo is the production-parameter
`v5_baseline_elo.run` probability, computed before the match is played.
"""
from __future__ import annotations

import os
import sys
import unicodedata

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "research_tests"))
sys.path.insert(0, os.path.join(ROOT, "research_tests", "first_server"))
from fs_core import final_set_rule  # noqa: E402
from qa import QA  # noqa: E402

MCP = os.environ.get("MCP_DIR", "/home/user/jeffsackmann/tennis_matchchartingproject")
SCRATCH = os.environ.get("FS_SCRATCH", "/tmp/claude-0/-home-user-Tennis-Quant-Lab-V5/a0609b44-84ba-59ef-a5f1-f66b68d375ec/scratchpad")
SLAMS = {"australian open": "Australian Open", "roland garros": "Roland Garros", "wimbledon": "Wimbledon", "us open": "US Open"}
EXCLUDE = ("davis cup", "laver cup", "nextgen", "next gen", "juniors", "olympics", "billie jean", "fed cup",
           "united cup", "atp cup", "hopman", "exhibition", "utr", "ultimate tennis")
GAME_PTS = {"0": 0, "15": 1, "30": 2, "40": 3, "AD": 4}


def name_key(name: str) -> str:
    s = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode().lower().replace("-", " ").replace(".", " ")
    parts = [p for p in s.split() if p]
    if not parts:
        return ""
    return f"{parts[-1]}_{parts[0][0]}"


def parse_pts(s: str, tb: bool):
    a, b = str(s).split("-")
    if tb:
        return int(a), int(b)
    return GAME_PTS[a], GAME_PTS[b]


def load_matches() -> pd.DataFrame:
    out = []
    for t, tour in (("m", "MEN"), ("w", "WTA")):
        m = pd.read_csv(os.path.join(MCP, f"charting-{t}-matches.csv"), encoding="latin1", dtype=str)
        m["tour"] = tour
        out.append(m)
    m = pd.concat(out, ignore_index=True)
    m["date"] = pd.to_datetime(m["Date"], format="%Y%m%d", errors="coerce")
    m["best_of"] = pd.to_numeric(m["Best of"], errors="coerce")
    tn = m["Tournament"].astype(str).str.lower()
    m["slam"] = tn.isin(SLAMS)
    m = m[m.date.notna() & m.best_of.isin([3, 5]) & ~tn.str.contains("|".join(EXCLUDE))].copy()
    m["final_rule"] = [final_set_rule("G" if s else "x", t, d.year, b) for s, t, d, b in zip(m.slam, m.Tournament, m.date, m.best_of)]
    m = m[m.final_rule.isin(["tb7", "tb10", "adv"])]
    m["k1"], m["k2"] = m["Player 1"].map(name_key), m["Player 2"].map(name_key)
    return m


def link_elo(m: pd.DataFrame, elo: pd.DataFrame) -> pd.Series:
    """P(player 1 wins) from our Elo, by names and date; NaN when not exactly one candidate."""
    elo = elo.copy()
    elo["kw"], elo["kl"] = elo.winner_name.map(name_key), elo.loser_name.map(name_key)
    elo["pair"] = [tuple(sorted(x)) for x in zip(elo.kw, elo.kl)]
    by_pair = {p: g for p, g in elo.groupby("pair")}
    out = {}
    for mid, k1, k2, d in zip(m.match_id, m.k1, m.k2, m.date):
        g = by_pair.get(tuple(sorted((k1, k2))))
        if g is None:
            continue
        g = g[(g.date >= d - pd.Timedelta(days=16)) & (g.date <= d + pd.Timedelta(days=2))]
        if len(g) != 1:
            continue
        r = g.iloc[0]
        out[mid] = (r.p_winner if r.kw == k1 else 1 - r.p_winner, min(r.n_winner, r.n_loser), r.key)
    return out


def build_points(m: pd.DataFrame, qa: QA) -> pd.DataFrame:
    files = [f for f in os.listdir(MCP) if "-points-" in f]
    keep = set(m.match_id)
    pts = pd.concat([pd.read_csv(os.path.join(MCP, f), encoding="latin1", dtype=str,
                                 usecols=["match_id", "Pt", "Set1", "Set2", "Gm1", "Gm2", "Pts", "Svr", "PtWinner"])
                     for f in files], ignore_index=True)
    pts = pts[pts.match_id.isin(keep)].copy()
    pts["Pt"] = pd.to_numeric(pts.Pt, errors="coerce")
    pts = pts.dropna(subset=["Pt"]).sort_values(["match_id", "Pt"])
    meta = m.set_index("match_id")
    rows, bad_matches, n_checked = [], 0, 0
    for mid, g in pts.groupby("match_id", sort=False):
        need = int(meta.at[mid, "best_of"]) // 2 + 1
        rule = meta.at[mid, "final_rule"]
        try:
            sa, sb = g.Set1.astype(int).to_numpy(), g.Set2.astype(int).to_numpy()
            ga, gb = g.Gm1.astype(int).to_numpy(), g.Gm2.astype(int).to_numpy()
            srv = g.Svr.astype(int).to_numpy()
            win = g.PtWinner.astype(int).to_numpy()
        except ValueError:
            bad_matches += 1
            continue
        n = len(g)
        final = (sa == need - 1) & (sb == need - 1)
        tb = (ga == 6) & (gb == 6) & ~(final & (rule == "adv"))
        try:
            ij = [parse_pts(s, t) for s, t in zip(g.Pts, tb)]
        except (KeyError, ValueError):
            bad_matches += 1
            continue
        i_srv, j_ret = np.array([x[0] for x in ij]), np.array([x[1] for x in ij])
        # P1 / P2 points in the current game, then the transition check
        p1p = np.where(srv == 1, i_srv, j_ret)
        p2p = np.where(srv == 1, j_ret, i_srv)
        broken = 0
        for k in range(n - 1):
            same_game = (sa[k], sb[k], ga[k], gb[k]) == (sa[k + 1], sb[k + 1], ga[k + 1], gb[k + 1])
            if same_game:
                e1, e2 = p1p[k] + (win[k] == 1), p2p[k] + (win[k] == 2)
                if not tb[k] and e1 == 4 and e2 == 4:
                    e1 = e2 = 3                                # back to deuce
                if (p1p[k + 1], p2p[k + 1]) != (e1, e2):
                    broken += 1
            elif not (p1p[k + 1] == 0 and p2p[k + 1] == 0):
                broken += 1
        n_checked += 1
        # who won the match: the last point's winner must complete it
        last_w = win[-1]
        complete = (last_w == 1 and sa[-1] == need - 1) or (last_w == 2 and sb[-1] == need - 1)
        if broken > 0.01 * n or not complete or n < 40:
            bad_matches += 1
            continue
        y = float(last_w == 1)
        # tiebreak first server: server of the tiebreak's first point
        tb_first = np.zeros(n, bool)
        start = None
        for k in range(n):
            if tb[k]:
                if start is None or (sa[k], sb[k]) != (sa[start], sb[start]):
                    start = k
                tb_first[k] = srv[start] == 1
            else:
                start = None
        rows.append(pd.DataFrame({
            "match_id": mid, "pt": np.arange(n), "n_pts": n, "sa": sa, "sb": sb, "ga": ga, "gb": gb,
            "p1_srv": srv == 1, "tb": tb, "tb_first_p1": tb_first,
            # model convention: regular game server-first; tiebreak P1's points first
            "i": np.where(tb, p1p, i_srv), "j": np.where(tb, p2p, j_ret),
            "p1_won_point": win == 1, "y": y}))
    qa.check("share of charted matches passing the score-consistency check", 1 - bad_matches / max(1, n_checked + bad_matches), 0.85, 1.0)
    return pd.concat(rows, ignore_index=True)


def main():
    qa = QA("inplay_charting_points")
    m = load_matches()
    elo = pd.read_pickle(os.path.join(SCRATCH, "elo_all_matches.pkl"))
    links = link_elo(m, elo)
    m["p_elo"] = m.match_id.map(lambda x: links.get(x, (np.nan,))[0])
    m["n_min"] = m.match_id.map(lambda x: links.get(x, (np.nan, np.nan))[1])
    m["our_key"] = m.match_id.map(lambda x: links.get(x, (None, None, None))[2])
    m2010 = m[m.date >= "2011-01-01"]
    qa.check("share of charted matches since 2011 linked to our Elo", m2010.p_elo.notna().mean(), 0.6, 1.0)
    m = m2010[m2010.p_elo.notna()].copy()
    P = build_points(m, qa)
    P = P.merge(m[["match_id", "tour", "date", "best_of", "final_rule", "Surface", "p_elo", "n_min", "our_key"]], on="match_id")
    qa.count("matches", P.match_id.nunique())
    qa.count("points", len(P))
    qa.check("P1 match win share", P.groupby("match_id").y.first().mean(), 0.40, 0.70)
    qa.check("server wins point share", (P.p1_won_point == P.p1_srv).mean(), 0.55, 0.68)
    # Elo should agree with the charted result about as well as it does in general
    first = P.groupby("match_id").first()
    ll = -(first.y * np.log(first.p_elo) + (1 - first.y) * np.log(1 - first.p_elo)).mean()
    qa.check("Elo log loss on the linked matches", ll, 0.50, 0.68)
    qa.save(HERE)
    P.to_pickle(os.path.join(SCRATCH, "inplay_points.pkl"))
    print("matches", P.match_id.nunique(), "points", len(P))


if __name__ == "__main__":
    main()
