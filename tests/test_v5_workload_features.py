import pandas as pd
import numpy as np

from v5_workload_features import build_workload_features


def _rows():
    return pd.DataFrame([
        {"match_id":"m1","player_name":"A","match_date":"2026-01-01","match_games":20,"match_sets":2,"match_duration_minutes":90,"best_of":3,"round":"R32"},
        {"match_id":"m2","player_name":"A","match_date":"2026-01-04","match_games":30,"match_sets":3,"match_duration_minutes":150,"best_of":3,"round":"R16"},
        {"match_id":"m3","player_name":"A","match_date":"2026-01-05","match_games":24,"match_sets":2,"match_duration_minutes":np.nan,"best_of":3,"round":"QF"},
    ])


def test_workload_uses_only_prior_matches():
    out = build_workload_features(_rows())
    first = out.iloc[0]
    second = out.iloc[1]
    third = out.iloc[2]
    assert pd.isna(first["rest_days"])
    assert second["rest_days"] == 3
    assert second["matches_last_3d"] == 1
    assert second["games_last_7d"] == 20
    assert third["rest_days"] == 1
    assert third["matches_last_7d"] == 2
    assert third["games_last_7d"] == 50
    assert third["minutes_last_7d"] == 240
    # The target match's own missing duration is not allowed to contaminate its pre-match state.
    assert third["duration_quality"] == "prior_complete"


def test_future_match_does_not_change_earlier_features():
    base = build_workload_features(_rows())
    future = pd.concat([_rows(), pd.DataFrame([{
        "match_id":"m4","player_name":"A","match_date":"2026-02-01","match_games":40,"match_sets":3,
        "match_duration_minutes":200,"best_of":3,"round":"F"
    }])], ignore_index=True)
    extended = build_workload_features(future)
    cols = [c for c in base.columns if c.startswith(("rest_","matches_last_","games_last_","sets_last_","minutes_last_","consecutive_","layoff_","matches_since_"))]
    pd.testing.assert_frame_equal(base[cols].reset_index(drop=True), extended.iloc[:len(base)][cols].reset_index(drop=True))


def test_missing_prior_duration_is_not_treated_as_zero_observation():
    fourth = pd.DataFrame([{
        "match_id":"m4","player_name":"A","match_date":"2026-01-06","match_games":18,"match_sets":2,
        "match_duration_minutes":100,"best_of":3,"round":"SF"
    }])
    out = build_workload_features(pd.concat([_rows(), fourth], ignore_index=True))
    assert out.iloc[3]["duration_quality"] == "prior_partial"
    # Missing m3 duration is omitted, never silently turned into zero minutes.
    assert out.iloc[3]["minutes_last_7d"] == 240
    assert pd.isna(out.iloc[0]["minutes_last_7d"])


def test_rest_is_represented_as_nonlinear_layoff_state_not_only_raw_days():
    rows = pd.DataFrame([
        {"match_id":"a1","player_name":"A","match_date":"2025-01-01","match_games":20,"match_sets":2},
        {"match_id":"a2","player_name":"A","match_date":"2025-01-03","match_games":20,"match_sets":2},
        {"match_id":"a3","player_name":"A","match_date":"2025-04-15","match_games":20,"match_sets":2},
        {"match_id":"a4","player_name":"A","match_date":"2025-04-17","match_games":20,"match_sets":2},
        {"match_id":"a5","player_name":"A","match_date":"2025-04-20","match_games":20,"match_sets":2},
    ])
    out = build_workload_features(rows)
    comeback = out.iloc[2]
    second_back = out.iloc[3]
    third_back = out.iloc[4]

    assert comeback["rest_days"] == 102
    assert np.isclose(comeback["rest_log1p"], np.log1p(102))
    assert comeback["layoff_60d"] == 1
    assert comeback["layoff_90d"] == 1
    assert comeback["first_match_after_60d"] == 1
    assert comeback["matches_since_60d_layoff"] == 0

    assert second_back["first_match_after_60d"] == 0
    assert second_back["matches_since_60d_layoff"] == 1
    assert third_back["matches_since_60d_layoff"] == 2


def test_rest_bucket_is_monotonic_but_does_not_make_180_days_twice_90_days():
    rows = pd.DataFrame([
        {"match_id":"b1","player_name":"B","match_date":"2025-01-01"},
        {"match_id":"b2","player_name":"B","match_date":"2025-04-01"},
        {"match_id":"c1","player_name":"C","match_date":"2025-01-01"},
        {"match_id":"c2","player_name":"C","match_date":"2025-06-30"},
    ])
    out = build_workload_features(rows)
    b = out[(out.player_name == "B") & (out.match_id == "b2")].iloc[0]
    c = out[(out.player_name == "C") & (out.match_id == "c2")].iloc[0]
    assert b["rest_bucket"] == 7
    assert c["rest_bucket"] == 7
    assert c["rest_log1p"] > b["rest_log1p"]
    assert c["rest_log1p"] < 2.0 * b["rest_log1p"]
