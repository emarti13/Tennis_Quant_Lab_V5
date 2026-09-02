from __future__ import annotations

import math
from collections import defaultdict

import numpy as np
import pandas as pd

STAT_COLS = [
    "stat_aces", "stat_double_faults", "stat_service_points", "stat_first_serves_in",
    "stat_first_serve_points_won", "stat_second_serve_points_won",
    "stat_break_points_saved", "stat_break_points_faced",
    "stat_return_points_total", "stat_return_points_won",
    "stat_break_points_opportunities", "stat_break_points_converted",
]


def _empty_accumulator() -> dict:
    return {"sums": defaultdict(float), "counts": defaultdict(int), "matches": 0}


def _value(row: pd.Series, col: str) -> float:
    value = row.get(col)
    if value is None or pd.isna(value):
        return float("nan")
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return float("nan")
    return parsed if math.isfinite(parsed) else float("nan")


def _update(acc: dict, row: pd.Series) -> None:
    acc["matches"] += 1
    for col in STAT_COLS:
        value = _value(row, col)
        if math.isfinite(value):
            acc["sums"][col] += value
            acc["counts"][col] += 1


def _sum(acc: dict, col: str) -> float:
    return float(acc["sums"][col]) if acc["counts"][col] > 0 else float("nan")


def _ratio(acc: dict, numerator: str, denominator: str) -> float:
    n, d = _sum(acc, numerator), _sum(acc, denominator)
    if not math.isfinite(n) or not math.isfinite(d) or d <= 0:
        return float("nan")
    return float(n / d)


def _state(acc: dict, prefix: str) -> dict[str, float]:
    if acc["matches"] == 0:
        return {
            f"{prefix}ace_rate": np.nan,
            f"{prefix}double_fault_rate": np.nan,
            f"{prefix}first_serve_in_pct": np.nan,
            f"{prefix}first_serve_points_won_pct": np.nan,
            f"{prefix}second_serve_points_won_pct": np.nan,
            f"{prefix}bp_save_pct": np.nan,
            f"{prefix}return_points_won_pct": np.nan,
            f"{prefix}bp_convert_pct": np.nan,
            f"{prefix}effective_service_points": 0.0,
            f"{prefix}effective_return_points": 0.0,
        }

    service_points = _sum(acc, "stat_service_points")
    first_in = _sum(acc, "stat_first_serves_in")
    second_won = _sum(acc, "stat_second_serve_points_won")
    second_attempts = service_points - first_in if math.isfinite(service_points) and math.isfinite(first_in) else float("nan")
    return_points = _sum(acc, "stat_return_points_total")

    return {
        f"{prefix}ace_rate": _ratio(acc, "stat_aces", "stat_service_points"),
        f"{prefix}double_fault_rate": _ratio(acc, "stat_double_faults", "stat_service_points"),
        f"{prefix}first_serve_in_pct": _ratio(acc, "stat_first_serves_in", "stat_service_points"),
        f"{prefix}first_serve_points_won_pct": _ratio(acc, "stat_first_serve_points_won", "stat_first_serves_in"),
        f"{prefix}second_serve_points_won_pct": (
            float(second_won / second_attempts)
            if math.isfinite(second_won) and math.isfinite(second_attempts) and second_attempts > 0 else np.nan
        ),
        f"{prefix}bp_save_pct": _ratio(acc, "stat_break_points_saved", "stat_break_points_faced"),
        f"{prefix}return_points_won_pct": _ratio(acc, "stat_return_points_won", "stat_return_points_total"),
        f"{prefix}bp_convert_pct": _ratio(acc, "stat_break_points_converted", "stat_break_points_opportunities"),
        f"{prefix}effective_service_points": 0.0 if not math.isfinite(service_points) else float(service_points),
        f"{prefix}effective_return_points": 0.0 if not math.isfinite(return_points) else float(return_points),
    }


def build_rolling_stats(player_rows: pd.DataFrame) -> pd.DataFrame:
    """Build all-surface and surface-specific serve/return states from prior matches only."""
    if player_rows is None or player_rows.empty:
        return player_rows.copy() if player_rows is not None else pd.DataFrame()

    df = player_rows.copy()
    df["_orig_order"] = np.arange(len(df))
    df["match_date"] = pd.to_datetime(df["match_date"], errors="coerce")
    for col in STAT_COLS:
        if col not in df.columns:
            df[col] = np.nan
        df[col] = pd.to_numeric(df[col], errors="coerce")

    outputs = []
    ordered = df.sort_values(["player_name", "match_date", "_orig_order"], kind="stable")
    for _, group in ordered.groupby("player_name", sort=False, dropna=False):
        overall = _empty_accumulator()
        by_surface: dict[str, dict] = defaultdict(_empty_accumulator)

        for idx, row in group.iterrows():
            surface = str(row.get("surface") or "").title()
            all_state = _state(overall, "rolling_")
            surface_state = _state(by_surface[surface], "surface_")
            service_points = all_state["rolling_effective_service_points"]
            return_points = all_state["rolling_effective_return_points"]
            outputs.append({
                "_idx": idx,
                **all_state,
                **surface_state,
                "stat_uncertainty_service": np.nan if service_points <= 0 else float(1.0 / math.sqrt(service_points)),
                "stat_uncertainty_return": np.nan if return_points <= 0 else float(1.0 / math.sqrt(return_points)),
            })
            _update(overall, row)
            _update(by_surface[surface], row)

    features = pd.DataFrame(outputs).set_index("_idx")
    for col in features.columns:
        df[col] = features[col]
    return df.sort_values("_orig_order").drop(columns=["_orig_order"]).reset_index(drop=True)
