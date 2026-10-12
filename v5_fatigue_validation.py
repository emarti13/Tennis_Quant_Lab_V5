"""
v5_fatigue_validation.py - independent checks for v5_fatigue_features (research tooling, no production use)

  link_oddspapi(matches, fixtures)   link finished OddsPapi fixtures (real clock times) to TennisMyLife matches
  run_parity(matches, fixtures, n)   live code fed only pre-first-serve data must reproduce the training row
  clock_check(matches, fixtures)     ordering rules vs real start/end times: "before" must really be before

Shared by tests/test_v5_fatigue_features.py and diagnose_fatigue_ordering_vs_clock.py.
"""
from __future__ import annotations

import math
import time
from collections import Counter, defaultdict

import pandas as pd

import v5_fatigue_features as F

COMPARE = F.PLAYER_FEATURES + F.QC_FIELDS


def same(a, b) -> bool:
    """Exact equality with NaN == NaN."""
    na = a is None or (isinstance(a, float) and math.isnan(a))
    nb = b is None or (isinstance(b, float) and math.isnan(b))
    return (na and nb) or (not na and not nb and a == b)


def link_oddspapi(m: pd.DataFrame, fixtures: pd.DataFrame) -> pd.DataFrame:
    """Finished OddsPapi fixtures linked to TennisMyLife matches: same tour, same player pair, fixture week
    inside the event's span, and overlapping tournament-name tokens (the same pair can meet at a warm-up
    event in the same window). Ambiguous links are dropped, never guessed."""
    ev = F.event_table(m)
    fx = fixtures[fixtures["status_name"].eq("Finished")
                  & fixtures["category_name"].isin(["ATP", "Challenger", "WTA", "WTA 125K"])].copy()
    fx["tour"] = fx["category_name"].str.upper().map(F.TOUR_MAP)
    fx["pair"] = [frozenset((F.norm_name(a), F.norm_name(b))) for a, b in zip(fx.participant1_name, fx.participant2_name)]
    fx["week"] = pd.to_datetime(fx["start_time_utc"], utc=True).map(F.tennis_week)
    mm = m[m.date >= "2025-12-01"].copy()
    mm["pair"] = [frozenset((F.norm_name(a), F.norm_name(b))) for a, b in zip(mm.winner_name, mm.loser_name)]
    mm = mm.join(ev[["first_week", "last_week"]], on=["tour", "tid"])
    j = fx.merge(mm, on=["tour", "pair"], suffixes=("_fx", ""))
    j = j[(j["week"] >= j["first_week"]) & (j["week"] <= j["first_week"] + 3)]
    j = j[[bool(F._event_tokens(a) & F._event_tokens(b)) for a, b in zip(j["tournament_name"], j["tourney_name"])]]
    j = j.sort_values(["key", "start_time_utc"]).drop_duplicates("key")
    return j[~j.duplicated("fixture_id", keep=False)]


def snapshot_for(m, fw, target, fixture_week):
    """What a live feed holds one minute before first serve: no later rounds of the target event, not the
    target itself, no events starting after this week. Other players' same-round results ARE included."""
    same_ev = (m.tour == target["tour"]) & (m.tid == target["tid"])
    later = same_ev & ((m.stage > target["stage"]) | ((m.stage == target["stage"]) & (m["rank"] > target["rank"])))
    return m[~later & (m.key != target["key"]) & (fw <= fixture_week)]


def restrict_for(snap, fw, tour, tid, pids, week):
    """Every row the features can depend on (the players' rows, all rows of their events, the name-resolution
    window). Same live code, smaller input; run_parity also checks a few FULL snapshots to prove it is harmless."""
    mine = (snap.tour == tour) & (snap.winner_id.isin(pids) | snap.loser_id.isin(pids))
    their_events = set(snap.loc[mine, "tid"]) | {tid}
    f = fw.loc[snap.index]
    window = (snap.tour == tour) & (f >= week - 4) & (f <= week)
    return snap[mine | ((snap.tour == tour) & snap.tid.isin(their_events)) | window]


def _fixture(fx):
    return {"tour": fx["category_name"], "tournament": fx["tournament_name"], "start_time_utc": fx["start_time_utc"],
            "player1": fx["participant1_name"], "player2": fx["participant2_name"]}


def _compare(live, tr):
    lmap = {live["p1_id"]: "p1", live["p2_id"]: "p2"}
    diffs = []
    for side in ("p1", "p2"):
        lside = lmap.get(tr[f"{side}_id"])
        if lside is None:
            diffs.append(f"player id mismatch {tr[f'{side}_id']}")
            continue
        diffs += [f"{side}.{k}: live {live[f'{lside}_{k}']} vs train {tr[f'{side}_{k}']}"
                  for k in COMPARE if not same(live[f"{lside}_{k}"], tr[f"{side}_{k}"])]
    return diffs


