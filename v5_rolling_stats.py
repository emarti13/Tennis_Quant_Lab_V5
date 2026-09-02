from __future__ import annotations

import math
import numpy as np
import pandas as pd

STAT_COLS = [
    "stat_aces", "stat_double_faults", "stat_service_points", "stat_first_serves_in",
    "stat_first_serve_points_won", "stat_second_serve_points_won",
    "stat_break_points_saved", "stat_break_points_faced",
    "stat_return_points_total", "stat_return_points_won",
    "stat_break_points_opportunities", "stat_break_points_converted",
]


def _num(frame: pd.DataFrame, col: str) -> pd.Series:
    if col not in frame.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(frame[col], errors="coerce")


def _ratio(frame: pd.DataFrame, numerator: str, denominator: str) -> float:
    n = _num(frame, numerator).sum(min_count=1)
    d = _num(frame, denominator).sum(min_count=1)
    if pd.isna(n) or pd.isna(d) or d <= 0:
        return np.nan
    return float(n / d)


def _state(history: pd.DataFrame, prefix: str) -> dict[str, float]:
    if history.empty:
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

    service_points = _num(history, "stat_service_points").sum(min_count=1)
    first_in = _num(history, "stat_first_serves_in").sum(min_count=1)
    second_attempts = service_points - first_in if pd.notna(service_points) and pd.notna(first_in) else np.nan
    second_won = _num(history, "stat_second_serve_points_won").sum(min_count=1)
    return_points = _num(history, "stat_return_points_total").sum(min_count=1)

    return {
        f"{prefix}ace_rate": _ratio(history, "stat_aces", "stat_service_points"),
        f"{prefix}double_fault_rate": _ratio(history, "stat_double_faults", "stat_service_points"),
        f"{prefix}first_serve_in_pct": _ratio(history, "stat_first_serves_in", "stat_service_points"),
        f"{prefix}first_serve_points_won_pct": _ratio(history, "stat_first_serve_points_won", "stat_first_serves_in"),
        f"{prefix}second_serve_points_won_pct": (
            float(second_won / second_attempts)
            if pd.notna(second_won) and pd.notna(second_attempts) and second_attempts > 0 else np.nan
        ),
        f"{prefix}bp_save_pct": _ratio(history, "stat_break_points_saved", "stat_break_points_faced"),
        f"{prefix}return_points_won_pct": _ratio(history, "stat_return_points_won", "stat_return_points_total"),
        f"{prefix}bp_convert_pct": _ratio(history, "stat_break_points_converted", "stat_break_points_opportunities"),
        f"{prefix}effective_service_points": 0.0 if pd.isna(service_points) else float(service_points),
        f"{prefix}effective_return_points": 0.0 if pd.isna(return_points) else float(return_points),
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

    outputs = []
    ordered = df.sort_values(["player_name", "match_date", "_orig_order"], kind="stable")
    for _, group in ordered.groupby("player_name", sort=False, dropna=False):
        history: list[dict] = []
        for idx, row in group.iterrows():
            prior = pd.DataFrame(history)
            surface = str(row.get("surface") or "").title()
            same_surface = prior[prior["surface"].astype(str).str.title() == surface] if not prior.empty else prior
            all_state = _state(prior, "rolling_")
            surface_state = _state(same_surface, "surface_")
            service_points = all_state["rolling_effective_service_points"]
            return_points = all_state["rolling_effective_return_points"]
            service_u = np.nan if service_points <= 0 else float(1.0 / math.sqrt(service_points))
            return_u = np.nan if return_points <= 0 else float(1.0 / math.sqrt(return_points))
            outputs.append({
                "_idx": idx,
                **all_state,
                **surface_state,
                "stat_uncertainty_service": service_u,
                "stat_uncertainty_return": return_u,
            })
            history.append(row.to_dict())

    features = pd.DataFrame(outputs).set_index("_idx")
    for col in features.columns:
        df[col] = features[col]
    return df.sort_values("_orig_order").drop(columns=["_orig_order"]).reset_index(drop=True)
