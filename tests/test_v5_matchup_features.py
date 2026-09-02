import math

from v5_matchup_features import build_matchup_features


def _state(**overrides):
    base = {
        "serve_first_won": 0.70,
        "serve_second_won": 0.52,
        "ace_rate": 0.10,
        "double_fault_rate": 0.03,
        "return_strength": 0.40,
        "surface_serve_first_won": 0.69,
        "surface_serve_second_won": 0.51,
        "rest_days": 3.0,
        "rest_log1p": math.log1p(3.0),
        "rest_bucket": 3.0,
        "short_rest_0d": 0.0,
        "short_rest_1d": 0.0,
        "short_rest_2d": 0.0,
        "layoff_30d": 0.0,
        "layoff_60d": 0.0,
        "layoff_90d": 0.0,
        "first_match_after_60d": 0.0,
        "matches_since_60d_layoff": float("nan"),
        "consecutive_play_days": 0.0,
        "previous_match_games": 22.0,
        "previous_match_duration": 105.0,
        "fatigue_matches_3d": 1.0,
        "fatigue_games_3d": 22.0,
        "fatigue_matches_7d": 2.0,
        "fatigue_games_7d": 48.0,
        "fatigue_minutes_7d": 240.0,
        "fatigue_matches_14d": 3.0,
        "fatigue_games_14d": 70.0,
        "fatigue_matches_30d": 5.0,
        "fatigue_games_30d": 115.0,
        "travel_km": 500.0,
        "timezone_change_hours": 1.0,
        "altitude_change_m": 50.0,
        "state_uncertainty": 0.08,
        "context_quality": 0.9,
        "player_rank": 30.0,
        "trajectory_serve": 0.01,
        "trajectory_return": 0.00,
    }
    base.update(overrides)
    return base


def test_signed_state_differences_reverse_when_players_swap():
    a = _state(ace_rate=0.15, return_strength=0.35, rest_days=2, rest_log1p=math.log1p(2), rest_bucket=2)
    b = _state(ace_rate=0.05, return_strength=0.45, rest_days=5, rest_log1p=math.log1p(5), rest_bucket=3)
    ctx = {"court_speed": 0.4, "altitude_m": 700, "weather_temperature_c": 32, "weather_humidity_pct": 70, "weather_wind_speed_kmh": 20}
    ab = build_matchup_features(a, b, ctx)
    ba = build_matchup_features(b, a, ctx)
    for key in ["ace_rate_diff", "return_strength_diff", "rest_log1p_diff", "rest_bucket_diff", "state_uncertainty_diff", "serve_dominance_diff"]:
        assert math.isclose(ab[key], -ba[key], rel_tol=1e-12, abs_tol=1e-12)
    assert "rest_days_diff" not in ab


def test_layoff_state_distinguishes_first_match_back_from_normal_long_rest():
    comeback = _state(
        rest_days=100,
        rest_log1p=math.log1p(100),
        rest_bucket=7,
        layoff_60d=1,
        layoff_90d=1,
        first_match_after_60d=1,
        matches_since_60d_layoff=0,
    )
    established = _state(rest_days=5, rest_log1p=math.log1p(5), rest_bucket=3)
    out = build_matchup_features(comeback, established, {})
    assert out["layoff_60d_diff"] == 1
    assert out["layoff_90d_diff"] == 1
    assert out["first_match_after_60d_diff"] == 1
    assert out["comeback_recency_60d_diff"] > 0


def test_environment_interactions_capture_tennis_specific_matchup_geometry():
    server = _state(ace_rate=0.18, serve_first_won=0.78, serve_second_won=0.58, return_strength=0.30, fatigue_matches_7d=4, rest_days=1, rest_log1p=math.log1p(1), short_rest_1d=1)
    returner = _state(ace_rate=0.04, serve_first_won=0.64, serve_second_won=0.45, return_strength=0.50, fatigue_matches_7d=1, rest_days=4, rest_log1p=math.log1p(4))
    ctx = {"court_speed": 0.6, "altitude_m": 1200, "weather_temperature_c": 34, "weather_humidity_pct": 75, "weather_wind_speed_kmh": 25}
    out = build_matchup_features(server, returner, ctx)
    assert out["big_server_x_fast_court"] > 0
    assert out["big_server_x_altitude"] > 0
    assert out["weak_second_serve_x_elite_returner"] < 0
    assert out["workload_x_heat_diff"] > 0
    assert out["short_rest_x_heat_diff"] > 0
    assert out["serve_dependence_x_wind_diff"] > 0


def test_market_fields_are_not_emitted_even_if_context_contains_them():
    ctx = {"court_speed": 0.1, "market_probability": 0.8, "odds": -400, "sportsbook_line": -4.5}
    out = build_matchup_features(_state(), _state(), ctx)
    forbidden = {"market_probability", "odds", "sportsbook_line"}
    assert not forbidden.intersection(out)
