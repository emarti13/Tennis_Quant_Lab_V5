from __future__ import annotations

from math import asin, cos, radians, sin, sqrt
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from v5_tournament_registry import TournamentRegistry

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    vals = pd.to_numeric(pd.Series([lat1, lon1, lat2, lon2]), errors="coerce")
    if vals.isna().any():
        return np.nan
    a1, o1, a2, o2 = map(radians, vals.astype(float))
    dlat = a2 - a1
    dlon = o2 - o1
    h = sin(dlat / 2.0) ** 2 + cos(a1) * cos(a2) * sin(dlon / 2.0) ** 2
    return float(2.0 * EARTH_RADIUS_KM * asin(sqrt(h)))


def _utc_offset_hours(timezone_name: str | None, when: pd.Timestamp) -> float:
    if not timezone_name or pd.isna(when):
        return np.nan
    try:
        ts = pd.Timestamp(when)
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        else:
            ts = ts.tz_convert("UTC")
        offset = ts.to_pydatetime().astimezone(ZoneInfo(timezone_name)).utcoffset()
        return np.nan if offset is None else offset.total_seconds() / 3600.0
    except Exception:
        return np.nan


def _continent_lookup(registry_frame: pd.DataFrame) -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    if registry_frame is None or registry_frame.empty or "canonical_event_id" not in registry_frame.columns:
        return out
    for _, row in registry_frame.iterrows():
        event_id = str(row.get("canonical_event_id") or "").strip()
        if not event_id:
            continue
        value = row.get("continent")
        out[event_id] = None if pd.isna(value) or str(value).strip() == "" else str(value).strip()
    return out


def build_travel_features(player_rows: pd.DataFrame, tournament_registry: pd.DataFrame) -> pd.DataFrame:
    """Build strict as-of travel/transition features from the player's prior competition row."""
    if player_rows is None or player_rows.empty:
        return player_rows.copy() if player_rows is not None else pd.DataFrame()

    df = player_rows.copy()
    df["_orig_order"] = np.arange(len(df))
    df["match_date"] = pd.to_datetime(df["match_date"], errors="coerce", utc=True)
    registry = TournamentRegistry(tournament_registry)
    continents = _continent_lookup(tournament_registry)

    result_rows: list[dict] = []
    ordered = df.sort_values(["player_name", "match_date", "_orig_order"], kind="stable")
    for _, group in ordered.groupby("player_name", sort=False, dropna=False):
        previous = None
        previous_date = pd.NaT
        for idx, row in group.iterrows():
            current_date = row["match_date"]
            year = int(current_date.year) if pd.notna(current_date) else 0
            current = registry.resolve(row.get("tourney_name") or "", row.get("tour") or "MEN", year)
            current_continent = continents.get(current.canonical_event_id or "")

            feat = {"_idx": idx}
            if previous is None or current.canonical_event_id is None or previous["ctx"].canonical_event_id is None:
                feat.update({
                    "travel_km_from_previous_event": np.nan,
                    "timezone_change_hours": np.nan,
                    "continent_change": np.nan,
                    "altitude_change_m": np.nan,
                    "surface_change": np.nan,
                    "indoor_outdoor_change": np.nan,
                    "days_since_previous_match": np.nan,
                    "km_per_recovery_day": np.nan,
                    "travel_context_quality": "no_prior" if previous is None else "unresolved",
                })
            else:
                prev_ctx = previous["ctx"]
                same_event = current.canonical_event_id == prev_ctx.canonical_event_id
                distance = 0.0 if same_event else haversine_km(
                    prev_ctx.latitude, prev_ctx.longitude, current.latitude, current.longitude
                )
                previous_offset = _utc_offset_hours(prev_ctx.timezone, current_date)
                current_offset = _utc_offset_hours(current.timezone, current_date)
                tz_change = (
                    current_offset - previous_offset
                    if pd.notna(previous_offset) and pd.notna(current_offset)
                    else np.nan
                )
                days = (
                    float((current_date - previous_date).total_seconds() / 86400.0)
                    if pd.notna(current_date) and pd.notna(previous_date)
                    else np.nan
                )
                prev_continent = previous.get("continent")
                feat.update({
                    "travel_km_from_previous_event": distance,
                    "timezone_change_hours": tz_change,
                    "continent_change": (
                        int(current_continent != prev_continent)
                        if current_continent is not None and prev_continent is not None
                        else np.nan
                    ),
                    "altitude_change_m": (
                        float(current.altitude_m - prev_ctx.altitude_m)
                        if current.altitude_m is not None and prev_ctx.altitude_m is not None
                        else np.nan
                    ),
                    "surface_change": (
                        int(str(current.surface or row.get("surface") or "").lower() != str(prev_ctx.surface or previous.get("surface") or "").lower())
                        if (current.surface or row.get("surface")) and (prev_ctx.surface or previous.get("surface"))
                        else np.nan
                    ),
                    "indoor_outdoor_change": (
                        int(bool(current.indoor) != bool(prev_ctx.indoor))
                        if current.indoor is not None and prev_ctx.indoor is not None
                        else np.nan
                    ),
                    "days_since_previous_match": days,
                    "km_per_recovery_day": (
                        float(distance / max(days, 1.0)) if pd.notna(distance) and pd.notna(days) else np.nan
                    ),
                    "travel_context_quality": "exact_registry",
                })

            result_rows.append(feat)
            previous = {"ctx": current, "continent": current_continent, "surface": row.get("surface")}
            previous_date = current_date

    features = pd.DataFrame(result_rows).set_index("_idx")
    for col in features.columns:
        df[col] = features[col]
    return df.sort_values("_orig_order").drop(columns=["_orig_order"]).reset_index(drop=True)
