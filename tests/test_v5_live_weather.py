from __future__ import annotations

import pandas as pd
import pytest


def test_forecast_summary_uses_closest_pre_match_hour():
    from v5_weather_features import summarize_forecast_at_time

    payload = {
        "hourly": {
            "time": ["2026-09-02T18:00", "2026-09-02T19:00", "2026-09-02T20:00"],
            "temperature_2m": [28.0, 27.0, 26.0],
            "relative_humidity_2m": [50.0, 55.0, 60.0],
            "dew_point_2m": [16.0, 17.0, 18.0],
            "surface_pressure": [1005.0, 1004.0, 1003.0],
            "precipitation": [0.0, 0.2, 0.4],
            "wind_speed_10m": [10.0, 12.0, 14.0],
            "wind_gusts_10m": [18.0, 20.0, 22.0],
        }
    }
    out = summarize_forecast_at_time(payload, "2026-09-02T19:20:00")
    assert out["temperature_c"] == pytest.approx(27.0)
    assert out["humidity_pct"] == pytest.approx(55.0)
    assert out["forecast_hour"] == "2026-09-02T19:00:00"
    assert out["source_quality"] == "forecast_hourly_pre_match"


def test_attach_live_weather_only_fills_live_targets():
    from v5_weather_features import attach_live_weather

    class FakeForecast:
        def get_at_time(self, latitude, longitude, when, timezone=None):
            assert latitude == pytest.approx(40.0)
            assert longitude == pytest.approx(-74.0)
            return {
                "temperature_c": 25.0,
                "humidity_pct": 62.0,
                "wind_speed_kmh": 11.0,
                "wind_gust_kmh": 19.0,
                "precipitation_mm": 0.0,
                "dew_point_c": 17.0,
                "pressure_hpa": 1008.0,
                "source_quality": "forecast_hourly_pre_match",
                "forecast_hour": "2026-09-02T19:00:00",
            }

    rows = pd.DataFrame([
        {
            "match_id": "historical",
            "result_file": "ATP_2026.csv",
            "match_date": "2026-08-01T19:00:00Z",
            "venue_latitude": 40.0,
            "venue_longitude": -74.0,
            "venue_timezone": "America/New_York",
            "weather_temperature_c": 31.0,
            "weather_source_quality": "historical_observed_daily",
        },
        {
            "match_id": "live_f1",
            "result_file": "LIVE_TARGET",
            "match_date": "2026-09-02T19:20:00Z",
            "venue_latitude": 40.0,
            "venue_longitude": -74.0,
            "venue_timezone": "America/New_York",
        },
    ])
    out = attach_live_weather(rows, client=FakeForecast())
    old = out[out["match_id"] == "historical"].iloc[0]
    live = out[out["match_id"] == "live_f1"].iloc[0]
    assert old["weather_temperature_c"] == pytest.approx(31.0)
    assert old["weather_source_quality"] == "historical_observed_daily"
    assert live["weather_temperature_c"] == pytest.approx(25.0)
    assert live["weather_source_quality"] == "forecast_hourly_pre_match"
    assert live["weather_forecast_hour"] == "2026-09-02T19:00:00"
