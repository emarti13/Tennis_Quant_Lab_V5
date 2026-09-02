from __future__ import annotations

import math
from typing import Iterable

import numpy as np
import pandas as pd

STATE_VERSION = "v5-player-state-2"


def _float(value) -> float:
    if value is None or pd.isna(value):
        return float("nan")
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return float("nan")
    return parsed if math.isfinite(parsed) else float("nan")


def regularized_slope(values: Iterable[float], shrink_matches: float = 8.0) -> float:
    arr = np.asarray([_float(v) for v in values], dtype=float)
    arr = arr[np.isfinite(arr)]
    n = len(arr)
    if n < 2:
        return 0.0
    x = np.arange(n, dtype=float)
    x_centered = x - x.mean()
    denom = float(np.sum(x_centered ** 2))
    if denom <= 0:
        return 0.0
    slope_per_match = float(np.sum(x_centered * (arr - arr.mean())) / denom)
    end_to_end_trend = slope_per_match * float(n - 1)
    shrink = float(n / (n + max(float(shrink_matches), 0.0)))
    return end_to_end_trend * shrink


STATE_FIELD_MAP = {
    "serve_first_won": "rolling_first_serve_points_won_pct",
    "serve_second_won": "rolling_second_serve_points_won_pct",
    "ace_rate": "rolling_ace_rate",
    "double_fault_rate": "rolling_double_fault_rate",
    "return_strength": "rolling_return_points_won_pct",
    "surface_serve_first_won": "surface_first_serve_points_won_pct",
    "surface_serve_second_won": "surface_second_serve_points_won_pct",
    "rest_days": "rest_days",
    "rest_log1p": "rest_log1p",
    "rest_bucket": "rest_bucket",
    "short_rest_0d": "short_rest_0d",
    "short_rest_1d": "short_rest_1d",
    "short_rest_2d": "short_rest_2d",
    "rest_3_to_7d": "rest_3_to_7d",
    "layoff_30d": "layoff_30d",
    "layoff_60d": "layoff_60d",
    "layoff_90d": "layoff_90d",
    "first_match_after_30d": "first_match_after_30d",
    "first_match_after_60d": "first_match_after_60d",
    "first_match_after_90d": "first_match_after_90d",
    "matches_since_30d_layoff": "matches_since_30d_layoff",
    "matches_since_60d_layoff": "matches_since_60d_layoff",
    "matches_since_90d_layoff": "matches_since_90d_layoff",
    "consecutive_play_days": "consecutive_play_days",
    "previous_match_games": "previous_match_games",
    "previous_match_sets": "previous_match_sets",
    "previous_match_duration": "previous_match_duration",
    "fatigue_matches_3d": "matches_last_3d",
    "fatigue_games_3d": "games_last_3d",
    "fatigue_sets_3d": "sets_last_3d",
    "fatigue_minutes_3d": "minutes_last_3d",
    "fatigue_matches_7d": "matches_last_7d",
    "fatigue_games_7d": "games_last_7d",
    "fatigue_minutes_7d": "minutes_last_7d",
    "fatigue_sets_7d": "sets_last_7d",
    "fatigue_matches_14d": "matches_last_14d",
    "fatigue_games_14d": "games_last_14d",
    "fatigue_sets_14d": "sets_last_14d",
    "fatigue_minutes_14d": "minutes_last_14d",
    "fatigue_matches_30d": "matches_last_30d",
    "fatigue_games_30d": "games_last_30d",
    "fatigue_sets_30d": "sets_last_30d",
    "fatigue_minutes_30d": "minutes_last_30d",
    "travel_km": "travel_km_from_previous_event",
    "timezone_change_hours": "timezone_change_hours",
    "altitude_change_m": "altitude_change_m",
    "weather_temperature_c": "weather_temperature_c",
    "weather_humidity_pct": "weather_humidity_pct",
    "weather_wind_speed_kmh": "weather_wind_speed_kmh",
    "weather_wind_gust_kmh": "weather_wind_gust_kmh",
    "weather_precipitation_mm": "weather_precipitation_mm",
    "weather_dew_point_c": "weather_dew_point_c",
    "weather_pressure_hpa": "weather_pressure_hpa",
    "court_speed": "court_speed_blended",
    "court_speed_historical": "court_speed_historical_prior",
    "court_speed_current_event": "court_speed_current_event",
    "court_speed_delta_vs_historical": "court_speed_delta_vs_historical",
    "court_speed_uncertainty": "court_speed_blended_uncertainty",
    "service_uncertainty": "stat_uncertainty_service",
    "rolling_service_points": "rolling_effective_service_points",
    "surface_service_points": "surface_effective_service_points",
    "player_rank": "player_rank",
    "trajectory_serve": "trajectory_serve",
    "trajectory_return": "trajectory_return",
    "trajectory_elo": "trajectory_elo",
}

