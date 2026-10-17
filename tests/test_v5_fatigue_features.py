"""
Safety tests for v5_fatigue_features. Each test targets a way the previous context model broke.

Unit tests (always run, seconds): hand-computed schedules, same-round concurrency, walkovers, re-runs,
loud failures, row-order invariance.

Real-data tests (run only when data is available; skipped otherwise, e.g. in the PR regression suite):
  * repo layout:  .v5_history_cache/*.csv present (python bootstrap_v5_history.py)
  * audit bundle: V5_FATIGUE_BUNDLE=<bundle>/02_upstream_daily_sources
  V5_FATIGUE_PARITY_N (default 60; the v5_fatigue_features workflow uses 400) sets the parity sample size.
"""
import math
import os
import random
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import v5_fatigue_features as F
import v5_fatigue_validation as V

ROOT = Path(__file__).resolve().parents[1]
FEATS = [f"{p}_{k}" for p in ("p1", "p2") for k in F.PLAYER_FEATURES + F.QC_FIELDS] + [f"d_{k}" for k in F.PLAYER_FEATURES]


def frames_equal(a, b, cols=FEATS):
    a = a.set_index("match_key").sort_index()[cols]
    b = b.set_index("match_key").sort_index()[cols]
    common = a.index.intersection(b.index)
    a, b = a.loc[common], b.loc[common]
    return int((~((a == b) | (a.isna() & b.isna()))).values.sum()), len(common)


# ===================================================================== synthetic unit tests
def synth_raw():
    """Hand-built schedule for player A with known answers."""
    rows = []

    def add(tid, name, date, rnd, w, l, score="6-4 6-4", minutes=80, level="C", bo=3):
        rows.append(dict(tourney_id=tid, tourney_name=name, tourney_level=level, tourney_date=date, round=rnd,
                         winner_id=w, loser_id=l, winner_name=f"Player {w}", loser_name=f"Player {l}",
                         score=score, minutes=minutes, best_of=bo, tour="MEN", source="synth", source_priority=0))
    # E0: A reaches the final and loses it
    add("E0", "Alpha", 20250106, "R32", "A", "B1")
    add("E0", "Alpha", 20250106, "R16", "A", "B2")
    add("E0", "Alpha", 20250106, "QF", "A", "B3")
    add("E0", "Alpha", 20250106, "SF", "A", "B4", score="4-6 6-3 7-5", minutes=150)
    add("E0", "Alpha", 20250106, "F", "B5", "A")
    # E1 next week: A through 3 qualifying rounds, wins R32 (opponent retires), plays R16 vs C
    add("E1", "Beta", 20250112, "Q1", "A", "Q1x", minutes=60)
    add("E1", "Beta", 20250112, "Q2", "A", "Q2x", minutes=70)
    add("E1", "Beta", 20250112, "Q3", "A", "Q3x", score="7-6(5) 6-7(3) 6-2", minutes=None)
    add("E1", "Beta", 20250113, "R32", "A", "D1", score="6-1 3-0 RET", minutes=40)
    add("E1", "Beta", 20250113, "R32", "C", "D2")
    add("E1", "Beta", 20250113, "R16", "C", "A")
    add("E1", "Beta", 20250113, "QF", "C", "Z")      # later round: must never be visible to R16
    # E2 twelve weeks later: A gives a walkover
    add("E2", "Gamma", 20250407, "R32", "W1", "A", score="W/O", minutes=None)
    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def synth():
    m = F.canonicalize(synth_raw())
    return m, F.build_training_table(m)


def _feats(t, tid, rnd, pid):
    r = t[(t.tid == tid) & (t["round"] == rnd) & ((t.p1_id == pid) | (t.p2_id == pid))].iloc[0]
    side = "p1" if r.p1_id == pid else "p2"
    return {k: r[f"{side}_{k}"] for k in F.PLAYER_FEATURES + F.QC_FIELDS}


def test_within_event_counts_quali_and_main_only_before_target(synth):
    f = _feats(synth[1], "E1", "R16", "A")
    assert f["ev_matches_before"] == 4 and f["ev_quali_matches_before"] == 3
    assert f["ev_sets_before"] == 2 + 2 + 3 + 2          # QF row invisible
    assert math.isnan(f["ev_minutes_before"])            # one prior match lacks minutes
    assert f["prev_in_event_minutes"] == 40 and f["retired_last_match"] == 0
    assert f["n_prior_matches"] == 9


def test_previous_event_features(synth):
    f = _feats(synth[1], "E1", "R16", "A")
    assert (f["prev_event_matches"], f["prev_event_reached_final"], f["prev_event_won_title"], f["weeks_since_prev_event"]) == (5, 1, 0, 1)


def test_same_round_matches_never_see_each_other(synth):
    t = synth[1]
    assert _feats(t, "E1", "R32", "A")["ev_matches_before"] == 3
    assert _feats(t, "E1", "R32", "C")["ev_matches_before"] == 0
    assert _feats(t, "E1", "R16", "C")["ev_matches_before"] == 1


