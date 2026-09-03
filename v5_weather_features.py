from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from zoneinfo import ZoneInfo
import json

import numpy as np
import pandas as pd
import requests

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
HOURLY_VARIABLES = [
    "temperature_2m",
    "relative_humidity_2m",
    "dew_point_2m",
    "surface_pressure",
    "precipitation",
    "wind_speed_10m",
    "wind_gusts_10m",
]


def _finite(values) -> np.ndarray:
    arr = pd.to_numeric(pd.Series(values), errors="coerce").to_numpy(dtype=float)
    return arr[np.isfinite(arr)]


def _mean(values) -> float:
    arr = _finite(values)
    return float(arr.mean()) if len(arr) else np.nan


def _max(values) -> float:
    arr = _finite(values)
    return float(arr.max()) if len(arr) else np.nan


def _sum(values) -> float:
    arr = _finite(values)
    return float(arr.sum()) if len(arr) else np.nan


def summarize_hourly_weather(payload: dict) -> dict[str, float | str]:
    hourly = (payload or {}).get("hourly") or {}
    return {
        "temperature_c": _mean(hourly.get("temperature_2m", [])),
        "humidity_pct": _mean(hourly.get("relative_humidity_2m", [])),
        "wind_speed_kmh": _mean(hourly.get("wind_speed_10m", [])),
        "wind_gust_kmh": _max(hourly.get("wind_gusts_10m", [])),
        "precipitation_mm": _sum(hourly.get("precipitation", [])),
        "dew_point_c": _mean(hourly.get("dew_point_2m", [])),
        "pressure_hpa": _mean(hourly.get("surface_pressure", [])),
        "source_quality": "historical_observed_daily",
    }


def summarize_hourly_weather_by_date(payload: dict) -> dict[str, dict[str, float | str]]:
    """Aggregate one multi-day Open-Meteo hourly payload into local-date summaries."""
    hourly = (payload or {}).get("hourly") or {}
    times = pd.to_datetime(pd.Series(hourly.get("time", [])), errors="coerce")
    if times.empty:
        return {}
    frame = pd.DataFrame({"time": times})
    for key in HOURLY_VARIABLES:
        raw = hourly.get(key, [])
        frame[key] = pd.to_numeric(pd.Series(raw), errors="coerce").reindex(frame.index)
    frame = frame[frame["time"].notna()].copy()
    frame["date"] = frame["time"].dt.strftime("%Y-%m-%d")
    out: dict[str, dict[str, float | str]] = {}
    for day, group in frame.groupby("date", sort=True):
        out[str(day)] = {
            "temperature_c": _mean(group["temperature_2m"]),
            "humidity_pct": _mean(group["relative_humidity_2m"]),
            "wind_speed_kmh": _mean(group["wind_speed_10m"]),
            "wind_gust_kmh": _max(group["wind_gusts_10m"]),
            "precipitation_mm": _sum(group["precipitation"]),
            "dew_point_c": _mean(group["dew_point_2m"]),
            "pressure_hpa": _mean(group["surface_pressure"]),
            "source_quality": "historical_observed_daily",
        }
    return out


def summarize_forecast_at_time(payload: dict, target_time) -> dict[str, float | str]:
    """Select the closest hourly forecast to the pre-match target time.

    Open-Meteo returns local clock timestamps when a timezone is requested. This function
    deliberately consumes only forecast fields; no match result or later tennis observation
    can enter the environment state.
    """
    hourly = (payload or {}).get("hourly") or {}
    times = pd.to_datetime(pd.Series(hourly.get("time", [])), errors="coerce")
    target = pd.Timestamp(target_time)
    if target.tzinfo is not None:
        target = target.tz_localize(None)
    if times.empty or times.notna().sum() == 0:
        raise ValueError("Forecast payload contains no hourly timestamps")
    valid = times.notna()
    distance = (times[valid] - target).abs()
    idx = distance.idxmin()

    def value(name):
        raw = pd.to_numeric(pd.Series(hourly.get(name, [])), errors="coerce")
        return float(raw.iloc[idx]) if idx < len(raw) and pd.notna(raw.iloc[idx]) else np.nan

    forecast_hour = pd.Timestamp(times.iloc[idx]).isoformat()
    return {
        "temperature_c": value("temperature_2m"),
        "humidity_pct": value("relative_humidity_2m"),
        "wind_speed_kmh": value("wind_speed_10m"),
        "wind_gust_kmh": value("wind_gusts_10m"),
        "precipitation_mm": value("precipitation"),
        "dew_point_c": value("dew_point_2m"),
        "pressure_hpa": value("surface_pressure"),
        "source_quality": "forecast_hourly_pre_match",
        "forecast_hour": forecast_hour,
    }


