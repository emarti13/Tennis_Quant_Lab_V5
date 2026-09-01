import pandas as pd

from v5_weather_context import weather_source_kind, nearest_hour_features, cache_key


def test_historical_validation_uses_historical_forecast_not_realized_archive():
    assert weather_source_kind(pd.Timestamp("2026-06-01", tz="UTC"), pd.Timestamp("2026-09-01", tz="UTC")) == "historical_forecast"


def test_live_future_match_uses_forecast():
    assert weather_source_kind(pd.Timestamp("2026-09-03", tz="UTC"), pd.Timestamp("2026-09-01", tz="UTC")) == "forecast"


def test_nearest_hour_features_selects_closest_available_hour():
    payload = {
        "hourly": {
            "time": ["2026-09-01T10:00", "2026-09-01T11:00", "2026-09-01T12:00"],
            "temperature_2m": [20.0, 22.0, 24.0],
            "relative_humidity_2m": [70, 65, 60],
            "dew_point_2m": [14.0, 15.0, 16.0],
            "apparent_temperature": [20.0, 23.0, 25.0],
            "precipitation": [0.0, 0.2, 0.0],
            "surface_pressure": [1000, 999, 998],
            "cloud_cover": [10, 20, 30],
            "wind_speed_10m": [8, 10, 12],
            "wind_gusts_10m": [12, 16, 20],
        }
    }
    out = nearest_hour_features(payload, pd.Timestamp("2026-09-01T11:20"))
    assert out["weather_temperature_c"] == 22.0
    assert out["weather_humidity_pct"] == 65
    assert out["weather_wind_speed_kmh"] == 10
    assert out["weather_time_distance_minutes"] == 20


def test_cache_key_is_stable_and_location_time_specific():
    a = cache_key(40.0, -74.0, "2026-09-01", "historical_forecast")
    b = cache_key(40.0, -74.0, "2026-09-01", "historical_forecast")
    c = cache_key(40.1, -74.0, "2026-09-01", "historical_forecast")
    assert a == b
    assert a != c