def test_quarterfinal_is_not_qualifying(synth):
    m = synth[0]
    assert set(m.loc[m["round"] == "QF", "stage"]) == {1}       # "QF" starts with Q: regression guard


def test_walkover_and_layoff(synth):
    t = synth[1]
    g = _feats(t, "E2", "R32", "A")
    assert g["ev_matches_before"] == 0 and t[t.tid == "E2"].iloc[0]["walkover"]
    assert g["layoff_8w_plus"] == 1 and g["weeks_since_prev_event"] == 12


def test_orientation_is_not_winner_first(synth):
    assert 0 < synth[1]["won"].mean() < 1


def test_row_order_never_changes_features(synth):
    for seed in range(5):
        n, _ = frames_equal(synth[1], F.build_training_table(F.canonicalize(synth_raw().sample(frac=1, random_state=seed))))
        assert n == 0


def _live_vs_train(out, tr, swap):
    return [k for k in F.PLAYER_FEATURES if not V.same(out[f"p1_{k}"], tr[f"{'p2' if swap else 'p1'}_{k}"])]


BETA_FIXTURE = {"tour": "Challenger", "tournament": "ATP Challenger Beta, Somewhere Men Singles",
                "start_time_utc": "2025-01-15T10:00:00Z", "player1": "Player A", "player2": "Player C"}


def test_live_path_reproduces_training_row(synth):
    m, t = synth
    hist = m[~((m.tid == "E1") & m["round"].isin(["R16", "QF"])) & (m.tid != "E2")]
    out = F.LiveFeatures(hist).features(BETA_FIXTURE)
    tr = t[(t.tid == "E1") & (t["round"] == "R16")].iloc[0]
    assert out["resolution"] == "inferred_main"
    assert _live_vs_train(out, tr, tr.p1_id != "A") == []


def test_completed_match_rerun_reproduces_training_row(synth):
    m, t = synth
    out = F.LiveFeatures(m[m.tid != "E2"]).features(BETA_FIXTURE)       # result already in the feed, A lost
    tr = t[(t.tid == "E1") & (t["round"] == "R16")].iloc[0]
    assert out["resolution"] == "completed_rerun"
    assert _live_vs_train(out, tr, tr.p1_id != "A") == []


def test_unknown_player_raises_unless_explicitly_allowed(synth):
    lf = F.LiveFeatures(synth[0])
    fx = dict(BETA_FIXTURE, player1="Nobody Known")
    with pytest.raises(F.LiveFeatureError):
        lf.features(fx)
    out = lf.features(fx, allow_unknown=True)
    assert out["p1_unknown_player"] == 1 and out["p1_n_prior_matches"] == 0


def test_unmatched_event_name_while_player_alive_raises(synth):
    m = synth[0]
    hist = m[~((m.tid == "E1") & m["round"].isin(["R16", "QF"])) & (m.tid != "E2")]
    with pytest.raises(F.LiveFeatureError):
        F.LiveFeatures(hist).features(dict(BETA_FIXTURE, tournament="ATP Challenger Totally Different, X"))


def test_reused_tourney_id_is_split_into_two_events():
    raw = synth_raw()
    late = raw[raw.tourney_id == "E0"].assign(tourney_name="Later Event", tourney_date=20250505)
    m = F.canonicalize(pd.concat([raw, late], ignore_index=True))
    assert m.loc[m.tourney_id_raw == "E0", "tid"].nunique() == 2


def test_identity_merge_uses_nationality_and_birth_date():
    rows = []
    for i in range(25):                                   # dominant id, born ~2000
        rows.append(dict(tourney_id=f"T{i}", tourney_name=f"T{i}", tourney_level="C", tourney_date=20200106 + 700 * 0,
                         round="R32", winner_id="MAIN", loser_id=f"O{i}", winner_name="Same Name", loser_name=f"Opp {i}",
                         winner_ioc="USA", winner_age=20.0, loser_ioc="FRA", loser_age=25.0, score="6-4 6-4",
                         minutes=80, best_of=3, tour="MEN", source="s", source_priority=0))
    for i in range(25):
        rows[i]["tourney_date"] = int((pd.Timestamp("2020-01-06") + pd.Timedelta(weeks=i)).strftime("%Y%m%d"))
        rows[i]["winner_age"] = 20.0 + i * 7 / 365.25
    same = dict(rows[0], tourney_id="S1", tourney_name="S1", tourney_date=20210104, winner_id="ALT", loser_id="X1",
                loser_name="Opp X1", winner_age=21.0)
    other = dict(rows[0], tourney_id="S2", tourney_name="S2", tourney_date=20210111, winner_id="IMPOSTER", loser_id="X2",
                 loser_name="Opp X2", winner_ioc="LAT", winner_age=30.0)
    rep = {}
    m = F.canonicalize(pd.DataFrame(rows + [same, other]), rep)
    ids = set(m.winner_id)
    assert "ALT" not in ids and "MAIN" in ids              # same person (USA, same birth year) merged
    assert "IMPOSTER" in ids                               # different nationality and age: kept separate


