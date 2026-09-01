from __future__ import annotations

import numpy as np
import pandas as pd

WINDOWS = (3, 7, 14, 30)


def _sum_or_nan(series: pd.Series) -> float:
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.notna().sum() == 0:
        return np.nan
    return float(numeric.sum(skipna=True))


def build_workload_features(player_rows: pd.DataFrame) -> pd.DataFrame:
    """Build strictly lagged workload/rest features from chronological player matches.

    The target row's own match outcome/duration is never used in any feature on that row.
    Rows are returned in their original order.
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
    for _, group in df.sort_values(["player_name", "match_date", "_orig_order"], kind="stable").groupby("player_name", sort=False, dropna=False):
        history = []
        previous_date = pd.NaT
        consecutive_days = 0
        previous_play_date = pd.NaT

        for idx, row in group.iterrows():
            current_date = row["match_date"]
            feat = {"_idx": idx}

            if pd.isna(current_date) or pd.isna(previous_date):
                feat["rest_days"] = np.nan
            else:
                feat["rest_days"] = int((current_date.normalize() - previous_date.normalize()).days)

            if pd.notna(current_date) and pd.notna(previous_play_date):
                gap = int((current_date.normalize() - previous_play_date.normalize()).days)
                consecutive_days = consecutive_days + 1 if gap == 1 else 0
            else:
                consecutive_days = 0
            feat["consecutive_play_days"] = consecutive_days

            prior = pd.DataFrame(history)
            for days in WINDOWS:
                if prior.empty or pd.isna(current_date):
                    window = prior.iloc[0:0] if not prior.empty else pd.DataFrame()
                else:
                    delta = current_date.normalize() - pd.to_datetime(prior["match_date"]).dt.normalize()
                    # Inclusive boundary: matches exactly N days earlier are included.
                    window = prior[(delta.dt.days >= 0) & (delta.dt.days <= days)]

                feat[f"matches_last_{days}d"] = int(len(window))
                feat[f"games_last_{days}d"] = _sum_or_nan(window.get("match_games", pd.Series(dtype=float))) if len(window) else 0.0
                feat[f"sets_last_{days}d"] = _sum_or_nan(window.get("match_sets", pd.Series(dtype=float))) if len(window) else 0.0
                feat[f"minutes_last_{days}d"] = _sum_or_nan(window.get("match_duration_minutes", pd.Series(dtype=float))) if len(window) else np.nan

            if prior.empty:
                feat["duration_quality"] = "no_prior"
                feat["previous_match_games"] = np.nan
                feat["previous_match_sets"] = np.nan
                feat["previous_match_duration"] = np.nan
            else:
                last = prior.iloc[-1]
                feat["previous_match_games"] = last.get("match_games", np.nan)
                feat["previous_match_sets"] = last.get("match_sets", np.nan)
                feat["previous_match_duration"] = last.get("match_duration_minutes", np.nan)
                duration_valid = pd.to_numeric(prior["match_duration_minutes"], errors="coerce").notna()
                feat["duration_quality"] = "prior_complete" if duration_valid.all() else "prior_partial"

            feature_rows.append(feat)
            history.append(row.to_dict())
            previous_date = current_date
            previous_play_date = current_date

    features = pd.DataFrame(feature_rows).set_index("_idx")
    for col in features.columns:
        df[col] = features[col]
    return df.sort_values("_orig_order").drop(columns=["_orig_order"]).reset_index(drop=True)
