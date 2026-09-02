import math
import numpy as np
import pandas as pd

from v5_player_state import build_player_state, regularized_slope


def test_regularized_slope_is_zero_with_insufficient_history_and_shrinks_small_samples():
    assert regularized_slope([1.0]) == 0.0
    small = regularized_slope([0.50, 0.60], shrink_matches=8)
    large = regularized_slope([0.50, 0.52, 0.54, 0.56, 0.58, 0.60, 0.62, 0.64], shrink_matches=8)
    assert small > 0
    assert large > small


def test_player_state_collects_context_without_market_inputs():
    row = pd.Series({
        "rolling_first_serve_points_won_pct": 0.74,
        "rolling_second_serve_points_won_pct": 0.54,
        "rolling_ace_rate": 0.12,
        "rolling_double_fault_rate": 0.03,
        "surface_first_serve_points_won_pct": 0.72,
        "surface_second_serve_points_won_pct": 0.52,
        "rest_days": 2,
        "rest_log1p": np.log1p(2),
        "rest_bucket": 2,
        "layoff_60d": 0,
        "layoff_90d": 0,
        "first_match_after_60d": 0,
        "matches_since_60d_layoff": np.nan,
        "matches_last_7d": 4,
        "games_last_7d": 96,
        "minutes_last_7d": 520,
        "travel_km_from_previous_event": 4100,
        "timezone_change_hours": 5,
        "altitude_change_m": 600,
        "weather_temperature_c": 31,
        "weather_humidity_pct": 72,
        "weather_wind_speed_kmh": 18,
        "court_speed_blended": 0.35,
        "court_speed_blended_uncertainty": 0.12,
        "stat_uncertainty_service": 0.04,
        "player_rank": 25,
        "sportsbook_probability": 0.20,
        "market_price": 5.0,
    })
    state = build_player_state(row)
    assert state["state_version"] == "v5-player-state-2"
    assert state["serve_first_won"] == 0.74
    assert state["fatigue_matches_7d"] == 4
    assert state["travel_km"] == 4100
    assert state["court_speed"] == 0.35
    assert state["rest_log1p"] == np.log1p(2)
    assert state["rest_bucket"] == 2
    assert state["layoff_60d"] == 0
    assert "sportsbook_probability" not in state
    assert "market_price" not in state


def test_missing_context_stays_missing_and_quality_reports_it():
    state = build_player_state(pd.Series({"rolling_ace_rate": 0.08}))
    assert math.isnan(state["rest_days"])
    assert state["missing_feature_count"] > 0
    assert 0 <= state["context_quality"] < 1


def test_uncertainty_increases_with_sparse_or_uncertain_inputs():
    dense = build_player_state(pd.Series({
        "stat_uncertainty_service": 0.03,
        "court_speed_blended_uncertainty": 0.05,
        "rolling_effective_service_points": 500,
        "surface_effective_service_points": 250,
    }))
    sparse = build_player_state(pd.Series({
        "stat_uncertainty_service": 0.15,
        "court_speed_blended_uncertainty": 0.30,
        "rolling_effective_service_points": 40,
        "surface_effective_service_points": 0,
    }))
    assert sparse["state_uncertainty"] > dense["state_uncertainty"]
