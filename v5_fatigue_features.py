#!/usr/bin/env python3
"""
v5_fatigue_features.py - leak-free fatigue / schedule / injury-proxy features for tennis
========================================================================================
FEATURE_VERSION = "fatigue_v1"

STATUS: RESEARCH CANDIDATE (PROJECT_MANDATE categories: Research + Model Profitability).
Not wired into any production workflow. It is a candidate replacement for the leaky same-date
ordering in v5_workload_features.py and may only feed production after it beats the Elo/baseline
model out of sample AND passes tests/test_v5_fatigue_features.py incl. the real-data parity tests.

One builder, two entry points, identical logic:
  build_training_table(matches)   -> one row per historical match (pre-match features)
  LiveFeatures(history).features(fixture) -> the same features for an upcoming fixture

WHY THIS FILE EXISTS (bugs it is designed to make impossible)
  1. Row-order leaks. The previous pipeline ordered same-date matches by a hashed match
     id, so a first-round row could "see" the same player's later rounds. Here nothing
     ever depends on row order: ordering uses only (event, stage, round) and week
     anchors, and every tie-break is a data key. Shuffling the input gives identical output.
  2. Mixed date meanings. TennisMyLife dates are tournament start dates in most files but
     per-match dates in 2026 ATP main draws and in the live "ongoing" feeds. No feature
     uses a raw date as a match day. Dates are only used to place EVENTS into tennis
     weeks, which is identical under both meanings.
  3. Same-round concurrency. Matches in the same event, stage and round are treated as
     simultaneous: none of them can see another.
  4. Silent defaults. Live lookups that fail (unknown player, ambiguous player, an event
     that cannot be resolved while the player has rows that week) RAISE instead of
     quietly producing zeros.

ORDERING RULES (what counts as "before" a target match)
  * Same event: rows whose (stage, round_rank) is strictly lower. Qualifying (stage 0)
    precedes main draw (stage 1). Unknown rounds are never "before" anything.
  * Other events: an event counts as prior if its last-stage anchor week is strictly
    earlier than the target's stage anchor week. Events in the same week are excluded
    (a safe loss of information, never a leak).
  * Tennis week of a date = Monday-based week of (date + 2 days), so Saturday/Sunday/
    Monday starts of the same tournament week land in the same week.

KNOWN LIMITATIONS (documented, not hidden)
  * TennisMyLife has no ITF and no WTA 125 results, so workload for players who play
    those events is undercounted. n_prior_matches helps the model see thin histories.
  * Week-level anchors cannot tell "played Sunday final, plays Tuesday" apart from
    "played Saturday final, plays Monday". Use OddsPapi clock times for that later,
    only after they exist for the whole training window (otherwise train/live skew).
"""
from __future__ import annotations

import glob
import hashlib
import math
import os
import re
import unicodedata
from bisect import bisect_left
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

FEATURE_VERSION = "fatigue_v1"

ROUND_RANK = {"Q1": 0, "Q2": 1, "Q3": 2, "Q4": 3,
              "R128": 10, "R64": 11, "R32": 12, "R16": 13, "RR": 13.5, "QF": 14,
              "SF": 15, "BR": 15.5, "3rd/4th": 15.5, "F": 16}
EPOCH_MONDAY = pd.Timestamp("1970-01-05")
MAX_MINUTES = 420

PLAYER_FEATURES = [
    # current event, strictly earlier rounds
    "ev_matches_before", "ev_quali_matches_before", "ev_sets_before", "ev_games_before",
    "ev_minutes_before", "prev_in_event_sets", "prev_in_event_games", "prev_in_event_minutes",
    "prev_in_event_went_distance",
    # earlier events
    "weeks_since_prev_event", "prev_event_matches", "prev_event_reached_final", "prev_event_won_title",
    "events_last_4w", "matches_last_4w", "matches_last_8w", "layoff_8w_plus",
    # injury proxies
    "retired_last_match", "retired_or_wo_last5",
    # history depth
    "n_prior_matches",
]
# Data-quality flags (NOT model features): weeks in the last 8 where TennisMyLife shows this player in
# more than one event - physically impossible, so dates/ids are wrong there and features are less reliable.
QC_FIELDS = ["qc_conflict_weeks_8w"]

MEN_FILES = ["historical_rating_aggregates/ATP.csv", "historical_rating_aggregates/ATPQualifiers.csv",
             "historical_rating_aggregates/Challenger.csv",
             "tennismylife_raw_current/20??.csv", "tennismylife_raw_current/20??_atp_quali.csv",
             "tennismylife_raw_current/20??_challenger.csv",
             "tennismylife_raw_current/ongoing_tourneys.csv",
             "tennismylife_raw_current/challenger_ongoing_tourneys.csv"]
WTA_FILES = ["historical_rating_aggregates/WTA.csv", "tennismylife_raw_current/20??_wta.csv",
             "tennismylife_raw_current/wta_ongoing_tourneys.csv"]


# ============================================================ helpers
def norm_name(n) -> str:
    """'Stefanini, Lucrezia' / 'Lucrezia Stéfanini' -> 'lucrezia stefanini'."""
    n = "" if n is None or (isinstance(n, float) and math.isnan(n)) else str(n)
    if "," in n:
        last, first = n.split(",", 1)
        n = f"{first} {last}"
    n = unicodedata.normalize("NFKD", n).encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z ]", " ", n).split())


