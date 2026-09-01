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


def test_future_match_does_not_change_earlier_features():
    base = build_workload_features(_rows())
    future = pd.concat([_rows(), pd.DataFrame([{
        "match_id":"m4","player_name":"A","match_date":"2026-02-01","match_games":40,"match_sets":3,
        "match_duration_minutes":200,"best_of":3,"round":"F"
    }])], ignore_index=True)
    extended = build_workload_features(future)
    cols = [c for c in base.columns if c.startswith(("rest_","matches_last_","games_last_","sets_last_","minutes_last_","consecutive_"))]
    pd.testing.assert_frame_equal(base[cols].reset_index(drop=True), extended.iloc[:len(base)][cols].reset_index(drop=True))


def test_missing_duration_is_not_treated_as_zero_observation():
    out = build_workload_features(_rows())
    assert out.iloc[2]["duration_quality"] == "prior_partial"
    assert pd.isna(out.iloc[0]["minutes_last_7d"])
