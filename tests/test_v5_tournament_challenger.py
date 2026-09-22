import numpy as np
import pandas as pd

from v5_tournament_challenger import add_authority_features, fit_ball_categories, non_court_context_columns


def test_non_court_control_excludes_retired_environment_and_travel_features():
    frame = pd.DataFrame(columns=[
        "ctx_serve_dominance_diff",
        "ctx_rank_diff",
        "ctx_rest_log1p_diff",
        "ctx_big_server_x_altitude",
        "ctx_court_speed_x_serve_dominance_diff",
        "ctx_altitude_change_x_short_rest_diff",
        "ctx_travel_km_diff",
        "ctx_weather_temperature_diff",
    ])
    got = non_court_context_columns(frame)
    assert "ctx_serve_dominance_diff" in got
    assert "ctx_rank_diff" in got
    assert "ctx_rest_log1p_diff" in got
    assert "ctx_big_server_x_altitude" not in got
    assert "ctx_court_speed_x_serve_dominance_diff" not in got
    assert "ctx_altitude_change_x_short_rest_diff" not in got
    assert "ctx_travel_km_diff" not in got
    assert "ctx_weather_temperature_diff" not in got


def test_authority_features_use_neutral_zero_for_missing_values_and_signed_interactions():
    frame = pd.DataFrame([
        {
            "ctx_serve_dominance_diff": 0.2,
            "ctx_return_dominance_diff": -0.1,
            "ctx_serve_dependence_diff": 0.3,
            "authority_altitude_m": 1000,
            "authority_setting": "Indoor",
            "authority_cpi": 40,
            "authority_ta": 1.2,
            "authority_ball_model": "Dunlop ATP Extra Duty",
        },
        {
            "ctx_serve_dominance_diff": -0.2,
            "ctx_return_dominance_diff": 0.1,
            "ctx_serve_dependence_diff": -0.3,
            "authority_altitude_m": np.nan,
            "authority_setting": None,
            "authority_cpi": np.nan,
            "authority_ta": np.nan,
            "authority_ball_model": None,
        },
    ])
    out = add_authority_features(frame, ball_categories=["Dunlop ATP Extra Duty"])
    assert np.isclose(out.loc[0, "ctx_auth_altitude_x_serve_dom"], 0.2)
    assert np.isclose(out.loc[0, "ctx_auth_indoor_x_serve_dep"], 0.3)
    assert np.isclose(out.loc[0, "ctx_auth_cpi_x_serve_dom"], 0.1)
    assert np.isclose(out.loc[0, "ctx_auth_ta_x_return_dom"], -0.02)
    assert np.isclose(out.loc[0, "ctx_auth_ball_dunlop_atp_extra_duty_x_serve_dep"], 0.3)
    assert out.loc[1, "ctx_auth_altitude_x_serve_dom"] == 0.0
    assert out.loc[1, "ctx_auth_cpi_x_serve_dom"] == 0.0
    assert out.loc[1, "ctx_auth_ball_dunlop_atp_extra_duty_x_serve_dep"] == 0.0


def test_ball_categories_are_fit_from_2025_only():
    frame = pd.DataFrame([
        {"year": 2025, "authority_ball_model": "Ball A"},
        {"year": 2025, "authority_ball_model": "Ball A"},
        {"year": 2025, "authority_ball_model": "Ball B"},
        {"year": 2026, "authority_ball_model": "Future Ball"},
        {"year": 2026, "authority_ball_model": "Future Ball"},
    ])
    assert fit_ball_categories(frame, fit_year=2025, min_rows=2) == ["Ball A"]