def run_parity(m_all: pd.DataFrame, fixtures: pd.DataFrame, n: int = 400, seed: int = 7, full_checks: int = 3,
               training: pd.DataFrame | None = None, progress: bool = False) -> dict:
    training = training if training is not None else F.build_training_table(m_all)
    train_i = training.set_index("match_key")
    links = link_oddspapi(m_all, fixtures)
    links = links[~links.walkover]
    sample = links.sample(min(n, len(links)), random_state=seed)
    ev = F.event_table(m_all)
    fw = m_all.join(ev["first_week"], on=["tour", "tid"])["first_week"]
    res = {"linked": len(links), "identical": 0, "mismatched": 0, "refused": 0, "mismatch_examples": [],
           "refusals_by_type": Counter(), "refusal_examples": [], "resolutions": Counter(), "full_identical": 0,
           "full_checked": 0}
    t0 = time.time()
    for i, fx in enumerate(sample.to_dict("records")):
        if progress and i % 50 == 0:
            print(f"  parity {i}/{len(sample)} ({time.time() - t0:.0f}s)", flush=True)
        target = m_all.loc[m_all.key == fx["key"]].iloc[0]
        week = F.tennis_week(pd.Timestamp(fx["start_time_utc"]))
        snap = snapshot_for(m_all, fw, target, week)
        if i < full_checks:                                  # unrestricted snapshot, proves restriction is harmless
            try:
                live_full = F.LiveFeatures(snap).features(_fixture(fx))
                res["full_checked"] += 1
                res["full_identical"] += not _compare(live_full, train_i.loc[fx["key"]])
            except F.LiveFeatureError:
                pass
        snap = restrict_for(snap, fw, target["tour"], target["tid"], [target.winner_id, target.loser_id], week)
        try:
            live = F.LiveFeatures(snap).features(_fixture(fx))
        except F.LiveFeatureError as e:
            res["refused"] += 1
            res["refusals_by_type"][str(e).split("'")[0].strip()] += 1
            res["refusal_examples"].append(str(e)[:160])
            continue
        res["resolutions"][live["resolution"]] += 1
        diffs = _compare(live, train_i.loc[fx["key"]])
        if diffs:
            res["mismatched"] += 1
            res["mismatch_examples"].append(f"{target.tourney_name} {target['round']} {target.winner_name} v "
                                            f"{target.loser_name}: {diffs[:3]}")
        else:
            res["identical"] += 1
    return res


def clock_check(m: pd.DataFrame, fixtures: pd.DataFrame, tolerance_minutes: int = 5) -> dict:
    """For every pair (A, B) of the same player's clock-timed matches: does the rule say A is before B, and did
    A actually end before B started? rule-before-but-clock-after = leak risk (must be 0)."""
    ev = F.event_table(m)
    L = link_oddspapi(m, fixtures)
    L = L[~L.walkover & L.true_start_time_utc.notna() & L.true_end_time_utc.notna()].copy()
    L["t0"] = pd.to_datetime(L.true_start_time_utc, utc=True)
    L["t1"] = pd.to_datetime(L.true_end_time_utc, utc=True)
    L = L[(L.t1 > L.t0) & ((L.t1 - L.t0) < pd.Timedelta(hours=8))]
    by_player = defaultdict(list)
    for r in L.to_dict("records"):
        evr = ev.loc[(r["tour"], r["tid"])]
        info = dict(tid=r["tid"], stage=r["stage"], rank=r["rank"], t0=r["t0"], t1=r["t1"],
                    last_week=evr["last_week"], target_week=F.target_week_for(evr, r["stage"]),
                    name=f"{r['tourney_name']} {r['round']}")
        by_player[(r["tour"], r["winner_id"])].append(info)
        by_player[(r["tour"], r["loser_id"])].append(info)
    tol = pd.Timedelta(minutes=tolerance_minutes)
    out = {"timed_matches": len(L), "pairs": 0, "leak_risk": 0, "missed": 0, "leak_examples": [], "missed_kinds": Counter()}
    for pid, rows in by_player.items():
        for a in rows:
            for b in rows:
                if a is b:
                    continue
                rule = ((a["stage"], a["rank"]) < (b["stage"], b["rank"])) if a["tid"] == b["tid"] \
                    else a["last_week"] < b["target_week"]
                clock = a["t1"] <= b["t0"] + tol
                out["pairs"] += 1
                if rule and not clock:
                    out["leak_risk"] += 1
                    out["leak_examples"].append(f"{pid[1]}: {a['name']} ({a['t0']:%Y-%m-%d %H:%M}) counted before "
                                                f"{b['name']} ({b['t0']:%Y-%m-%d %H:%M})")
                if clock and not rule:
                    out["missed"] += 1
                    out["missed_kinds"]["same event" if a["tid"] == b["tid"] else "same week"] += 1
    return out