# ===================================================================== real-data tests
def _real_data():
    bundle = os.environ.get("V5_FATIGUE_BUNDLE")
    if bundle:
        return F.load_matches(bundle), pd.read_csv(Path(bundle) / "oddspapi_registry" / "fixtures.csv", low_memory=False)
    if (ROOT / ".v5_history_cache" / "ATP.csv").exists():
        return F.load_repo_matches(str(ROOT)), pd.read_csv(ROOT / "oddspapi_registry" / "fixtures.csv", low_memory=False)
    return None


@pytest.fixture(scope="module")
def real():
    data = _real_data()
    if data is None:
        pytest.skip("real-data tests need .v5_history_cache (bootstrap_v5_history.py) or V5_FATIGUE_BUNDLE")
    m, fixtures = data
    sub = m[m.date >= "2024-01-01"].copy()
    return {"m": m, "fixtures": fixtures, "sub": sub, "base": F.build_training_table(sub)}


def test_real_shuffle_invariance(real):
    n, tot = frames_equal(real["base"], F.build_training_table(real["sub"].sample(frac=1, random_state=7)))
    assert n == 0 and tot > 10000


def test_real_future_blindness(real):
    sub = real["sub"]
    ev = F.event_table(sub)
    cut = ev["first_week"].quantile(0.6)
    fw = sub.join(ev["first_week"], on=["tour", "tid"])["first_week"]
    trunc = sub[(fw < cut - 1) | ((fw == cut - 1) & (sub["rank"] < 14))]
    n, tot = frames_equal(real["base"], F.build_training_table(trunc))
    assert n == 0 and tot > 1000


def test_real_result_blindness(real):
    sub = real["sub"]
    used, keys = set(), []
    for k, w, l in sub[["key", "winner_id", "loser_id"]].sample(frac=1, random_state=7).itertuples(index=False):
        if w not in used and l not in used:                # disjoint players: flips can't affect each other
            keys.append(k)
            used.update((w, l))
        if len(keys) == 300:
            break
    flipped = sub.copy()
    sel = flipped.key.isin(keys)
    flipped.loc[sel, ["winner_id", "loser_id", "winner_name", "loser_name"]] = \
        flipped.loc[sel, ["loser_id", "winner_id", "loser_name", "winner_name"]].values
    a = real["base"][real["base"].match_key.isin(keys)].set_index("match_key")
    b = F.build_training_table(flipped).set_index("match_key").loc[a.index]
    bad = 0
    for k in a.index:
        for side in ("p1", "p2"):
            oside = "p1" if b.loc[k, "p1_id"] == a.loc[k, f"{side}_id"] else "p2"
            bad += sum(not V.same(a.loc[k, f"{side}_{f}"], b.loc[k, f"{oside}_{f}"]) for f in F.PLAYER_FEATURES)
    assert bad == 0


def test_real_date_convention_invariance(real):
    ts = real["sub"].copy()
    ts["date"] = ts.groupby(["tour", "tid", "stage"])["date"].transform("min")    # pre-2026 convention
    n, _ = frames_equal(real["base"], F.build_training_table(ts))
    assert n == 0


def test_real_no_leak_signature(real):
    """Recent-activity counts legitimately carry signal (winners keep playing): hard cap AUC 0.66 (market ~0.75).
    The old leak made 'matches this event' favour the eventual winner; without it, it must not."""
    t = real["base"]
    t = t[(t.date >= "2025-01-01") & ~t.walkover]

    def auc(x, y):
        ok = x.notna()
        x, y = x[ok], y[ok]
        r = x.rank()
        n1 = y.sum()
        n0 = len(y) - n1
        return float((r[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))
    aucs = {k: auc(t[f"d_{k}"], t["won"]) for k in F.PLAYER_FEATURES}
    assert all(0.34 <= v <= 0.66 for v in aucs.values()), aucs
    assert max(aucs[k] for k in ("ev_matches_before", "ev_sets_before", "ev_games_before")) <= 0.52, aucs


def test_real_parity_live_equals_training(real):
    n = int(os.environ.get("V5_FATIGUE_PARITY_N", "60"))
    res = V.run_parity(real["m"], real["fixtures"], n=n, progress=True)
    print({k: v for k, v in res.items() if not k.endswith("examples")})
    assert res["mismatched"] == 0, res["mismatch_examples"][:5]
    assert res["identical"] >= 0.8 * n
    assert res["full_checked"] == 0 or res["full_identical"] == res["full_checked"]


def test_real_ordering_matches_clock_times(real):
    res = V.clock_check(real["m"], real["fixtures"])
    assert res["pairs"] > 10000
    assert res["leak_risk"] == 0, res["leak_examples"][:10]
