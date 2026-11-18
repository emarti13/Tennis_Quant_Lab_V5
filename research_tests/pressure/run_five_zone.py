"""From 5 games to the end of the set: what happens after a failed serve-out, against what both players'
serve predicts, and how far a fair match price moves when it happens (Match Charting Project).

Usage:  python research_tests/pressure/run_five_zone.py MCP_DIR OUT_JSON

Written 2026-11-18, before any result. The user disputed "a failed serve-out moves the match price
only a few points" and asked for every set to be reviewed from the first time either player reaches
5 games to the end of the set: break back, solid hold, broken again, runs of games. Exploratory
(historical data before 2026-11-01).

  SETS      every set of every charted match with its games in order (server, game winner, score
            before the game) and the set winner (the next set's set count, or the last point of the
            match). Tie-break sets: the tie-break counts as the last "game", won by the set winner.
  ZONE      from the first game played with a player on 5 games to the end of the set.
  SERVE-OUT the server serving for the set (5-x with x <= 4, or 6-5), broken = FAILED.
            After a failed serve-out (score now s-(r+1), the breaker serving next):
            - next game: breaker holds ("solid hold") or is broken ("break right back");
            - the broken server still wins the set (yes / no);
            - games won in a row by the breaker starting with the break;
            - breaks of the original server after this one, in the same set.
  EXPECTED  each player's share of serve points won in the match (all service games, tie-breaks out),
            through research_kit.inplay: the breaker's hold chance next game, and the chance the broken
            server still wins the set from the new score (points independent).
  PRICE     fair match-win chance of the original server just before the failed serve-out game and
            just after the break (research_kit.inplay.p_match, both players' match serve rates, the
            real set and game score, best of 3 or 5, final-set tie-break to 10 at best of 5 from 2022 on
            and to 7 otherwise), so the drop a fair price must show, by set (first / middle / deciding)
            and by serving for the set or for the match.
  REPORT    per tour: counts and shares with 95% ranges resampling matches; actual minus expected.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research_kit import inplay as ip  # noqa: E402

SEED, BOOT = 20261118, 2000


def load(mcp: Path, tour: str) -> tuple[pd.DataFrame, pd.Series]:
    pts = pd.concat([pd.read_csv(f, low_memory=False, usecols=["match_id", "Pt", "Set1", "Set2", "Gm1", "Gm2", "Svr", "PtWinner"])
                     for f in sorted(mcp.glob(f"charting-{tour}-points-*.csv"))], ignore_index=True)
    for c in ("Pt", "Set1", "Set2", "Gm1", "Gm2", "Svr", "PtWinner"):
        pts[c] = pd.to_numeric(pts[c], errors="coerce")
    pts = pts.dropna().astype({c: int for c in ("Pt", "Set1", "Set2", "Gm1", "Gm2", "Svr", "PtWinner")})
    pts = pts[pts["Svr"].isin([1, 2]) & pts["PtWinner"].isin([1, 2])].sort_values(["match_id", "Pt"], kind="stable")
    mt = pd.read_csv(mcp / f"charting-{tour}-matches.csv", low_memory=False).drop_duplicates("match_id").set_index("match_id")
    bo = pd.to_numeric(mt["Best of"], errors="coerce")
    year = pd.to_numeric(mt["Date"].astype(str).str[:4], errors="coerce")
    return pts, pd.DataFrame({"best_of": bo, "year": year})


def ci(x: np.ndarray, cl: np.ndarray) -> list:
    x = np.asarray(x, float)
    if len(x) == 0:
        return [None, None, None]
    codes, uniq = pd.factorize(pd.Series(cl))
    s, c = np.bincount(codes, weights=x), np.bincount(codes).astype(float)
    g = np.random.default_rng(SEED)
    m = [s[i].sum() / c[i].sum() for i in (g.integers(0, len(uniq), len(uniq)) for _ in range(BOOT))]
    lo, hi = np.percentile(m, [2.5, 97.5])
    return [round(100 * float(x.mean()), 2), round(100 * float(lo), 2), round(100 * float(hi), 2)]


def analyse(pts: pd.DataFrame, meta: pd.DataFrame) -> dict:
    rows = []
    for mid, m in pts.groupby("match_id", sort=False):
        if mid not in meta.index or meta.loc[mid, "best_of"] not in (3, 5):
            continue
        bo = int(meta.loc[mid, "best_of"])
        ftb = 10 if (bo == 5 and meta.loc[mid, "year"] >= 2022) else 7
        stw = (bo + 1) // 2
        m = m.assign(sw=(m["PtWinner"] == m["Svr"]).astype(int))
        notb = m[~((m["Gm1"] == 6) & (m["Gm2"] == 6))]
        srv = {k: notb[notb["Svr"] == k]["sw"].agg(["sum", "count"]) for k in (1, 2)}
        if min(srv[1]["count"], srv[2]["count"]) < 30:
            continue
        p = {k: float(np.clip(srv[k]["sum"] / srv[k]["count"], 0.05, 0.95)) for k in (1, 2)}
        sets = list(m.groupby(["Set1", "Set2"], sort=False))
        for si, ((s1, s2), st) in enumerate(sets):
            if si + 1 < len(sets):
                n1, n2 = sets[si + 1][0]
                set_winner = 1 if n1 > s1 else 2
            else:
                set_winner = int(st["PtWinner"].iloc[-1])
            gms = st[~((st["Gm1"] == 6) & (st["Gm2"] == 6))].groupby(["Gm1", "Gm2"], sort=False).agg(
                server=("Svr", "first"), nsrv=("Svr", "nunique"), winner=("PtWinner", "last")).reset_index()
            if (gms["nsrv"] > 1).any():
                continue
            gl = list(gms.itertuples())
            deciding = s1 == s2 == stw - 1
            stage = "deciding set" if deciding else ("first set" if s1 == s2 == 0 else "middle set")
            for gi, g in enumerate(gl):
                s_ = g.Gm1 if g.server == 1 else g.Gm2
                r_ = g.Gm2 if g.server == 1 else g.Gm1
                sfs = (s_ == 5 and r_ <= 4) or (s_ == 6 and r_ == 5)
                if not sfs or g.winner == g.server:
                    continue
                srv_, brk = g.server, 3 - g.server
                server_sets = s1 if srv_ == 1 else s2
                for_match = server_sets == stw - 1
                nxt = gl[gi + 1] if gi + 1 < len(gl) else None
                run = 1
                for h in gl[gi + 1:]:
                    if h.winner == brk:
                        run += 1
                    else:
                        break
                more_breaks = sum(1 for h in gl[gi + 1:] if h.server == srv_ and h.winner != srv_)
                # expectations (points independent, both players' match serve rates)
                pa, pb = p[srv_], p[brk]                              # A = original server
                ga, gb = s_, r_ + 1                                   # score after the break, from A's side
                d = ip._set_dist(round(pa, 10), round(pb, 10), ga, gb, False, ftb if deciding else 7)
                exp_set = d[0] + d[1]
                exp_hold_next = ip.p_game(pb)
                sa, sb = (s1, s2) if srv_ == 1 else (s2, s1)
                before = ip.p_match(pa, pb, (sa, sb), (s_, r_), (0, 0), True, bo, ftb)
                after = ip.p_match(pa, pb, (sa, sb), (ga, gb), (0, 0), False, bo, ftb)
                rows.append({"match_id": mid, "stage": stage, "for_match": bool(for_match), "score": f"{s_}-{r_}",
                             "next_breaker_held": None if nxt is None else int(nxt.winner == brk),
                             "server_won_set": int(set_winner == srv_), "run": run, "more_breaks": more_breaks,
                             "exp_set": exp_set, "exp_hold_next": exp_hold_next, "price_before": before, "price_after": after})
    d = pd.DataFrame(rows)
    out = {"failed_serve_outs": int(len(d)), "matches": int(d["match_id"].nunique())}
    if d.empty:
        return out
    d["drop"] = d["price_before"] - d["price_after"]
    nx = d.dropna(subset=["next_breaker_held"])
    out["next game: breaker holds (solid hold) [actual %, range] / expected %"] = [ci(nx["next_breaker_held"], nx["match_id"]), round(100 * float(nx["exp_hold_next"].mean()), 2)]
    out["next game: break right back %"] = round(100 * float(1 - nx["next_breaker_held"].mean()), 2)
    out["broken server still wins the set [actual %, range] / expected %"] = [ci(d["server_won_set"], d["match_id"]), round(100 * float(d["exp_set"].mean()), 2)]
    out["actual minus expected, set won by broken server (pts)"] = ci(d["server_won_set"] - d["exp_set"], d["match_id"])
    out["server broken again later in the set %"] = round(100 * float((d["more_breaks"] > 0).mean()), 2)
    out["breaker's run of games from the break: share >= 2 / >= 3 / mean"] = [round(100 * float((d["run"] >= 2).mean()), 1), round(100 * float((d["run"] >= 3).mean()), 1), round(float(d["run"].mean()), 2)]
    out["fair match-price drop for the server (pts): median / quartiles / mean"] = {}
    for (stage, fm), g in d.groupby(["stage", "for_match"]):
        q = np.percentile(100 * g["drop"], [25, 50, 75])
        out["fair match-price drop for the server (pts): median / quartiles / mean"][f"{stage}{', serving for the match' if fm else ''}"] = {
            "n": int(len(g)), "median": round(float(q[1]), 1), "quartiles": [round(float(q[0]), 1), round(float(q[2]), 1)],
            "mean": round(float(100 * g["drop"].mean()), 1), "mean price before": round(float(100 * g["price_before"].mean()), 1),
            "mean price after": round(float(100 * g["price_after"].mean()), 1),
            "server still won the set %": round(100 * float(g["server_won_set"].mean()), 1)}
    return out


def main() -> int:
    mcp, outp = Path(sys.argv[1]), Path(sys.argv[2])
    res = {}
    for t, name in (("w", "WTA"), ("m", "ATP")):
        pts, meta = load(mcp, t)
        res[name] = analyse(pts, meta)
    outp.write_text(json.dumps(res, indent=1) + "\n")
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
