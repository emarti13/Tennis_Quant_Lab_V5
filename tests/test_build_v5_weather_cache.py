from pathlib import Path

import pandas as pd

from build_v5_weather_cache import build_weather_cache


class FakeRangeClient:
    def __init__(self):
        self.calls = []

    def get_range(self, latitude, longitude, start_date, end_date, timezone=None):
        self.calls.append((round(float(latitude), 2), round(float(longitude), 2), str(start_date), str(end_date), timezone))
        dates = pd.date_range(start_date, end_date, freq="D")
        return {
            d.strftime("%Y-%m-%d"): {
                "temperature_c": 20.0 + i,
                "humidity_pct": 60.0,
                "wind_speed_kmh": 12.0,
                "wind_gust_kmh": 25.0,
                "precipitation_mm": 0.0,
                "dew_point_c": 12.0,
                "pressure_hpa": 1005.0,
                "source_quality": "historical_observed_daily",
            }
            for i, d in enumerate(dates)
        }


def test_weather_cache_batches_one_request_per_event_year_and_persists_match_dates(tmp_path: Path):
    warehouse = tmp_path / "context_warehouse"
    registry_dir = tmp_path / "context_registry"
    warehouse.mkdir()
    registry_dir.mkdir()

    pd.DataFrame([
        {"match_id":"m1","tour":"MEN","match_date":"2026-04-20","tourney_id":"2026-0999","tourney_name":"Madrid","surface":"Clay"},
        {"match_id":"m2","tour":"MEN","match_date":"2026-04-22","tourney_id":"2026-0999","tourney_name":"Madrid","surface":"Clay"},
        {"match_id":"m3","tour":"MEN","match_date":"2025-04-21","tourney_id":"2025-0999","tourney_name":"Madrid","surface":"Clay"},
    ]).to_parquet(warehouse / "matches.parquet", index=False)
    pd.DataFrame([
        {"canonical_event_id":"MEN:0999","canonical_name":"Madrid","aliases":"Madrid","tour":"MEN","start_year":2025,"end_year":2026,"city":"Madrid","country":"Spain","continent":"Europe","latitude":40.4,"longitude":-3.7,"timezone":"Europe/Madrid","altitude_m":657,"surface":"Clay","indoor":False,"source_quality":"test"},
    ]).to_csv(registry_dir / "tournaments.csv", index=False)

    client = FakeRangeClient()
    result = build_weather_cache(tmp_path, client=client)

    assert len(client.calls) == 2
    cache = pd.read_parquet(tmp_path / "context_weather" / "weather_by_event_date.parquet")
    assert set(cache["match_date"].dt.strftime("%Y-%m-%d")) == {"2025-04-21", "2026-04-20", "2026-04-22"}
    assert cache["weather_temperature_c"].notna().all()
    assert result["requested_event_years"] == 2
    assert result["weather_rows"] == 3


def test_unresolved_venue_is_reported_not_guessed(tmp_path: Path):
    warehouse = tmp_path / "context_warehouse"
    registry_dir = tmp_path / "context_registry"
    warehouse.mkdir()
    registry_dir.mkdir()
    pd.DataFrame([
        {"match_id":"m1","tour":"MEN","match_date":"2026-04-20","tourney_id":"2026-7777","tourney_name":"Mystery","surface":"Hard"},
    ]).to_parquet(warehouse / "matches.parquet", index=False)
    pd.DataFrame(columns=["canonical_event_id","canonical_name","aliases","tour","start_year","end_year","latitude","longitude","timezone"]).to_csv(registry_dir / "tournaments.csv", index=False)

    result = build_weather_cache(tmp_path, client=FakeRangeClient())
    assert result["unresolved_matches"] == 1
    cache = pd.read_parquet(tmp_path / "context_weather" / "weather_by_event_date.parquet")
    assert cache.empty
