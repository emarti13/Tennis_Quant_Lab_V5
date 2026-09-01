from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import json

import pandas as pd
import requests

HOURLY_VARIABLES = [
    "temperature_2m", "relative_humidity_2m", "dew_point_2m", "apparent_temperature",
    "precipitation", "surface_pressure", "cloud_cover", "wind_speed_10m", "wind_gusts_10m",
]

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
HISTORICAL_FORECAST_URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"


def weather_source_kind(target_time: pd.Timestamp, prediction_time: pd.Timestamp) -> str:
    target = pd.Timestamp(target_time)
    prediction = pd.Timestamp(prediction_time)
    if target.tzinfo is None:
        target = target.tz_localize("UTC")
    if prediction.tzinfo is None:
        prediction = prediction.tz_localize("UTC")
    return "forecast" if target >= prediction else "historical_forecast"


def cache_key(latitude: float, longitude: float, date_value: str, source_kind: str) -> str:
    raw = f"{float(latitude):.4f}|{float(longitude):.4f}|{date_value}|{source_kind}"
    return sha256(raw.encode("utf-8")).hexdigest()[:24]


def nearest_hour_features(payload: dict, target_local_time: pd.Timestamp) -> dict:
    hourly = payload.get("hourly") or {}
    times = pd.to_datetime(pd.Series(hourly.get("time") or []), errors="coerce")
    target = pd.Timestamp(target_local_time)
    if times.empty or times.isna().all():
        return {"weather_quality": "missing"}
    if target.tzinfo is not None:
        target = target.tz_localize(None)
    distances = (times - target).abs()
    idx = int(distances.idxmin())

    def value(name):
        values = hourly.get(name) or []
        return values[idx] if idx < len(values) else None

    return {
        "weather_temperature_c": value("temperature_2m"),
        "weather_humidity_pct": value("relative_humidity_2m"),
        "weather_dew_point_c": value("dew_point_2m"),
        "weather_apparent_temperature_c": value("apparent_temperature"),
        "weather_precipitation_mm": value("precipitation"),
        "weather_surface_pressure_hpa": value("surface_pressure"),
        "weather_cloud_cover_pct": value("cloud_cover"),
        "weather_wind_speed_kmh": value("wind_speed_10m"),
        "weather_wind_gust_kmh": value("wind_gusts_10m"),
        "weather_observation_time": str(times.iloc[idx]),
        "weather_time_distance_minutes": int(round(distances.iloc[idx].total_seconds() / 60.0)),
        "weather_quality": "hourly_nearest",
    }


class OpenMeteoWeatherCache:
    """Persistent weather adapter that preserves the data mode used for each feature row.

    Historical replay uses archived forecasts rather than perfect realized weather so model
    validation does not gain atmospheric hindsight. Realized archive weather can be fetched
    separately for diagnostics, but is never substituted silently into predictive features.
    """

    def __init__(self, cache_dir: str | Path = "context_cache/weather", session=None):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.session = session or requests.Session()

    def _endpoint(self, source_kind: str) -> str:
        if source_kind == "forecast":
            return FORECAST_URL
        if source_kind == "historical_forecast":
            return HISTORICAL_FORECAST_URL
        if source_kind == "realized_archive":
            return ARCHIVE_URL
        raise ValueError(f"Unsupported weather source kind: {source_kind}")

    def fetch_day(
        self,
        latitude: float,
        longitude: float,
        local_date: str,
        timezone: str,
        source_kind: str,
        *,
        force: bool = False,
    ) -> dict:
        key = cache_key(latitude, longitude, local_date, source_kind)
        path = self.cache_dir / f"{key}.json"
        if path.exists() and not force:
            return json.loads(path.read_text(encoding="utf-8"))

        params = {
            "latitude": float(latitude),
            "longitude": float(longitude),
            "hourly": ",".join(HOURLY_VARIABLES),
            "timezone": timezone or "UTC",
            "start_date": local_date,
            "end_date": local_date,
        }
        response = self.session.get(self._endpoint(source_kind), params=params, timeout=60)
        response.raise_for_status()
        payload = response.json()
        wrapped = {
            "source_kind": source_kind,
            "source_endpoint": self._endpoint(source_kind),
            "latitude_requested": float(latitude),
            "longitude_requested": float(longitude),
            "local_date": local_date,
            "timezone_requested": timezone or "UTC",
            "payload": payload,
        }
        path.write_text(json.dumps(wrapped, indent=2), encoding="utf-8")
        return wrapped

    def match_features(
        self,
        latitude: float,
        longitude: float,
        target_local_time: pd.Timestamp,
        prediction_time: pd.Timestamp,
        timezone: str,
    ) -> dict:
        target = pd.Timestamp(target_local_time)
        source_kind = weather_source_kind(target, pd.Timestamp(prediction_time))
        local_date = target.strftime("%Y-%m-%d")
        wrapped = self.fetch_day(latitude, longitude, local_date, timezone, source_kind)
        features = nearest_hour_features(wrapped["payload"], target)
        features.update({
            "weather_source_kind": source_kind,
            "weather_source_endpoint": wrapped["source_endpoint"],
        })
        return features
