import numpy as np
import pandas as pd

from v5_rolling_stats import build_rolling_stats


def _rows():
    return pd.DataFrame([
        {"match_id":"m1","player_name":"A","opponent_name":"B","match_date":"2026-01-01","surface":"Hard","stat_aces":10,"stat_double_faults":2,"stat_service_points":60,"stat_first_serves_in":36,"stat_first_serve_points_won":28,"stat_second_serve_points_won":12,"stat_break_points_saved":3,"stat_break_points_faced":5},
        {"match_id":"m2","player_name":"A","opponent_name":"C","match_date":"2026-01-08","surface":"Hard","stat_aces":5,"stat_double_faults":4,"stat_service_points":70,"stat_first_serves_in":42,"stat_first_serve_points_won":30,"stat_second_serve_points_won":11,"stat_break_points_saved":4,"stat_break_points_faced":7},
        {"match_id":"m3","player_name":"A","opponent_name":"D","match_date":"2026-01-15","surface":"Clay","stat_aces":2,"stat_double_faults":3,"stat_service_points":65,"stat_first_serves_in":40,"stat_first_serve_points_won":25,"stat_second_serve_points_won":10,"stat_break_points_saved":5,"stat_break_points_faced":8},
    ])


def test_first_match_has_no_prior_stat_state_and_second_uses_only_first():
    out = build_rolling_stats(_rows())
    assert pd.isna(out.iloc[0]["rolling_ace_rate"])
    assert np.isclose(out.iloc[1]["rolling_ace_rate"], 10 / 60)
    assert np.isclose(out.iloc[1]["rolling_double_fault_rate"], 2 / 60)
    assert np.isclose(out.iloc[1]["rolling_first_serve_in_pct"], 36 / 60)
    assert np.isclose(out.iloc[1]["rolling_first_serve_points_won_pct"], 28 / 36)
    assert np.isclose(out.iloc[1]["rolling_second_serve_points_won_pct"], 12 / 24)
    assert np.isclose(out.iloc[1]["rolling_bp_save_pct"], 3 / 5)


def test_surface_state_uses_only_prior_matches_on_that_surface():
    out = build_rolling_stats(_rows())
    third = out.iloc[2]
    assert np.isclose(third["surface_ace_rate"], 15 / 130)
    assert third["surface_effective_service_points"] == 130


def test_appending_future_match_does_not_change_earlier_rolling_features():
    base = build_rolling_stats(_rows())
    future = pd.concat([_rows(), pd.DataFrame([{"match_id":"m4","player_name":"A","opponent_name":"E","match_date":"2026-02-01","surface":"Hard","stat_aces":30,"stat_double_faults":0,"stat_service_points":50,"stat_first_serves_in":40,"stat_first_serve_points_won":38,"stat_second_serve_points_won":9,"stat_break_points_saved":2,"stat_break_points_faced":2}])], ignore_index=True)
    extended = build_rolling_stats(future)
    cols = [c for c in base.columns if c.startswith(("rolling_","surface_","stat_uncertainty_"))]
    pd.testing.assert_frame_equal(base[cols], extended.iloc[:3][cols].reset_index(drop=True), check_dtype=False)


def test_uncertainty_decreases_with_more_prior_service_points():
    out = build_rolling_stats(_rows())
    assert out.iloc[2]["stat_uncertainty_service"] < out.iloc[1]["stat_uncertainty_service"]