class OpenMeteoArchiveClient:
    def __init__(self, cache_dir: str | Path = "context_cache/weather", session=None):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.session = session or requests.Session()

    def _request_payload(self, latitude, longitude, start_date, end_date, timezone=None) -> dict:
        start = pd.Timestamp(start_date).strftime("%Y-%m-%d")
        end = pd.Timestamp(end_date).strftime("%Y-%m-%d")
        lat = float(latitude)
        lon = float(longitude)
        tz = str(timezone or "UTC")
        key_raw = f"{lat:.4f}|{lon:.4f}|{start}|{end}|{tz}|{'|'.join(HOURLY_VARIABLES)}"
        key = sha256(key_raw.encode("utf-8")).hexdigest()[:32]
        path = self.cache_dir / f"{key}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        response = self.session.get(
            ARCHIVE_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "start_date": start,
                "end_date": end,
                "hourly": ",".join(HOURLY_VARIABLES),
                "timezone": tz,
                "wind_speed_unit": "kmh",
                "precipitation_unit": "mm",
            },
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        path.write_text(json.dumps(payload), encoding="utf-8")
        return payload

    def get_daily(self, latitude, longitude, date, timezone=None) -> dict:
        day = pd.Timestamp(date).strftime("%Y-%m-%d")
        payload = self._request_payload(latitude, longitude, day, day, timezone=timezone)
        return summarize_hourly_weather(payload)

    def get_range(self, latitude, longitude, start_date, end_date, timezone=None) -> dict[str, dict]:
        payload = self._request_payload(latitude, longitude, start_date, end_date, timezone=timezone)
        return summarize_hourly_weather_by_date(payload)


class OpenMeteoForecastClient:
    """Cached current/future hourly weather available before the match begins."""

    def __init__(self, cache_dir: str | Path = "context_cache/weather_forecast", session=None):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.session = session or requests.Session()

    def _local_target(self, when, timezone=None) -> pd.Timestamp:
        target = pd.Timestamp(when)
        tz = str(timezone or "UTC")
        if target.tzinfo is None:
            return target
        try:
            return target.tz_convert(ZoneInfo(tz)).tz_localize(None)
        except Exception:
            return target.tz_convert("UTC").tz_localize(None)

    def _request_payload(self, latitude, longitude, target_time, timezone=None) -> tuple[dict, pd.Timestamp]:
        lat = float(latitude)
        lon = float(longitude)
        tz = str(timezone or "UTC")
        local_target = self._local_target(target_time, tz)
        day = local_target.strftime("%Y-%m-%d")
        # Cache by venue/local day. Forecast responses are intentionally refreshed between
        # workflow runs; a single run reuses the same response for every match at the venue.
        key_raw = f"forecast|{lat:.4f}|{lon:.4f}|{day}|{tz}|{'|'.join(HOURLY_VARIABLES)}"
        key = sha256(key_raw.encode("utf-8")).hexdigest()[:32]
        path = self.cache_dir / f"{key}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8")), local_target
        response = self.session.get(
            FORECAST_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "start_date": day,
                "end_date": day,
                "hourly": ",".join(HOURLY_VARIABLES),
                "timezone": tz,
                "wind_speed_unit": "kmh",
                "precipitation_unit": "mm",
            },
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        path.write_text(json.dumps(payload), encoding="utf-8")
        return payload, local_target

    def get_at_time(self, latitude, longitude, when, timezone=None) -> dict:
        payload, local_target = self._request_payload(latitude, longitude, when, timezone=timezone)
        return summarize_forecast_at_time(payload, local_target)


def _weather_columns() -> list[str]:
    return [
        "weather_temperature_c",
        "weather_humidity_pct",
        "weather_wind_speed_kmh",
        "weather_wind_gust_kmh",
        "weather_precipitation_mm",
        "weather_dew_point_c",
        "weather_pressure_hpa",
        "weather_source_quality",
    ]


def _missing_weather(quality: str) -> dict:
    return {
        "temperature_c": np.nan,
        "humidity_pct": np.nan,
        "wind_speed_kmh": np.nan,
        "wind_gust_kmh": np.nan,
        "precipitation_mm": np.nan,
        "dew_point_c": np.nan,
        "pressure_hpa": np.nan,
        "source_quality": quality,
        "forecast_hour": "",
    }