QUALITY_FIELDS = [
    "serve_first_won", "serve_second_won", "ace_rate", "double_fault_rate",
    "return_strength", "rest_log1p", "fatigue_matches_7d", "fatigue_games_7d",
    "travel_km", "timezone_change_hours", "weather_temperature_c", "weather_humidity_pct",
    "weather_wind_speed_kmh", "court_speed",
]


def _sample_uncertainty(points: float, scale: float) -> float:
    if not math.isfinite(points) or points <= 0:
        return scale
    return min(scale, 1.0 / math.sqrt(points))


def build_player_state(feature_row: pd.Series | dict) -> dict[str, float | str | int]:
    row = feature_row if isinstance(feature_row, dict) else feature_row
    state: dict[str, float | str | int] = {"state_version": STATE_VERSION}
    for output_name, source_name in STATE_FIELD_MAP.items():
        state[output_name] = _float(row.get(source_name))

    missing = sum(1 for key in QUALITY_FIELDS if not math.isfinite(float(state[key])))
    state["missing_feature_count"] = int(missing)
    state["context_quality"] = float(max(0.0, 1.0 - missing / len(QUALITY_FIELDS)))

    service_u = float(state["service_uncertainty"])
    court_u = float(state["court_speed_uncertainty"])
    roll_points = float(state["rolling_service_points"])
    surface_points = float(state["surface_service_points"])

    components = []
    components.append(service_u if math.isfinite(service_u) and service_u >= 0 else _sample_uncertainty(roll_points, 0.25))
    components.append(court_u if math.isfinite(court_u) and court_u >= 0 else 0.25)
    components.append(_sample_uncertainty(roll_points, 0.25))
    components.append(_sample_uncertainty(surface_points, 0.30))
    coverage_penalty = (1.0 - float(state["context_quality"])) * 0.20
    state["state_uncertainty"] = float(math.sqrt(sum(c * c for c in components) / len(components)) + coverage_penalty)

    return state


def add_trajectory_features(
    player_rows: pd.DataFrame,
    serve_col: str = "rolling_first_serve_points_won_pct",
    return_col: str = "rolling_return_points_won_pct",
    elo_col: str = "surface_elo",
    window: int = 8,
) -> pd.DataFrame:
    if player_rows is None or player_rows.empty:
        return player_rows.copy() if player_rows is not None else pd.DataFrame()
    df = player_rows.copy()
    df["_orig_order"] = np.arange(len(df))
    df["match_date"] = pd.to_datetime(df["match_date"], errors="coerce")
    output = []
    for _, group in df.sort_values(["player_name", "match_date", "_orig_order"], kind="stable").groupby("player_name", sort=False, dropna=False):
        history: list[dict] = []
        for idx, row in group.iterrows():
            recent = history[-int(window):]
            output.append({
                "_idx": idx,
                "trajectory_serve": regularized_slope([h.get(serve_col) for h in recent]),
                "trajectory_return": regularized_slope([h.get(return_col) for h in recent]),
                "trajectory_elo": regularized_slope([h.get(elo_col) for h in recent]),
            })
            history.append(row.to_dict())
    features = pd.DataFrame(output).set_index("_idx")
    for col in ("trajectory_serve", "trajectory_return", "trajectory_elo"):
        df[col] = features[col]
    return df.sort_values("_orig_order").drop(columns=["_orig_order"]).reset_index(drop=True)
