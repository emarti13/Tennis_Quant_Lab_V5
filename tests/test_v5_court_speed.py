import pandas as pd
import numpy as np

from v5_court_speed import blend_estimates, build_court_speed_features, add_derived_court_speed_features


def _matches():
    return pd.DataFrame([
        # Historical same event
        {"match_id":"h1","canonical_event_id":"event_a","tour":"MEN","surface":"Hard","indoor":False,"match_start":"2024-08-20 12:00:00+00:00","speed_residual":0.40},
        {"match_id":"h2","canonical_event_id":"event_a","tour":"MEN","surface":"Hard","indoor":False,"match_start":"2025-08-20 12:00:00+00:00","speed_residual":0.60},
        # Comparable cohort history
        {"match_id":"c1","canonical_event_id":"other_hard","tour":"MEN","surface":"Hard","indoor":False,"match_start":"2025-07-01 12:00:00+00:00","speed_residual":0.10},
        # Current event, chronological
        {"match_id":"a1","canonical_event_id":"event_a","tour":"MEN","surface":"Hard","indoor":False,"match_start":"2026-08-20 10:00:00+00:00","speed_residual":0.90},
        {"match_id":"a2","canonical_event_id":"event_a","tour":"MEN","surface":"Hard","indoor":False,"match_start":"2026-08-20 14:00:00+00:00","speed_residual":0.70},
        {"match_id":"a3","canonical_event_id":"event_a","tour":"MEN","surface":"Hard","indoor":False,"match_start":"2026-08-21 10:00:00+00:00","speed_residual":0.80},
    ])


def test_precision_blend_moves_toward_more_precise_estimate():
    mean, uncertainty = blend_estimates(0.2, 0.5, 0.8, 0.1)
    assert mean > 0.6
    assert uncertainty < 0.5


def test_first_current_event_match_has_historical_prior_but_no_current_event_data():
    out = build_court_speed_features(_matches())
    a1 = out.loc[out.match_id == "a1"].iloc[0]
    assert a1["court_speed_historical_sample_size"] == 2
    assert 0.4 < a1["court_speed_historical_prior"] < 0.61
    assert a1["court_speed_current_event_sample_size"] == 0
    assert pd.isna(a1["court_speed_current_event"])
    assert np.isclose(a1["court_speed_blended"], a1["court_speed_historical_prior"])


def test_current_event_and_day_updates_use_only_matches_before_target_start():
    out = build_court_speed_features(_matches())
    a2 = out.loc[out.match_id == "a2"].iloc[0]
    assert a2["court_speed_current_event_sample_size"] == 1
    assert a2["court_speed_current_day_sample_size"] == 1
    assert np.isclose(a2["court_speed_current_event"], 0.90)

    a3 = out.loc[out.match_id == "a3"].iloc[0]
    assert a3["court_speed_current_event_sample_size"] == 2
    assert a3["court_speed_current_day_sample_size"] == 0
    assert np.isclose(a3["court_speed_current_event"], 0.80)


def test_appending_later_match_does_not_change_earlier_court_speed_features():
    base = build_court_speed_features(_matches())
    later = pd.concat([_matches(), pd.DataFrame([{
        "match_id":"future","canonical_event_id":"event_a","tour":"MEN","surface":"Hard","indoor":False,
        "match_start":"2026-08-22 12:00:00+00:00","speed_residual":-2.0
    }])], ignore_index=True)
    extended = build_court_speed_features(later)
    cols = [c for c in base.columns if c.startswith("court_speed_")]
    pd.testing.assert_frame_equal(
        base.sort_values("match_id")[cols].reset_index(drop=True),
        extended[extended.match_id.isin(base.match_id)].sort_values("match_id")[cols].reset_index(drop=True),
        check_dtype=False,
    )


def _player_rows_for_derived_speed():
    rows = []
    for match_id, date, p1, p2, p1_ace, p2_ace in [
        ("h", "2025-08-20", "A", "B", 12, 10),
        ("c1", "2026-08-20", "A", "C", 14, 12),
        ("c2", "2026-08-21", "B", "C", 8, 7),
    ]:
        for player, opponent, ace in [(p1, p2, p1_ace), (p2, p1, p2_ace)]:
            rows.append({
                "match_id": match_id,
                "match_date": date,
                "tour": "MEN",
                "surface": "Hard",
                "tourney_name": "Example Open",
                "player_name": player,
                "opponent_name": opponent,
                "stat_service_points": 60,
                "stat_first_serves_in": 36,
                "stat_first_serve_points_won": 27,
                "stat_second_serve_points_won": 12,
                "stat_aces": ace,
                "stat_double_faults": 2,
                "stat_return_points_total": 60,
                "stat_return_points_won": 21,
                "rolling_first_serve_in_pct": 0.60,
                "rolling_first_serve_points_won_pct": 0.70,
                "rolling_second_serve_points_won_pct": 0.50,
                "rolling_ace_rate": 0.10,
                "rolling_double_fault_rate": 0.04,
                "rolling_return_points_won_pct": 0.36,
            })
    return pd.DataFrame(rows)


def test_derived_court_speed_starts_from_historical_event_prior_and_is_shared_by_match():
    out = add_derived_court_speed_features(_player_rows_for_derived_speed())
    current_first = out[out.match_id == "c1"]
    assert len(current_first) == 2
    assert current_first["court_speed_historical_sample_size"].iloc[0] == 1
    assert current_first["court_speed_historical_prior"].notna().all()
    assert current_first["court_speed_blended"].nunique(dropna=False) == 1
    # Match c1 cannot use its own stats to price itself.
    assert current_first["court_speed_current_event_sample_size"].iloc[0] == 0

    next_day = out[out.match_id == "c2"].iloc[0]
    assert next_day["court_speed_current_event_sample_size"] == 1


def test_same_date_matches_do_not_leak_into_each_other_without_known_start_times():
    rows = _player_rows_for_derived_speed()
    extra = rows[rows.match_id == "c1"].copy()
    extra["match_id"] = "c1b"
    extra["player_name"] = ["D", "E"]
    extra["opponent_name"] = ["E", "D"]
    rows = pd.concat([rows, extra], ignore_index=True)
    out = add_derived_court_speed_features(rows)
    c1 = out[out.match_id == "c1"].iloc[0]
    c1b = out[out.match_id == "c1b"].iloc[0]
    assert c1["court_speed_current_event_sample_size"] == 0
    assert c1b["court_speed_current_event_sample_size"] == 0