def _apply_weather_values(df: pd.DataFrame, mask: pd.Series, values_by_match: dict) -> pd.DataFrame:
    mapping = {
        "weather_temperature_c": "temperature_c",
        "weather_humidity_pct": "humidity_pct",
        "weather_wind_speed_kmh": "wind_speed_kmh",
        "weather_wind_gust_kmh": "wind_gust_kmh",
        "weather_precipitation_mm": "precipitation_mm",
        "weather_dew_point_c": "dew_point_c",
        "weather_pressure_hpa": "pressure_hpa",
        "weather_source_quality": "source_quality",
        "weather_forecast_hour": "forecast_hour",
    }
    text_targets = {"weather_source_quality", "weather_forecast_hour"}
    for target, source in mapping.items():
        if target not in df.columns:
            df[target] = "" if target in text_targets else np.nan
        elif target in text_targets and not (pd.api.types.is_object_dtype(df[target].dtype) or pd.api.types.is_string_dtype(df[target].dtype)):
            # Historical all-null metadata can be read from parquet as float64.
            # Cast only text metadata before assigning live source labels under Pandas 3.
            df[target] = df[target].astype("object")
        df.loc[mask, target] = df.loc[mask, "match_id"].map(lambda match_id: values_by_match.get(match_id, {}).get(source, np.nan))
    return df


def attach_live_weather(player_rows: pd.DataFrame, client=None) -> pd.DataFrame:
    """Attach only pre-match forecast weather to LIVE_TARGET rows, preserving history."""
    if player_rows is None or player_rows.empty:
        return player_rows.copy() if player_rows is not None else pd.DataFrame()
    df = player_rows.copy()
    client = client or OpenMeteoForecastClient()
    live_mask = df.get("result_file", pd.Series("", index=df.index)).astype(str).eq("LIVE_TARGET")
    if not live_mask.any():
        return df
    values_by_match = {}
    request_cache = {}
    for match_id, group in df[live_mask].groupby("match_id", sort=False, dropna=False):
        row = group.iloc[0]
        lat = pd.to_numeric(pd.Series([row.get("venue_latitude")]), errors="coerce").iloc[0]
        lon = pd.to_numeric(pd.Series([row.get("venue_longitude")]), errors="coerce").iloc[0]
        when = row.get("match_date")
        timezone = row.get("venue_timezone")
        if pd.isna(lat) or pd.isna(lon) or pd.isna(pd.to_datetime(when, errors="coerce")):
            values_by_match[match_id] = _missing_weather("unresolved_live_venue")
            continue
        key = (round(float(lat), 4), round(float(lon), 4), str(pd.Timestamp(when)), str(timezone or "UTC"))
        if key not in request_cache:
            try:
                request_cache[key] = client.get_at_time(float(lat), float(lon), when, timezone=timezone)
            except Exception as exc:
                request_cache[key] = _missing_weather(f"forecast_error:{type(exc).__name__}")
        values_by_match[match_id] = request_cache[key]
    return _apply_weather_values(df, live_mask, values_by_match)


def build_weather_features(player_rows: pd.DataFrame, client=None) -> pd.DataFrame:
    """Attach venue/date historical weather shared by all player rows in the same match."""
    if player_rows is None or player_rows.empty:
        return player_rows.copy() if player_rows is not None else pd.DataFrame()

    df = player_rows.copy()
    client = client or OpenMeteoArchiveClient()
    dates = pd.to_datetime(df.get("match_date"), errors="coerce")
    df["_weather_date"] = dates.dt.strftime("%Y-%m-%d")

    match_weather: dict[object, dict] = {}
    request_cache: dict[tuple, dict] = {}
    for match_id, group in df.groupby("match_id", sort=False, dropna=False):
        row = group.iloc[0]
        lat = pd.to_numeric(pd.Series([row.get("venue_latitude")]), errors="coerce").iloc[0]
        lon = pd.to_numeric(pd.Series([row.get("venue_longitude")]), errors="coerce").iloc[0]
        day = row.get("_weather_date")
        timezone = row.get("venue_timezone")

        if pd.isna(lat) or pd.isna(lon) or not day:
            match_weather[match_id] = _missing_weather("unresolved_venue")
            continue

        key = (round(float(lat), 4), round(float(lon), 4), str(day), str(timezone or "UTC"))
        if key not in request_cache:
            try:
                request_cache[key] = client.get_daily(float(lat), float(lon), str(day), timezone=timezone)
            except Exception as exc:
                request_cache[key] = _missing_weather(f"weather_error:{type(exc).__name__}")
        match_weather[match_id] = request_cache[key]

    mask = pd.Series(True, index=df.index)
    df = _apply_weather_values(df, mask, match_weather)
    return df.drop(columns=["_weather_date"])
