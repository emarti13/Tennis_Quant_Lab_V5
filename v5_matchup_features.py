from __future__ import annotations

import math

import pandas as pd


def _f(mapping: dict, key: str, default=float("nan")) -> float:
    value = mapping.get(key, default)
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return float(parsed) if pd.notna(parsed) else float("nan")


def _safe(value: float, default: float = 0.0) -> float:
    return value if math.isfinite(value) else default


def _diff(a: dict, b: dict, key: str) -> float:
    av, bv = _f(a, key), _f(b, key)
    if not math.isfinite(av) or not math.isfinite(bv):
        return float("nan")
    return av - bv


def _serve_dominance(state: dict) -> float:
    first = _safe(_f(state, "serve_first_won"), 0.67)
    second = _safe(_f(state, "serve_second_won"), 0.50)
    ace = _safe(_f(state, "ace_rate"), 0.07)
    df = _safe(_f(state, "double_fault_rate"), 0.04)
    return (first - 0.67) + 0.8 * (second - 0.50) + 0.8 * (ace - 0.07) - 0.5 * (df - 0.04)


def _return_dominance(state: dict) -> float:
    return _safe(_f(state, "return_strength"), 0.40) - 0.40


def _serve_dependence(state: dict) -> float:
    return _serve_dominance(state) - _return_dominance(state)


def _second_serve_vulnerability(server: dict, returner: dict) -> float:
    second = _safe(_f(server, "serve_second_won"), 0.50)
    return_strength = _safe(_f(returner, "return_strength"), 0.40)
    return (0.55 - second) * return_strength


def _comeback_recency(state: dict, threshold: int) -> float:
    matches_since = _f(state, f"matches_since_{threshold}d_layoff")
    if not math.isfinite(matches_since) or matches_since < 0:
        return 0.0
    # First match back = 1.0, then decays rapidly without assuming a permanent penalty.
    return 1.0 / (1.0 + float(matches_since))


