"""Step 1: join the Kaggle odds file (alimoh89/tennis-results-and-betting-odds-20142025,
tennis_matches_2014_2025.csv: an OddsPortal-style scrape) to our match table.

Facts about the file that matter (checked 2026-10-21):
- player_a is ALWAYS the match winner (100% of completed rows). Every a/b column is therefore
  re-oriented here by our stable key hash (v5_fatigue_features._p1_is_winner), never kept.
- No Pinnacle. Books: Bet365, Betfair, Ladbrokes, Unibet (closing and opening), best_odds
  (max over the scraped books). "Avg" is computed here over the books present.
- Handicap columns are NOT usable: line sign and prices are not consistently tied to one
  player (the best-fitting reading assigns the favourite's price to the winner's column,
  which leaks the result). Dropped.
- Totals (line, over, under) do not depend on orientation and are kept.
- About 58% of rows are ITF events: out of scope (CLAUDE.md), dropped.

Join: same tour, match date within tourney_date - 8 .. + 20 days (Challenger dates can be the Sunday after), winner and loser names
matched (last-name token plus first initial; token-set fallback). A Kaggle row with more than
one candidate, or a match claimed by two rows, is dropped (never guessed).

Usage: python research_tests/kaggle_odds/join_odds.py <tennis_matches_2014_2025.csv> <out.pkl>
"""
from __future__ import annotations

import os
import re
import sys
import unicodedata

import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, ROOT)

ML_BOOKS = ["bet365", "Betfair", "Ladbrokes", "Unibet"]
TOT_BOOKS = ["bet365", "Ladbrokes", "Unibet"]


def norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z ]", " ", s.replace("-", " "))


def toks(s) -> list[str]:
    return [t for t in norm(s).split() if t]


def name_keys(full, first=None, last=None) -> set[str]:
    """Keys 'lasttoken|initial' plus a sorted token-set key."""
    t = toks(full)
    if not t:
        return set()
    keys = {"set:" + " ".join(sorted(t))}
    if last is not None and isinstance(last, str) and toks(last):
        lt, fi = toks(last)[-1], (toks(first)[0][0] if isinstance(first, str) and toks(first) else "")
        keys.add(f"{lt}|{fi}")
    keys.add(f"{t[-1]}|{t[0][0]}")
    keys.add(f"{t[0]}|{t[-1][0]}")          # family-name-first spellings
    return keys


def load_kaggle(path):
    d = pd.read_csv(path, low_memory=False)
    d = d[~d.tournament.astype(str).str.contains("ITF")].copy()
    d["mdate"] = pd.to_datetime(d.match_date_formatted, errors="coerce")
    d["tour"] = np.where(d.tour == "WTA", "WTA", "MEN")
    return d.reset_index(drop=True)


def main(path, out):
    import v5_baseline_elo as be
    from v5_fatigue_features import _p1_is_winner
    k = load_kaggle(path)
    m = be.load_matches(ROOT)
    m = m[m.date >= "2013-12-01"].reset_index(drop=True)
    idx: dict[tuple, list[int]] = {}
    for i, (tour, wn, ln) in enumerate(zip(m.tour, m.winner_name, m.loser_name)):
        for kw in name_keys(wn):
            for kl in name_keys(ln):
                idx.setdefault((tour, kw, kl), []).append(i)
    hits = []
    mdate = m.date.to_numpy()
    for j, r in enumerate(k.itertuples()):
        if pd.isna(r.mdate):
            continue
        cand = set()
        for kw in name_keys(r.player_a, r.player_a_first_name, r.player_a_last_name):
            for kl in name_keys(r.player_b, r.player_b_first_name, r.player_b_last_name):
                cand.update(idx.get((r.tour, kw, kl), []))
        lo, hi = r.mdate - pd.Timedelta(days=20), r.mdate + pd.Timedelta(days=8)
        cand = [i for i in cand if lo <= mdate[i] <= hi]
        if len(cand) == 1:
            hits.append((j, cand[0]))
    h = pd.DataFrame(hits, columns=["kj", "mi"])
    h = h[~h.mi.duplicated(keep=False)]
    j = k.iloc[h.kj].reset_index(drop=True)
    mm = m.iloc[h.mi].reset_index(drop=True)
    out_df = pd.DataFrame({"key": mm.key, "tour": mm.tour, "tid": mm.tid, "level": mm.level, "date": mm.date,
                           "mdate": j.mdate, "k_tournament": j.tournament, "k_round": j["round"],
                           "completed": j.completed, "k_total_games": j.total_games, "k_comment": j.comment})
    # orientation: A = the side our key hash picks (not winner-first)
    a_is_w = np.array([_p1_is_winner(x) for x in mm.key])
    out_df["y"] = a_is_w.astype(int)
    for b in ML_BOOKS + ["best"]:
        for suf in ("", "_opening"):
            wa, wb = j[f"{b}_odds_a{suf}"].to_numpy(float), j[f"{b}_odds_b{suf}"].to_numpy(float)
            out_df[f"{b}{suf}_A"] = np.where(a_is_w, wa, wb)
            out_df[f"{b}{suf}_B"] = np.where(a_is_w, wb, wa)
    for b in TOT_BOOKS:
        out_df[f"{b}_tot_line"] = j[f"{b}_total_games_line"].to_numpy(float)
        out_df[f"{b}_over"] = j[f"{b}_odds_over"].to_numpy(float)
        out_df[f"{b}_under"] = j[f"{b}_odds_under"].to_numpy(float)
        if f"{b}_odds_over_opening" in j:
            out_df[f"{b}_over_opening"] = j[f"{b}_odds_over_opening"].to_numpy(float)
            out_df[f"{b}_under_opening"] = j[f"{b}_odds_under_opening"].to_numpy(float)
    # sanity: our winner must be the file's player_a (names already matched as winner/loser)
    n_k = len(k)
    print(f"non-ITF Kaggle rows {n_k}, joined {len(out_df)} ({100 * len(out_df) / n_k:.1f}%)")
    print(out_df.groupby([out_df.mdate.dt.year, "tour"]).size().unstack().fillna(0).astype(int).to_string())
    out_df.to_pickle(out)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    main(sys.argv[1], sys.argv[2])