def _day(ts) -> pd.Timestamp:
    ts = pd.Timestamp(ts)
    return (ts.tz_convert(None) if ts.tzinfo is not None else ts).normalize()


def tennis_week(ts) -> float:
    ts = pd.Timestamp(ts)
    if pd.isna(ts):
        return float("nan")
    if ts.tzinfo is not None:
        ts = ts.tz_convert(None)
    return float(((ts.normalize() + pd.Timedelta(days=2)) - EPOCH_MONDAY).days // 7)


def parse_score(score):
    """-> (walkover, retired, defaulted, sets, games)."""
    s = "" if score is None or (isinstance(score, float) and math.isnan(score)) else str(score)
    up = s.upper()
    walkover = bool(re.search(r"W/O|WALKOVER", up))
    retired = bool(re.search(r"\bRET", up))
    defaulted = bool(re.search(r"\bDEF", up))
    tokens = re.findall(r"(\d+)-(\d+)", re.sub(r"\(\d+\)", "", s))
    if walkover:
        return True, False, False, 0, 0
    if not tokens:
        return False, retired, defaulted, np.nan, np.nan
    return False, retired, defaulted, len(tokens), sum(int(a) + int(b) for a, b in tokens)


def stable_match_key(tour, tid, rnd, a, b) -> str:
    lo, hi = sorted([str(a), str(b)])
    return f"{tour}|{tid}|{rnd}|{lo}|{hi}"


def _p1_is_winner(match_key: str) -> bool:
    return int(hashlib.sha256(match_key.encode()).hexdigest()[:8], 16) % 2 == 0


# ============================================================ loading
def load_matches(data_dir: str | None = None, files: dict | None = None, report: dict | None = None) -> pd.DataFrame:
    """Load TennisMyLife files into one canonical match table.

    files: optional {"MEN": [paths], "WTA": [paths]}; default = the bundle layout under data_dir.
    """
    report = report if report is not None else {}
    if files is None:
        files = {"MEN": [], "WTA": []}
        for tour, pats in (("MEN", MEN_FILES), ("WTA", WTA_FILES)):
            for pat in pats:
                files[tour] += sorted(glob.glob(os.path.join(data_dir, pat)))
    frames = []
    for tour, paths in files.items():
        for priority, path in enumerate(paths):
            d = pd.read_csv(path, low_memory=False, dtype={"tourney_id": str, "winner_id": str, "loser_id": str})
            if d.empty:
                continue
            d["tour"] = tour
            d["source"] = os.path.basename(path)
            d["source_priority"] = priority
            frames.append(d)
    raw = pd.concat(frames, ignore_index=True, sort=False)
    report["raw_rows"] = len(raw)
    return canonicalize(raw, report)


REPO_HISTORY_FILES = {"MEN": ["ATP.csv", "ATPQualifiers.csv", "Challenger.csv"], "WTA": ["WTA.csv"]}
REPO_CURRENT_RESULTS = "v5_results_ready/tennismylife_results.csv"


def load_repo_matches(root: str = ".", report: dict | None = None) -> pd.DataFrame:
    """Load the SAME files production reads (no second copy of the data):
      .v5_history_cache/{ATP,ATPQualifiers,Challenger,WTA}.csv   (bootstrap_v5_history.py, 2010..last year)
      v5_results_ready/tennismylife_results.csv                    (canonical current-season results;
                                                                    tour taken from its result_file column)
    Current-season rows outrank history rows when the same match appears in both."""
    report = report if report is not None else {}
    frames = []
    for tour, names in REPO_HISTORY_FILES.items():
        for priority, name in enumerate(names):
            path = os.path.join(root, ".v5_history_cache", name)
            if not os.path.exists(path):
                raise FileNotFoundError(f"{path} missing - run bootstrap_v5_history.py first")
            d = pd.read_csv(path, low_memory=False, dtype={"tourney_id": str, "winner_id": str, "loser_id": str})
            frames.append(d.assign(tour=tour, source=name, source_priority=priority))
    cur_path = os.path.join(root, REPO_CURRENT_RESULTS)
    cur = pd.read_csv(cur_path, low_memory=False, dtype={"tourney_id": str, "winner_id": str, "loser_id": str})
    rf = cur["result_file"].astype(str).str.lower()
    cur = cur.assign(tour=np.where(rf.str.contains("wta"), "WTA", "MEN"), source=cur["result_file"].astype(str),
                     source_priority=10)
    frames.append(cur)
    raw = pd.concat(frames, ignore_index=True, sort=False)
    report["raw_rows"] = len(raw)
    return canonicalize(raw, report)


def canonicalize(raw: pd.DataFrame, report: dict | None = None) -> pd.DataFrame:
    report = report if report is not None else {}
    df = pd.DataFrame({
        "tour": raw["tour"].astype(str),
        "tid": raw["tourney_id"].astype(str),
        "tourney_name": raw.get("tourney_name"),
        "level": raw.get("tourney_level").astype(str) if "tourney_level" in raw else "",
        "surface": raw["surface"].astype("string") if "surface" in raw else pd.NA,
        "round": raw["round"].astype(str),
        "date": pd.to_datetime(raw["tourney_date"].astype(str).str[:8], format="%Y%m%d", errors="coerce"),
        "winner_id": raw["winner_id"].astype(str), "loser_id": raw["loser_id"].astype(str),
        "winner_name": raw["winner_name"], "loser_name": raw["loser_name"],
        "score": raw.get("score"), "best_of": pd.to_numeric(raw.get("best_of"), errors="coerce"),
        "minutes": pd.to_numeric(raw.get("minutes"), errors="coerce"),
        "winner_ioc": raw.get("winner_ioc"), "loser_ioc": raw.get("loser_ioc"),
        "winner_age": pd.to_numeric(raw.get("winner_age"), errors="coerce"),
        "loser_age": pd.to_numeric(raw.get("loser_age"), errors="coerce"),
        "source": raw.get("source", ""), "source_priority": raw.get("source_priority", 0),
    })
    missing = lambda s: s.isna() | s.astype("string").str.strip().isin(["nan", "", "None", "<NA>"]).fillna(True)
    bad = df["date"].isna() | missing(raw["winner_id"].reindex(df.index)) | missing(raw["loser_id"].reindex(df.index)) \
        | missing(raw["tourney_id"].reindex(df.index))
    report["dropped_missing_date_or_id"] = int(bad.sum())
    df = df[~bad].copy()
    # qualifying = Q1..Q4 only ("QF" also starts with Q - caught by unit test)
    df["stage"] = np.where(df["round"].str.upper().str.fullmatch(r"Q\d"), 0, 1)
    # stray duplicate player ids (same person, 1-5 rows under a second id) -> merge BEFORE de-duplication,
    # so a match filed twice under two ids collapses into one row
    mapping = _stray_id_map(df, report)
    df["winner_id"] = df["winner_id"].map(lambda x: mapping.get(x, x))
    df["loser_id"] = df["loser_id"].map(lambda x: mapping.get(x, x))
    df["rank"] = df["round"].map(ROUND_RANK).astype(float)
    report["unknown_round_rows"] = int(df["rank"].isna().sum())
    parsed = df["score"].map(parse_score)
    df["walkover"] = [p[0] for p in parsed]
    df["retired"] = [p[1] for p in parsed]
    df["sets"] = [p[3] for p in parsed]
    df["games"] = [p[4] for p in parsed]
    bad_min = (df["minutes"] <= 0) | (df["minutes"] > MAX_MINUTES)
    report["minutes_out_of_range_set_nan"] = int(bad_min.sum())
    df.loc[bad_min, "minutes"] = np.nan
    df.loc[df["walkover"], ["minutes", "sets", "games"]] = [0.0, 0, 0]
    # TennisMyLife re-uses tourney_ids (e.g. 2026-416 = Munich in April AND Rome Masters in May).
    # Treating them as one event let Rome results count as 'before' Madrid (found by the clock check).
    # Split an id into separate events wherever its dates jump by more than EVENT_GAP_DAYS; real events
    # never have internal gaps that long, under either date convention. Done BEFORE de-duplication so two
    # real matches between the same players in two events sharing an id are not collapsed as copies.
    df["tourney_id_raw"] = df["tid"]
    df["tid"] = _split_reused_ids(df)
    report["reused_ids_split"] = int(df.groupby(["tour", "tourney_id_raw"])["tid"].nunique().gt(1).sum())
    # de-duplicate overlapping files; keep the most complete row, ties broken by data keys only
    df["key"] = [stable_match_key(t, i, r, a, b) for t, i, r, a, b in
                 zip(df["tour"], df["tid"], df["round"], df["winner_id"], df["loser_id"])]
    df["_nonnull"] = df[["minutes", "sets", "games", "best_of"]].notna().sum(axis=1)
    before = len(df)
    df = (df.sort_values(["key", "_nonnull", "source_priority", "source", "score", "date"],
                         ascending=[True, False, False, True, True, True], kind="mergesort")
            .drop_duplicates("key", keep="first").drop(columns=["_nonnull"]))
    report["duplicates_removed"] = before - len(df)
    # Same match filed under two different tourney_ids (Munich 2026 appears as 2026-308 AND 2026-416).
    # Two players cannot meet in the same round in the same week twice, so keep one copy: the row whose
    # event id has more rows (the main filing), ties broken by data keys.
    df["_week"] = (((df["date"].dt.normalize() + pd.Timedelta(days=2)) - EPOCH_MONDAY).dt.days // 7)
    df["_pair"] = [stable_match_key(t, "", r, a, b) + f"|{w}" for t, r, a, b, w in
                   zip(df["tour"], df["round"], df["winner_id"], df["loser_id"], df["_week"])]
    df["_tid_rows"] = df.groupby(["tour", "tid"])["tid"].transform("size")
    before = len(df)
    df = (df.sort_values(["_pair", "_tid_rows", "tid", "key"], ascending=[True, False, True, True], kind="mergesort")
            .drop_duplicates("_pair", keep="first").drop(columns=["_week", "_pair", "_tid_rows"]))
    report["cross_id_duplicates_removed"] = before - len(df)
    report["matches"] = len(df)
    return df.sort_values("key", kind="mergesort").reset_index(drop=True)


EVENT_GAP_DAYS = 10
STRAY_MAX_ROWS = 5
DOMINANT_MIN_ROWS = 20


BIRTH_TOLERANCE_DAYS = 60


def _player_attributes(df: pd.DataFrame) -> pd.DataFrame:
    """Long table of (tour, pid, normalized name, tid, week, ioc, estimated birth date) per appearance."""
    long = pd.concat([
        df[["tour", "winner_id", "winner_name", "winner_ioc", "winner_age", "tid", "date"]]
            .set_axis(["tour", "pid", "name", "ioc", "age", "tid", "date"], axis=1),
        df[["tour", "loser_id", "loser_name", "loser_ioc", "loser_age", "tid", "date"]]
            .set_axis(["tour", "pid", "name", "ioc", "age", "tid", "date"], axis=1)])
    long["n"] = long["name"].map(norm_name)
    long["week"] = (((long["date"].dt.normalize() + pd.Timedelta(days=2)) - EPOCH_MONDAY).dt.days // 7).astype(float)
    age = long["age"].where((long["age"] > 12) & (long["age"] < 50))
    long["birth"] = long["date"] - pd.to_timedelta(age * 365.25, unit="D")
    long["ioc"] = long["ioc"].astype("string").str.strip().str.upper()
    return long


def _same_person(a: pd.DataFrame, b: pd.DataFrame):
    """True / False from nationality + birth date; None when the attributes can't decide."""
    ioc_a, ioc_b = set(a["ioc"].dropna()), set(b["ioc"].dropna())
    ba, bb = a["birth"].dropna(), b["birth"].dropna()
    if ioc_a and ioc_b and not (ioc_a & ioc_b):
        return False
    if len(ba) and len(bb):
        return abs((ba.median() - bb.median()).days) <= BIRTH_TOLERANCE_DAYS and bool(ioc_a & ioc_b or not (ioc_a and ioc_b))
    return None


def _stray_id_map(df: pd.DataFrame, report: dict) -> dict:
    """TennisMyLife sometimes files a player's matches under a second id (Khachanov: 862 rows as KE29, 1 row as
    106421), and sometimes files a DIFFERENT player under a famous name (several 1-row 'Keegan Smith' ids are
    Swiss/Latvian/British players born years apart). Name alone cannot decide, so:
      * merge when name + nationality + birth date (within BIRTH_TOLERANCE_DAYS) agree;
      * never merge when nationality or birth date disagree;
      * attributes missing -> merge only a tiny id (<= STRAY_MAX_ROWS) into a large one (>= DOMINANT_MIN_ROWS)
        with no week clash.
    Unmerged same-name ids stay separate; live lookups handle them explicitly (see resolve_player)."""
    long = _player_attributes(df)
    counts = long.groupby(["tour", "n", "pid"]).size()
    multi = counts[counts.groupby(level=[0, 1]).transform("size") > 1]
    sub = long[long.set_index(["tour", "n", "pid"]).index.isin(multi.index)]
    by_pid = {k: g for k, g in sub.groupby(["tour", "pid"])}
    mapping, merged, kept_conflict, kept_unknown = {}, 0, 0, 0
    for (tour, n), grp in multi.groupby(level=[0, 1]):
        grp = grp.droplevel([0, 1]).sort_index()
        dom = max(grp.index, key=lambda p: (grp[p], p))
        dom_rows = by_pid[(tour, dom)]
        dom_weeks = dom_rows.groupby("week")["tid"].agg(set).to_dict()
        for pid, c in grp.items():
            if pid == dom:
                continue
            rows = by_pid[(tour, pid)]
            verdict = _same_person(rows, dom_rows)
            if verdict is None:
                clash = any(w in dom_weeks and t not in dom_weeks[w] for w, t in zip(rows["week"], rows["tid"]))
                verdict = bool(c <= STRAY_MAX_ROWS and grp[dom] >= DOMINANT_MIN_ROWS and not clash)
                kept_unknown += not verdict
            else:
                kept_conflict += not verdict
            if verdict:
                mapping[pid] = dom
                merged += 1
    report["player_ids_merged_same_person"] = merged
    report["same_name_ids_kept_different_person"] = kept_conflict
    report["same_name_ids_kept_undecidable"] = kept_unknown
    return mapping


def _split_reused_ids(df: pd.DataFrame) -> pd.Series:
    out = df["tid"].copy()
    for (tour, tid), g in df.groupby(["tour", "tid"], sort=False):
        dates = sorted(g["date"].unique())
        if len(dates) < 2 or (dates[-1] - dates[0]).days <= EVENT_GAP_DAYS:
            continue
        cluster, k, prev = {}, 0, dates[0]
        for d in dates:
            if (d - prev).days > EVENT_GAP_DAYS:
                k += 1
            cluster[d] = k
            prev = d
        if k:
            out.loc[g.index] = [f"{tid}#{cluster[d]}" if cluster[d] else tid for d in g["date"]]
    return out


def event_table(matches: pd.DataFrame) -> pd.DataFrame:
    """Per event: first week (any stage), main-draw week, last-stage week. Uses MIN dates only,
    so it is the same whether dates are tournament-start or per-match, and whether or not
    later rounds have been played yet."""
    g = matches.groupby(["tour", "tid"], sort=True)
    ev = pd.DataFrame({"first_date": g["date"].min(),
                       "main_date": matches[matches["stage"] == 1].groupby(["tour", "tid"])["date"].min(),
                       "tourney_name": g["tourney_name"].agg(lambda s: s.dropna().astype(str).min() if s.notna().any() else ""),
                       "level": g["level"].agg(lambda s: s.astype(str).min())})
    ev["first_week"] = ev["first_date"].map(tennis_week)
    ev["main_week"] = ev["main_date"].map(tennis_week)
    ev["last_week"] = ev["main_week"].where(ev["main_week"].notna(), ev["first_week"])
    return ev


# ============================================================ per-player state (shared by training and live)
@dataclass
class PlayerState:
    events: list = field(default_factory=list)          # sorted event keys (tour, tid)
    last_weeks: list = field(default_factory=list)      # parallel, sorted ascending
    ev_rows: dict = field(default_factory=dict)         # event -> list of row dicts sorted by (stage, rank, opp)
    ev_played: list = field(default_factory=list)       # matches actually played per event
    ev_final: list = field(default_factory=list)
    ev_title: list = field(default_factory=list)
    cum_played: list = field(default_factory=list)      # cumulative played through event i (inclusive)
    flat_flags: list = field(default_factory=list)      # injury flag per row in event order
    cum_rows: list = field(default_factory=list)        # rows through event i (inclusive)
    conflict_weeks: list = field(default_factory=list)  # sorted weeks where this player has >1 event


def _player_rows(matches: pd.DataFrame) -> pd.DataFrame:
    common = ["tour", "tid", "round", "stage", "rank", "sets", "games", "minutes", "best_of", "walkover", "retired", "key", "date"]
    w = matches[common + ["winner_id", "loser_id"]].rename(columns={"winner_id": "pid", "loser_id": "opp"})
    w["won"] = 1
    l = matches[common + ["loser_id", "winner_id"]].rename(columns={"loser_id": "pid", "winner_id": "opp"})
    l["won"] = 0
    pr = pd.concat([w, l], ignore_index=True)
    pr["played"] = (~pr["walkover"]).astype(int)
    # injury proxy: this player retired, or gave a walkover
    pr["injury_flag"] = ((pr["won"] == 0) & (pr["retired"] | pr["walkover"])).astype(int)
    return pr


def build_states(prows: pd.DataFrame, events: pd.DataFrame) -> dict:
    """{(tour, pid): PlayerState}. Ordering uses data keys only - never input row order."""
    lw = events["last_week"].to_dict()
    fw = events["first_week"].to_dict()
    states = {}
    prows = prows.sort_values(["tour", "pid", "tid", "stage", "rank", "opp", "key"], kind="mergesort", na_position="last")
    for (tour, pid), g in prows.groupby(["tour", "pid"], sort=False):
        st = PlayerState()
        by_ev = {}
        for rec in g.to_dict("records"):
            by_ev.setdefault((tour, rec["tid"]), []).append(rec)
        order = sorted(by_ev, key=lambda e: (lw[e], fw[e], e[1]))
        tot_played = tot_rows = 0
        for e in order:
            rows = by_ev[e]
            st.events.append(e)
            st.last_weeks.append(lw[e])
            st.ev_rows[e] = rows
            p = sum(r["played"] for r in rows)
            st.ev_played.append(p)
            st.ev_final.append(int(any(r["round"] == "F" and r["played"] for r in rows)))
            st.ev_title.append(int(any(r["round"] == "F" and r["won"] == 1 for r in rows)))
            tot_played += p
            tot_rows += len(rows)
            st.cum_played.append(tot_played)
            st.cum_rows.append(tot_rows)
            st.flat_flags.extend(r["injury_flag"] for r in rows)
        wk = pd.Series(st.last_weeks).value_counts()
        st.conflict_weeks = sorted(float(w) for w in wk[wk > 1].index)
        states[(tour, pid)] = st
    return states


def player_features(st: PlayerState | None, event, stage: int, rank: float, target_week: float) -> dict:
    """THE feature function. Training and live both call this; nothing else computes features."""
    f = dict.fromkeys(PLAYER_FEATURES + QC_FIELDS, np.nan)
    if st is None:
        st = PlayerState()
    # ---- current event: rows strictly before (stage, rank)
    rows = st.ev_rows.get(event, []) if event is not None else []
    if rank is None or (isinstance(rank, float) and math.isnan(rank)):
        prior = [r for r in rows if r["stage"] < stage]
    else:
        prior = [r for r in rows if not math.isnan(r["rank"]) and (r["stage"], r["rank"]) < (stage, rank)]
    played = [r for r in prior if r["played"]]
    f["ev_matches_before"] = len(played)
    f["ev_quali_matches_before"] = sum(1 for r in played if r["stage"] == 0)
    f["ev_sets_before"] = float(np.nansum([r["sets"] for r in played])) if played else 0.0
    f["ev_games_before"] = float(np.nansum([r["games"] for r in played])) if played else 0.0
    mins = [r["minutes"] for r in played]
    f["ev_minutes_before"] = float(sum(mins)) if mins and not any(math.isnan(m) for m in mins) else (0.0 if not mins else np.nan)
    if played:
        last = played[-1]                                   # rows are sorted by (stage, rank, opp)
        f["prev_in_event_sets"] = last["sets"]
        f["prev_in_event_games"] = last["games"]
        f["prev_in_event_minutes"] = last["minutes"]
        bo = last["best_of"] if not math.isnan(last["best_of"]) else 3
        f["prev_in_event_went_distance"] = float(last["sets"] == bo) if not math.isnan(last["sets"]) else np.nan
    # ---- earlier events: last_week strictly before target week
    k = bisect_left(st.last_weeks, target_week) if not math.isnan(target_week) else 0
    assert event not in st.events[:k], "current event leaked into prior events"
    if k > 0:
        f["weeks_since_prev_event"] = target_week - st.last_weeks[k - 1]
        f["prev_event_matches"] = st.ev_played[k - 1]
        f["prev_event_reached_final"] = st.ev_final[k - 1]
        f["prev_event_won_title"] = st.ev_title[k - 1]
        f["layoff_8w_plus"] = float(f["weeks_since_prev_event"] >= 8)
    for weeks, name in ((4, "matches_last_4w"), (8, "matches_last_8w")):
        j = bisect_left(st.last_weeks, target_week - weeks) if not math.isnan(target_week) else 0
        f[name] = (st.cum_played[k - 1] - (st.cum_played[j - 1] if j > 0 else 0)) if k > j else 0
        if weeks == 4:
            f["events_last_4w"] = max(k - j, 0)
    if not math.isnan(target_week):
        f["qc_conflict_weeks_8w"] = bisect_left(st.conflict_weeks, target_week) - bisect_left(st.conflict_weeks, target_week - 8)
    prior_events_played = st.cum_played[k - 1] if k > 0 else 0
    f["n_prior_matches"] = prior_events_played + len(played)
    # ---- injury proxies over the most recent rows (current-event prior rows are most recent)
    n_flat = st.cum_rows[k - 1] if k > 0 else 0
    recent = st.flat_flags[max(0, n_flat - 5):n_flat] + [r["injury_flag"] for r in prior]
    recent = recent[-5:]
    if recent:
        f["retired_last_match"] = recent[-1]
        f["retired_or_wo_last5"] = sum(recent)
    return f


def _pair_features(s1, s2, event, stage, rank, week) -> dict:
    f1 = player_features(s1, event, stage, rank, week)
    f2 = player_features(s2, event, stage, rank, week)
    out = {f"p1_{k}": v for k, v in f1.items()}
    out.update({f"p2_{k}": v for k, v in f2.items()})
    out.update({f"d_{k}": (f1[k] - f2[k]) if not (pd.isna(f1[k]) or pd.isna(f2[k])) else np.nan for k in PLAYER_FEATURES})
    return out


def target_week_for(ev_row, stage: int) -> float:
    return ev_row["main_week"] if stage == 1 and not pd.isna(ev_row["main_week"]) else ev_row["first_week"]


# ============================================================ training table
def build_training_table(matches: pd.DataFrame) -> pd.DataFrame:
    events = event_table(matches)
    states = build_states(_player_rows(matches), events)
    ev_rows = events[["first_week", "main_week"]].to_dict("index")
    out = []
    for m in matches.sort_values("key", kind="mergesort").to_dict("records"):
        ev = (m["tour"], m["tid"])
        week = target_week_for(ev_rows[ev], m["stage"])
        p1w = _p1_is_winner(m["key"])
        a, b = (m["winner_id"], m["loser_id"]) if p1w else (m["loser_id"], m["winner_id"])
        an, bn = (m["winner_name"], m["loser_name"]) if p1w else (m["loser_name"], m["winner_name"])
        row = {"match_key": m["key"], "tour": m["tour"], "tid": m["tid"], "tourney_name": m["tourney_name"],
               "level": m["level"], "round": m["round"], "stage": m["stage"], "date": m["date"], "target_week": week,
               "p1_id": a, "p2_id": b, "p1_name": an, "p2_name": bn, "won": int(p1w), "walkover": m["walkover"],
               "p1_unknown_player": 0, "p2_unknown_player": 0}
        row.update(_pair_features(states.get((m["tour"], a)), states.get((m["tour"], b)), ev, m["stage"], m["rank"], week))
        out.append(row)
    t = pd.DataFrame(out)
    t["feature_version"] = FEATURE_VERSION
    return t


# ============================================================ live
TOUR_MAP = {"ATP": "MEN", "CHALLENGER": "MEN", "MEN": "MEN", "WTA": "WTA", "WTA 125K": "WTA", "WTA125": "WTA"}
EVENT_STOPWORDS = {"atp", "wta", "challenger", "men", "women", "singles", "doubles", "masters", "open", "k",
                   "the", "de", "of", "cup", "championships", "international"}


def _event_key(name: str) -> str:
    """'ATP Challenger Porto 2, Portugal Men Singles' -> 'porto 2'; 'Canada Masters' -> 'canada'.
    Digits are kept so 'Porto' and 'Porto 2' stay different events."""
    s = unicodedata.normalize("NFKD", str(name).split(",")[0]).encode("ascii", "ignore").decode().lower()
    toks = re.sub(r"[^a-z0-9 ]", " ", s).split()
    return " ".join(t for t in toks if t not in EVENT_STOPWORDS)


def _event_tokens(name: str) -> set:
    return set(_event_key(name).split())


TEAM_LEVELS = {"D", "A"}     # Davis Cup / team & exhibition-style events
# Days from an event's first recorded match (qualifying included) during which a fixture can belong to it:
#   MAX_EVENT_DAYS   - any match (Sat quali start -> Sunday final = 8 days, +1 for rain)
#   FIRST_MATCH_DAYS - a player's FIRST match there (later first matches = byes), which is what separates
#                      this week's 'Shymkent' from last week's 'Shymkent' on the Monday of a back-to-back
MAX_EVENT_DAYS = {"G": 23, "M": 15, "1000": 15, "PM": 15, "P5": 15, "D": 12, "A": 12}
FIRST_MATCH_DAYS = {"G": 10, "M": 8, "1000": 8, "PM": 8, "P5": 8}
DEFAULT_MAX_EVENT_DAYS, DEFAULT_FIRST_MATCH_DAYS = 9, 6


class LiveFeatureError(LookupError):
    pass


class LiveFeatures:
    """Build fatigue features for upcoming fixtures from the matches completed so far.

    history: canonical matches (load_matches / canonicalize) containing ONLY completed results.
    event_aliases: optional {fixture city token string: TennisMyLife tourney_name} for names that differ
                   (e.g. {"montreal": "Canada Masters"}). Add entries when the builder raises.
    """

    def __init__(self, history: pd.DataFrame, event_aliases: dict | None = None):
        self.h = history
        self.events = event_table(history)
        self.states = build_states(_player_rows(history), self.events)
        self.aliases = {_event_key(k): _event_key(v) for k, v in (event_aliases or {}).items()}
        names = pd.concat([history[["tour", "winner_id", "winner_name"]].set_axis(["tour", "pid", "name"], axis=1),
                           history[["tour", "loser_id", "loser_name"]].set_axis(["tour", "pid", "name"], axis=1)])
        names["n"] = names["name"].map(norm_name)
        cnt = names.groupby(["tour", "n", "pid"]).size()
        self.name_index = {k: sorted(g.droplevel([0, 1]).items()) for k, g in cnt.groupby(level=[0, 1])}
        self.name_notes = {}

    def resolve_player(self, tour: str, name: str) -> str:
        """Same-name ids left after identity merging are different people (TennisMyLife files some players
        under the wrong name). Resolve to the dominant id only when it is overwhelmingly the main one;
        otherwise refuse. The choice is recorded in name_notes / the output."""
        ids = self.name_index.get((tour, norm_name(name)))
        if not ids:
            raise LiveFeatureError(f"Unknown player '{name}' ({tour}): not in results history. Add an alias - do not default.")
        if len(ids) == 1:
            return ids[0][0]
        dom, dom_n = max(ids, key=lambda x: (x[1], x[0]))
        others = [(p, c) for p, c in ids if p != dom]
        if dom_n >= DOMINANT_MIN_ROWS and all(c <= STRAY_MAX_ROWS for _, c in others):
            self.name_notes[dom] = f"chose {dom} ({dom_n} matches) over {others}"
            return dom
        raise LiveFeatureError(f"Ambiguous player '{name}' ({tour}): ids {ids}.")

    def resolve_event(self, tour: str, tournament: str, week: float, pids: list, fixture_day=None):
        fixture_day = _day(fixture_day) if fixture_day is not None else EPOCH_MONDAY + pd.Timedelta(days=7 * week)
        ev = self.events.loc[tour] if tour in self.events.index.get_level_values(0) else self.events.iloc[0:0]
        window = ev[(ev["first_week"] >= week - 4) & (ev["first_week"] <= week)]

        def can_be_current(t):
            """Could this fixture belong to event t? Judged in days (tennis weeks put weekend matches into
            the next week) plus player evidence."""
            r = window.loc[t]
            lv = str(r["level"])
            days = (fixture_day - r["first_date"]).days
            if days < -3 or days > MAX_EVENT_DAYS.get(lv, DEFAULT_MAX_EVENT_DAYS):
                return False
            # the fixture itself is already in the results (re-run after it was played): it is this event
            p1_rows = self.states.get((tour, pids[0]), PlayerState()).ev_rows.get((tour, t), [])
            if any(r["opp"] == pids[1] for r in p1_rows):
                return True
            statuses = []
            for p in pids:
                rows = self.states.get((tour, p), PlayerState()).ev_rows.get((tour, t), [])
                if rows:
                    last = rows[-1]
                    # still in the draw: won last match (not the final), or lost in qualifying early enough to be
                    # a lucky loser in the first main-draw round
                    lucky_loser = last["stage"] == 0 and days <= FIRST_MATCH_DAYS.get(lv, DEFAULT_FIRST_MATCH_DAYS)
                    statuses.append((last["won"] == 1 and last["round"] != "F") or lucky_loser)
            if statuses:
                return all(statuses)
            return days <= FIRST_MATCH_DAYS.get(lv, DEFAULT_FIRST_MATCH_DAYS)

        running = window.loc[[t for t in window.index if can_be_current(t)]]
        fkey = _event_key(tournament)
        alias = self.aliases.get(fkey)

        def name_matches(tname):
            if alias is not None:
                return _event_key(tname) == alias
            if _event_key(tname) == fkey:
                return True
            tt, ft = _event_tokens(tname), set(fkey.split())
            # digits must agree exactly ('porto' vs 'porto 2'); otherwise allow word-subset matches
            if {t for t in tt if t.isdigit()} != {t for t in ft if t.isdigit()}:
                return False
            return bool(tt) and bool(ft) and (tt <= ft or ft <= tt)

        def has_rows(t):
            return any((tour, t) in self.states.get((tour, p), PlayerState()).ev_rows for p in pids)

        cands = sorted(tid for tid, r in running.iterrows() if name_matches(r["tourney_name"]))
        if len(cands) > 1:                       # 1) prefer the event these players are already in
            with_rows = [t for t in cands if has_rows(t)]
            if len(with_rows) == 1:
                cands = with_rows
        if len(cands) > 1:                       # 2) otherwise the most recent start, if unique
            latest = max(window.loc[t, "first_week"] for t in cands)
            top = [t for t in cands if window.loc[t, "first_week"] == latest]
            if len(top) == 1:
                cands = top
        if len(cands) > 1:
            raise LiveFeatureError(f"Ambiguous event for '{tournament}' week {week}: {cands}")
        if not cands:
            # A player whose latest result in a recent event is a win (not a final) is still IN that event,
            # so this fixture almost certainly belongs to it and the name simply did not match.
            def still_alive(t):
                # only individual events still running: team events (Davis Cup etc.) and qualifying wins
                # (qualifiers often withdraw) are not evidence the player is still in that draw
                lv = str(window.loc[t, "level"])
                if lv in TEAM_LEVELS or (fixture_day - window.loc[t, "first_date"]).days > MAX_EVENT_DAYS.get(lv, DEFAULT_MAX_EVENT_DAYS):
                    return False
                for p in pids:
                    rows = self.states.get((tour, p), PlayerState()).ev_rows.get((tour, t), [])
                    if rows and rows[-1]["won"] == 1 and rows[-1]["stage"] == 1 and rows[-1]["round"] not in ("F", "RR"):
                        return True
                return False
            alive = [t for t in window.index if still_alive(t)]
            if alive:
                raise LiveFeatureError(f"Could not match '{tournament}' to an event, but a player is still alive in "
                                       f"{alive} ({[window.loc[t, 'tourney_name'] for t in alive]}). Add an event alias "
                                       f"instead of defaulting.")
            return None
        return (tour, cands[0])

    def features(self, fixture: dict, allow_unknown: bool = False) -> dict:
        """fixture: {tour, tournament, start_time_utc, player1, player2} (market board format).

        allow_unknown=False (default): a player missing from the results history raises.
        allow_unknown=True: that player gets no-history features AND p?_unknown_player = 1, so the model
        sees it explicitly (TennisMyLife has no WTA 125 / ITF results, so many such players are real)."""
        tour = TOUR_MAP.get(str(fixture["tour"]).upper().strip())
        if tour is None:
            raise LiveFeatureError(f"Unknown tour '{fixture['tour']}'")
        week = tennis_week(pd.Timestamp(fixture["start_time_utc"]))
        ids, unknown = [], []
        for key in ("player1", "player2"):
            try:
                ids.append(self.resolve_player(tour, fixture[key]))
                unknown.append(0)
            except LiveFeatureError as e:
                if not (allow_unknown and str(e).startswith("Unknown player")):
                    raise
                ids.append(f"UNKNOWN:{norm_name(fixture[key])}")
                unknown.append(1)
        p1, p2 = ids
        event = self.resolve_event(tour, fixture["tournament"], week, [p1, p2], fixture["start_time_utc"])
        stage, rank, target_week, how = 1, float("inf"), week, "new_event"
        if event is not None:
            erow = self.events.loc[event]
            key_rows = [r for r in self.states.get((tour, p1), PlayerState()).ev_rows.get(event, []) if r["opp"] == p2]
            if key_rows:                                   # match already in results: rerun exactly
                r = key_rows[-1]
                stage, rank, how = r["stage"], r["rank"], "completed_rerun"
            else:
                has_main = not pd.isna(erow["main_week"])
                stage = 1 if (has_main or week > erow["first_week"]) else 0
                how = "inferred_main" if stage == 1 else "inferred_quali"
            target_week = target_week_for(erow, stage) if not (stage == 1 and pd.isna(erow["main_week"])) else week
        out = {"tour": tour, "p1_id": p1, "p2_id": p2, "event": None if event is None else event[1],
               "id_notes": "; ".join(self.name_notes[p] for p in (p1, p2) if p in self.name_notes),
               "p1_unknown_player": unknown[0], "p2_unknown_player": unknown[1],
               "stage": stage, "target_week": target_week, "resolution": how, "feature_version": FEATURE_VERSION}
        out.update(_pair_features(self.states.get((tour, p1)), self.states.get((tour, p2)), event, stage, rank, target_week))
        return out


# ============================================================ CLI
def main():
    import argparse
    ap = argparse.ArgumentParser(description="Build leak-free fatigue features from TennisMyLife feeds.")
    ap.add_argument("data_dir", nargs="?", default=".",
                    help="repo root (default; reads .v5_history_cache + v5_results_ready) or an audit-bundle "
                         "folder containing tennismylife_raw_current/ and historical_rating_aggregates/")
    ap.add_argument("--out", default="fatigue_training_table.csv")
    ap.add_argument("--board", help="optional market_board_input.csv: also build live features for its fixtures")
    ap.add_argument("--allow-unknown", action="store_true",
                    help="build fixtures with players missing from history (flagged p?_unknown_player=1) instead of refusing")
    a = ap.parse_args()
    rep = {}
    bundle = os.path.isdir(os.path.join(a.data_dir, "historical_rating_aggregates"))
    m = load_matches(a.data_dir, report=rep) if bundle else load_repo_matches(a.data_dir, report=rep)
    print("load report:", rep)
    t = build_training_table(m)
    t.to_csv(a.out, index=False)
    print(f"wrote {len(t)} rows x {t.shape[1]} cols -> {a.out}")
    if a.board:
        lf = LiveFeatures(m)
        b = pd.read_csv(a.board).drop_duplicates("fixture_id")
        rows, errors = [], []
        for fx in b.to_dict("records"):
            try:
                rows.append({"fixture_id": fx["fixture_id"], **lf.features(fx, allow_unknown=a.allow_unknown)})
            except LiveFeatureError as e:
                errors.append({"fixture_id": fx["fixture_id"], "player1": fx["player1"], "player2": fx["player2"],
                               "tournament": fx["tournament"], "error": str(e)})
        pd.DataFrame(rows).to_csv("fatigue_live_features.csv", index=False)
        pd.DataFrame(errors).to_csv("fatigue_live_errors.csv", index=False)
        print(f"live: {len(rows)} fixtures built, {len(errors)} refused (see fatigue_live_errors.csv)")


if __name__ == "__main__":
    main()