def build_matchup_features(state_a: dict, state_b: dict, context: dict) -> dict[str, float]:
    """Build signed, leak-safe matchup and environment interactions.

    Rest is deliberately nonlinear. Raw rest days are retained in player state for audit and
    interactions, but are not emitted as a direct linear feature. This prevents a 180-day
    absence from mechanically counting as twice a 90-day absence while still preserving
    short-rest fatigue and layoff/comeback information.
    """
    serve_a, serve_b = _serve_dominance(state_a), _serve_dominance(state_b)
    return_a, return_b = _return_dominance(state_a), _return_dominance(state_b)
    dependence_a, dependence_b = _serve_dependence(state_a), _serve_dependence(state_b)

    court_speed = _safe(_f(context, "court_speed"), 0.0)
    altitude_m = _safe(_f(context, "altitude_m"), 0.0)
    temp_c = _safe(_f(context, "weather_temperature_c"), 25.0)
    humidity = _safe(_f(context, "weather_humidity_pct"), 50.0)
    wind = _safe(_f(context, "weather_wind_speed_kmh"), 0.0)
    heat_load = max(temp_c - 25.0, 0.0)
    humidity_load = max(humidity - 55.0, 0.0) / 20.0

    workload_a = _safe(_f(state_a, "fatigue_matches_7d"), 0.0)
    workload_b = _safe(_f(state_b, "fatigue_matches_7d"), 0.0)
    games_a = _safe(_f(state_a, "fatigue_games_7d"), 0.0)
    games_b = _safe(_f(state_b, "fatigue_games_7d"), 0.0)
    rest_a = _f(state_a, "rest_days")
    rest_b = _f(state_b, "rest_days")
    short_rest_a = 0.0 if not math.isfinite(rest_a) else 1.0 / max(rest_a, 0.5)
    short_rest_b = 0.0 if not math.isfinite(rest_b) else 1.0 / max(rest_b, 0.5)

    out = {
        "serve_first_won_diff": _diff(state_a, state_b, "serve_first_won"),
        "serve_second_won_diff": _diff(state_a, state_b, "serve_second_won"),
        "ace_rate_diff": _diff(state_a, state_b, "ace_rate"),
        "double_fault_rate_diff": _diff(state_a, state_b, "double_fault_rate"),
        "return_strength_diff": _diff(state_a, state_b, "return_strength"),

        # Nonlinear rest/layoff state.
        "rest_log1p_diff": _diff(state_a, state_b, "rest_log1p"),
        "rest_bucket_diff": _diff(state_a, state_b, "rest_bucket"),
        "short_rest_0d_diff": _diff(state_a, state_b, "short_rest_0d"),
        "short_rest_1d_diff": _diff(state_a, state_b, "short_rest_1d"),
        "short_rest_2d_diff": _diff(state_a, state_b, "short_rest_2d"),
        "rest_3_to_7d_diff": _diff(state_a, state_b, "rest_3_to_7d"),
        "layoff_30d_diff": _diff(state_a, state_b, "layoff_30d"),
        "layoff_60d_diff": _diff(state_a, state_b, "layoff_60d"),
        "layoff_90d_diff": _diff(state_a, state_b, "layoff_90d"),
        "first_match_after_30d_diff": _diff(state_a, state_b, "first_match_after_30d"),
        "first_match_after_60d_diff": _diff(state_a, state_b, "first_match_after_60d"),
        "first_match_after_90d_diff": _diff(state_a, state_b, "first_match_after_90d"),
        "comeback_recency_30d_diff": _comeback_recency(state_a, 30) - _comeback_recency(state_b, 30),
        "comeback_recency_60d_diff": _comeback_recency(state_a, 60) - _comeback_recency(state_b, 60),
        "comeback_recency_90d_diff": _comeback_recency(state_a, 90) - _comeback_recency(state_b, 90),

        # Workload at multiple horizons and immediate previous-match cost.
        "consecutive_play_days_diff": _diff(state_a, state_b, "consecutive_play_days"),
        "previous_match_games_diff": _diff(state_a, state_b, "previous_match_games"),
        "previous_match_duration_diff": _diff(state_a, state_b, "previous_match_duration"),
        "matches_3d_diff": _diff(state_a, state_b, "fatigue_matches_3d"),
        "games_3d_diff": _diff(state_a, state_b, "fatigue_games_3d"),
        "matches_7d_diff": _diff(state_a, state_b, "fatigue_matches_7d"),
        "games_7d_diff": _diff(state_a, state_b, "fatigue_games_7d"),
        "minutes_7d_diff": _diff(state_a, state_b, "fatigue_minutes_7d"),
        "matches_14d_diff": _diff(state_a, state_b, "fatigue_matches_14d"),
        "games_14d_diff": _diff(state_a, state_b, "fatigue_games_14d"),
        "matches_30d_diff": _diff(state_a, state_b, "fatigue_matches_30d"),
        "games_30d_diff": _diff(state_a, state_b, "fatigue_games_30d"),

        "travel_km_diff": _diff(state_a, state_b, "travel_km"),
        "timezone_change_abs_diff": abs(_safe(_f(state_a, "timezone_change_hours"), 0.0)) - abs(_safe(_f(state_b, "timezone_change_hours"), 0.0)),
        "state_uncertainty_diff": _diff(state_a, state_b, "state_uncertainty"),
        "context_quality_diff": _diff(state_a, state_b, "context_quality"),
        "serve_dominance_diff": serve_a - serve_b,
        "return_dominance_diff": return_a - return_b,
        "serve_dependence_diff": dependence_a - dependence_b,
        "big_server_x_fast_court": (serve_a - serve_b) * max(court_speed, 0.0),
        "big_server_x_slow_court": -(serve_a - serve_b) * max(-court_speed, 0.0),
        "big_server_x_altitude": (serve_a - serve_b) * (altitude_m / 1000.0),
        "weak_second_serve_x_elite_returner": _second_serve_vulnerability(state_a, state_b) - _second_serve_vulnerability(state_b, state_a),
        "workload_x_heat_diff": (workload_a - workload_b) * heat_load,
        "games_load_x_heat_diff": ((games_a - games_b) / 50.0) * heat_load,
        "workload_x_humidity_diff": (workload_a - workload_b) * humidity_load,
        "short_rest_x_heat_diff": (short_rest_a - short_rest_b) * heat_load,
        "serve_dependence_x_wind_diff": (dependence_a - dependence_b) * (wind / 20.0),
        "court_speed_x_return_dominance_diff": (return_a - return_b) * court_speed,
        "court_speed_x_serve_dominance_diff": (serve_a - serve_b) * court_speed,
        "trajectory_serve_diff": _diff(state_a, state_b, "trajectory_serve"),
        "trajectory_return_diff": _diff(state_a, state_b, "trajectory_return"),
        "rank_diff": _diff(state_a, state_b, "player_rank"),
    }

    travel_a = _safe(_f(state_a, "travel_km"), 0.0)
    travel_b = _safe(_f(state_b, "travel_km"), 0.0)
    recovery_a = max(_safe(rest_a, 0.0), 0.5)
    recovery_b = max(_safe(rest_b, 0.0), 0.5)
    out["travel_per_rest_day_diff"] = travel_a / recovery_a - travel_b / recovery_b

    altitude_change_a = abs(_safe(_f(state_a, "altitude_change_m"), 0.0))
    altitude_change_b = abs(_safe(_f(state_b, "altitude_change_m"), 0.0))
    out["altitude_change_x_short_rest_diff"] = altitude_change_a * short_rest_a - altitude_change_b * short_rest_b

    return out
