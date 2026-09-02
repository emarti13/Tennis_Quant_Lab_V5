from __future__ import annotations

from collections import deque
import math

import numpy as np
import pandas as pd

WINDOWS = (3, 7, 14, 30)
VALUE_FIELDS = ("match_games", "match_sets", "match_duration_minutes")
LAYOFF_THRESHOLDS = (30, 60, 90)


def _finite(value) -> bool:
    return value is not None and math.isfinite(float(value))


def _rest_bucket(days: float) -> float:
    if not _finite(days):
        return np.nan
    d = float(days)
    if d <= 0:
        return 0.0
    if d <= 1:
        return 1.0
    if d <= 2:
        return 2.0
    if d <= 5:
        return 3.0
    if d <= 10:
        return 4.0
    if d <= 21:
        return 5.0
    if d <= 45:
        return 6.0
    return 7.0


def _new_window() -> dict:
    return {
        "rows": deque(),
        "sums": {field: 0.0 for field in VALUE_FIELDS},
        "valid": {field: 0 for field in VALUE_FIELDS},
    }


def _add(window: dict, record: dict) -> None:
    window["rows"].append(record)
    for field in VALUE_FIELDS:
        value = record[field]
        if _finite(value):
            window["sums"][field] += float(value)
            window["valid"][field] += 1


def _remove_left(window: dict) -> None:
    record = window["rows"].popleft()
    for field in VALUE_FIELDS:
        value = record[field]
        if _finite(value):
            window["sums"][field] -= float(value)
            window["valid"][field] -= 1


def _window_value(window: dict, field: str, *, empty_value: float) -> float:
    if not window["rows"]:
        return empty_value
    if window["valid"][field] == 0:
        return np.nan
    return float(window["sums"][field])


def _completed_win(row: pd.Series) -> int | None:
    role = str(row.get("player_role") or "").strip().lower()
    if role == "winner":
        return 1
    if role == "loser":
        return 0
    return None


