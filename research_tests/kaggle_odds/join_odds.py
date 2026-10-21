"""Step 1: join the Kaggle odds files (alimoh89/tennis-results-and-betting-odds-20142025,
tennis-data.co.uk layout) to our match table.

NOT YET RUN on the real files: the environment's network policy refuses api.kaggle.com, so the
dataset could not be downloaded. The loader detects the schema rather than assuming it and
stops with a clear message when a needed column is missing.

Usage: python -I research_tests/kaggle_odds/join_odds.py <dir with the extracted files> <out.pkl>

Join rule: same tour, both players' "surname + first initial" keys (the files write
"Nadal R.", "Auger-Aliassime F."), and the odds-file date inside the event window
(tourney_date - 3 days .. tourney_date + 20 days). A pair that meets twice in one window is
dropped (ambiguous), never guessed. Winner-first files: the result is in the file's own column
order, so orientation comes from our key hash, never from the file.
"""
from __future__ import annotations

import glob
import os
import re
import sys
import unicodedata

import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, ROOT)

ODDS_PAIRS = ["PS", "B365", "Max", "Avg", "EX", "LB", "SJ", "CB", "GB", "IW", "SB", "UB", "BF"]


def _ascii(s):
    return unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()


def name_key(name):
    """'Rafael Nadal' / 'Nadal R.' / 'Nadal, Rafael' -> 'nadal r'; None when unusable."""
    if not isinstance(name, str) or not name.strip():
        return None
    s = _ascii(name).replace(",", " ").strip()
    toks = [t for t in re.split(r"\s+", s) if t]
    if len(toks) >= 2 and re.fullmatch(r"([a-z]\.)+|[a-z]", toks[-1]):      # "nadal r." / "de minaur a."
        surname = " ".join(toks[:-1])
        init = toks[-1][0]
    elif "," in name:
        surname, init = toks[0], toks[1][0]
    else:                                                                   # "rafael nadal"
        surname, init = " ".join(toks[1:]), toks[0][0]
    surname = re.sub(r"[^a-z]", "", surname)
    return f"{surname} {init}" if surname else None


def read_any(path):
    if path.lower().endswith((".xlsx", ".xls")):
        return pd.read_excel(path)
    return pd.read_csv(path, low_memory=False, encoding_errors="replace")


def load_odds(folder):
    frames = []
    for p in sorted(glob.glob(os.path.join(folder, "**", "*"), recursive=True)):
        if not p.lower().endswith((".csv", ".xlsx", ".xls")):
            continue
        d = read_any(p)
        d.columns = [str(c).strip() for c in d.columns]
        if not {"Winner", "Loser", "Date"} <= set(d.columns):
            print("skip (no Winner/Loser/Date):", os.path.basename(p))
            continue
        low = os.path.basename(p).lower()
        d["tour"] = "WTA" if ("wta" in low or "WTA" in d.columns and "ATP" not in d.columns) else "MEN"
        d["src_file"] = os.path.basename(p)
        frames.append(d)
    if not frames:
        raise SystemExit(f"no odds files with Winner/Loser/Date columns under {folder}")
    o = pd.concat(frames, ignore_index=True)
    o["odate"] = pd.to_datetime(o["Date"], errors="coerce", dayfirst=False)
    o["wk"], o["lk"] = o["Winner"].map(name_key), o["Loser"].map(name_key)
    found = [b for b in ODDS_PAIRS if f"{b}W" in o and f"{b}L" in o]
    print("odds columns found:", found, "| other columns:", [c for c in o.columns if c not in
                                                             {f"{b}{s}" for b in found for s in "WL"}][:40])
    for b in found:
        for s in "WL":
            o[f"{b}{s}"] = pd.to_numeric(o[f"{b}{s}"], errors="coerce")
    extra = [c for c in o.columns if re.search(r"(over|under|total|handicap|hcp|spread|ou_)", c, re.I)]
    print("possible totals / handicap columns:", extra or "none")
    return o, found, extra


def main(folder, out):
    import v5_baseline_elo as be
    o, books, extra = load_odds(folder)
    m = be.load_matches(ROOT)
    m["wk"], m["lk"] = m["winner_name"].map(name_key), m["loser_name"].map(name_key)
    m["pair"] = [frozenset((a, b)) for a, b in zip(m.wk, m.lk)]
    o["pair"] = [frozenset((a, b)) for a, b in zip(o.wk, o.lk)]
    idx = {}
    for i, (tour, pr) in enumerate(zip(m.tour, m.pair)):
        idx.setdefault((tour, pr), []).append(i)
    hits = []
    for j, r in enumerate(o.itertuples()):
        c = idx.get((r.tour, r.pair), [])
        c = [i for i in c if pd.notna(r.odate) and pd.Timedelta(days=-3) <= r.odate - m.date.iat[i] <= pd.Timedelta(days=20)]
        if len(c) == 1:
            hits.append((j, c[0]))
    jj = pd.DataFrame(hits, columns=["oi", "mi"]).drop_duplicates("mi", keep=False)
    res = pd.concat([o.iloc[jj.oi].reset_index(drop=True).drop(columns=["pair"]),
                     m.iloc[jj.mi][["key", "tour", "tid", "date", "winner_key", "loser_key", "score"]]
                     .rename(columns={"tour": "m_tour"}).reset_index(drop=True)], axis=1)
    # sanity: the odds file's winner must be our winner
    res["winner_agrees"] = res["wk"] == m.set_index("key").loc[res.key, "wk"].values
    print(f"odds rows {len(o)}, joined {len(res)} ({100 * len(res) / max(len(o), 1):.1f}%), "
          f"winner agrees {100 * res.winner_agrees.mean():.2f}%")
    print(res.groupby([res.odate.dt.year, "tour"]).size().unstack().fillna(0).astype(int))
    res.to_pickle(out)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    main(sys.argv[1], sys.argv[2])
