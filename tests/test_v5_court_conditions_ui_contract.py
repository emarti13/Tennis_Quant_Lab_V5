from pathlib import Path


def test_live_context_suppresses_outdoor_weather_for_indoor_matches():
    source = Path("v5_full_context_live.py").read_text(encoding="utf-8")
    assert 'environment == "Indoor"' in source
    assert '"weather_temperature_c": np.nan if indoor' in source
    assert '"weather_wind_speed_kmh": np.nan if indoor' in source