def build_workload_features(player_rows: pd.DataFrame) -> pd.DataFrame:
    """Build strictly lagged workload, fatigue, rest and layoff-state features.

    Rest is intentionally represented in several nonlinear forms. Raw days remain available
    for diagnostics, while log/bucket/layoff-state variables prevent a 180-day absence from
    being treated as simply twice a 90-day absence. Player-specific comeback history is also
    strictly lagged: a comeback match's own outcome can update future response state only after
    that match's pre-match features are emitted.
    """
    if player_rows is None or player_rows.empty:
        return player_rows.copy() if player_rows is not None else pd.DataFrame()

    df = player_rows.copy()
    df["_orig_order"] = np.arange(len(df))
    df["match_date"] = pd.to_datetime(df["match_date"], errors="coerce")
    for col in ("match_games", "match_sets", "match_duration_minutes", "best_of"):
        if col not in df.columns:
            df[col] = np.nan
        df[col] = pd.to_numeric(df[col], errors="coerce")

    feature_rows = []
    ordered = df.sort_values(["player_name", "match_date", "_orig_order"], kind="stable")
    for _, group in ordered.groupby("player_name", sort=False, dropna=False):
        windows = {days: _new_window() for days in WINDOWS}
        previous_date = pd.NaT
        previous_play_date = pd.NaT
        previous_record = None
        prior_matches = 0
        prior_duration_valid = 0
        consecutive_days = 0
        matches_since_layoff = {threshold: None for threshold in LAYOFF_THRESHOLDS}
        layoff_response = {
            threshold: {"sample": 0, "wins": 0}
            for threshold in LAYOFF_THRESHOLDS
        }

        for idx, row in group.iterrows():
            current_date = row["match_date"]
            normalized_current = current_date.normalize() if pd.notna(current_date) else pd.NaT
            feat = {"_idx": idx}

            if pd.isna(normalized_current) or pd.isna(previous_date):
                rest_days = np.nan
            else:
                rest_days = int((normalized_current - previous_date).days)
            feat["rest_days"] = rest_days
            feat["rest_log1p"] = math.log1p(max(float(rest_days), 0.0)) if _finite(rest_days) else np.nan
            feat["rest_bucket"] = _rest_bucket(rest_days)
            feat["short_rest_0d"] = int(_finite(rest_days) and float(rest_days) <= 0)
            feat["short_rest_1d"] = int(_finite(rest_days) and float(rest_days) == 1)
            feat["short_rest_2d"] = int(_finite(rest_days) and float(rest_days) == 2)
            feat["rest_3_to_7d"] = int(_finite(rest_days) and 3 <= float(rest_days) <= 7)

            current_layoff_flags: dict[int, bool] = {}
            for threshold in LAYOFF_THRESHOLDS:
                is_layoff = bool(_finite(rest_days) and float(rest_days) >= threshold)
                current_layoff_flags[threshold] = is_layoff
                feat[f"layoff_{threshold}d"] = int(is_layoff)
                feat[f"first_match_after_{threshold}d"] = int(is_layoff)
                if is_layoff:
                    feat[f"matches_since_{threshold}d_layoff"] = 0
                    matches_since_layoff[threshold] = 0
                elif matches_since_layoff[threshold] is None:
                    feat[f"matches_since_{threshold}d_layoff"] = np.nan
                else:
                    feat[f"matches_since_{threshold}d_layoff"] = int(matches_since_layoff[threshold])

                response = layoff_response[threshold]
                sample = int(response["sample"])
                wins = int(response["wins"])
                # Beta(1,1) shrinkage prevents 1-2 historical comeback matches from
                # producing a misleading extreme player-specific response estimate.
                shrunk_rate = float((wins + 1.0) / (sample + 2.0))
                feat[f"layoff_response_{threshold}d_sample"] = sample
                feat[f"layoff_response_{threshold}d_shrunk_win_rate"] = shrunk_rate
                feat[f"layoff_response_{threshold}d_excess"] = shrunk_rate - 0.5

            if pd.notna(normalized_current) and pd.notna(previous_play_date):
                gap = int((normalized_current - previous_play_date).days)
                consecutive_days = consecutive_days + 1 if gap == 1 else 0
            else:
                consecutive_days = 0
            feat["consecutive_play_days"] = consecutive_days

            for days, window in windows.items():
                if pd.notna(normalized_current):
                    while window["rows"]:
                        old_date = window["rows"][0]["date"]
                        if pd.isna(old_date) or int((normalized_current - old_date).days) > days:
                            _remove_left(window)
                        else:
                            break
                else:
                    while window["rows"]:
                        _remove_left(window)

                feat[f"matches_last_{days}d"] = int(len(window["rows"]))
                feat[f"games_last_{days}d"] = _window_value(window, "match_games", empty_value=0.0)
                feat[f"sets_last_{days}d"] = _window_value(window, "match_sets", empty_value=0.0)
                feat[f"minutes_last_{days}d"] = _window_value(window, "match_duration_minutes", empty_value=np.nan)

            if previous_record is None:
                feat["duration_quality"] = "no_prior"
                feat["previous_match_games"] = np.nan
                feat["previous_match_sets"] = np.nan
                feat["previous_match_duration"] = np.nan
            else:
                feat["previous_match_games"] = previous_record["match_games"]
                feat["previous_match_sets"] = previous_record["match_sets"]
                feat["previous_match_duration"] = previous_record["match_duration_minutes"]
                feat["duration_quality"] = "prior_complete" if prior_duration_valid == prior_matches else "prior_partial"

            feature_rows.append(feat)

            record = {
                "date": normalized_current,
                "match_games": float(row["match_games"]) if pd.notna(row["match_games"]) else np.nan,
                "match_sets": float(row["match_sets"]) if pd.notna(row["match_sets"]) else np.nan,
                "match_duration_minutes": float(row["match_duration_minutes"]) if pd.notna(row["match_duration_minutes"]) else np.nan,
            }
            if pd.notna(normalized_current):
                for window in windows.values():
                    _add(window, record)
            prior_matches += 1
            if _finite(record["match_duration_minutes"]):
                prior_duration_valid += 1
            previous_record = record
            previous_date = normalized_current
            previous_play_date = normalized_current

            completed_win = _completed_win(row)
            if completed_win is not None:
                for threshold, is_layoff in current_layoff_flags.items():
                    if is_layoff:
                        layoff_response[threshold]["sample"] += 1
                        layoff_response[threshold]["wins"] += int(completed_win)

            for threshold in LAYOFF_THRESHOLDS:
                if matches_since_layoff[threshold] is not None:
                    matches_since_layoff[threshold] += 1

    features = pd.DataFrame(feature_rows).set_index("_idx")
    for col in features.columns:
        df[col] = features[col]
    return df.sort_values("_orig_order").drop(columns=["_orig_order"]).reset_index(drop=True)
