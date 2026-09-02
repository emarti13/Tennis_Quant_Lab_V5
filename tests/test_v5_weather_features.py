import numpy as np
import pandas as pd

from v5_weather_features import build_weather_features, summarize_hourly_weather


class FakeWeatherClient:
    def __init__(self):
        self.calls = []

    def get_daily(self, latitude, longitude, date, timezone=None):
        self.calls.append((round(float(latitude), 2), round(float(longitude), 2), str(date), timezone))
        return {
            "temperature_c": 24.0,
            "humidity_pct": 58.0,
            "wind_speed_kmh": 13.0,
            "wind_gust_kmh": 28.0,
            "precipitation_mm": 1.5,
            "dew_point_c": 15.0,
            "pressure_hpa": 1008.0,
            "source_quality": "historical_observed_daily",
        }


def _rows():
    return pd.DataFrame([
        {"match_id":"m1","player_name":"A","match_date":"2026-04-20","venue_latitude":40.4,"venue_longitude":-3.7,"venue_timezone":"Europe/Madrid"},
        {"match_id":"m1","player_name":"B","match_date":"2026-04-20","venue_latitude":40.4,"venue_longitude":-3.7,"venue_timezone":"Europe/Madrid"},
        {"match_id":"m2","player_name":"C","match_date":"2026-04-21","venue_latitude":np.nan,"venue_longitude":np.nan,"venue_timezone":None},
    ])


def test_summarize_hourly_weather_uses_mean_max_and_sum_as_intended():
    payload = {
        "hourly": {
            "temperature_2m": [20.0, 24.0],
            "relative_humidity_2m": [50.0, 70.0],
            "wind_speed_10m": [10.0, 20.0],
            "wind_gusts_10m": [25.0, 35.0],
            "precipitation": [0.5, 1.0],
            "dew_point_2m": [10.0, 14.0],
            "surface_pressure": [1000.0, 1004.0],
        }
    }
    out = summarize_hourly_weather(payload)
    assert out["temperature_c"] == 22.0
    assert out["humidity_pct"] == 60.0
    assert out["wind_speed_kmh"] == 15.0
    assert out["wind_gust_kmh"] == 35.0
    assert out["precipitation_mm"] == 1.5
    assert out["dew_point_c"] == 12.0
    assert out["pressure_hpa"] == 1002.0


def test_weather_features_are_shared_by_match_and_requested_once_per_venue_date():
    client = FakeWeatherClient()
    out = build_weather_features(_rows(), client=client)
    m1 = out[out.match_id == "m1"]
    assert m1["weather_temperature_c"].tolist() == [24.0, 24.0]
    assert m1["weather_humidity_pct"].tolist() == [58.0, 58.0]
    assert m1["weather_pressure_hpa"].tolist() == [1008.0, 1008.0]
    assert len(client.calls) == 1


def test_missing_venue_keeps_weather_explicitly_unresolved():
    out = build_weather_features(_rows(), client=FakeWeatherClient())
    m2 = out[out.match_id == "m2"].iloc[0]
    assert pd.isna(m2["weather_temperature_c"])
    assert pd.isna(m2["weather_pressure_hpa"])
    assert m2["weather_source_quality"] == "unresolved_venue"
