from pathlib import Path


def test_interactive_production_accepts_all_court_condition_overrides():
    source = Path("v5_interactive_production.py").read_text(encoding="utf-8")
    for label in (
        "Environment", "Court Speed", "CPI", "Ace Rate %", "Rally Length",
        "Relative Air Density", "Altitude m", "Ball Type",
    ):
        assert label in source
    assert "v5_environment_override" in source
    assert "v5_court_speed_override" in source


def test_live_context_suppresses_outdoor_weather_for_indoor_matches():
    source = Path("v5_full_context_live.py").read_text(encoding="utf-8")
    assert 'environment == "Indoor"' in source
    assert '"weather_temperature_c": np.nan if indoor' in source
    assert '"weather_wind_speed_kmh": np.nan if indoor' in source


def test_cpi_is_kept_separate_from_internal_court_speed_state():
    source = Path("v5_full_context_live.py").read_text(encoding="utf-8")
    assert '"external_cpi": conditions.get("cpi")' in source
    assert '"court_speed": pick("court_speed_override", "court_speed_blended", "court_speed")' in source
    assert 'court_speed_blended": conditions.get("cpi")' not in source
