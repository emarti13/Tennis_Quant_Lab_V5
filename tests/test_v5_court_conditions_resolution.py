import pandas as pd

from v5_court_conditions_source import resolve_court_conditions


def _snapshot():
    return pd.DataFrame([
        {
            "event_key": "paris_masters", "event_name": "Paris", "year": 2025,
            "surface_type": "Hard", "environment": "Indoor", "cpi": 35.1,
            "ace_rate_pct": 10.5, "rally_length": 4.0, "relative_air_density": None,
            "altitude_m": 47, "ball_type": "Penn/Head", "overall_speed_rating": "Med fast",
            "source_name": "CourtSpeed", "source_updated_at": "2026-09-10",
            "source_refreshed_at": "2026-09-14T00:17:00+00:00",
        },
        {
            "event_key": "paris_masters", "event_name": "Paris", "year": 2026,
            "surface_type": "Hard", "environment": "Indoor", "cpi": None,
            "ace_rate_pct": None, "rally_length": None, "relative_air_density": None,
            "altitude_m": 47, "ball_type": "Penn/Head", "overall_speed_rating": None,
            "source_name": "CourtSpeed", "source_updated_at": "2026-09-10",
            "source_refreshed_at": "2026-09-14T00:17:00+00:00",
        },
    ])


def test_courtspeed_exact_or_prior_year_outranks_v5_when_fresh():
    out = resolve_court_conditions(
        "Paris Masters", 2026,
        snapshot=_snapshot(),
        refresh_status={"state": "READY", "run_timestamp": "2026-09-14T00:17:00+00:00"},
        now_utc="2026-09-14T03:00:00+00:00",
        v5_fallback={"cpi": 99.0, "surface_type": "Clay", "environment": "Outdoor"},
    )
    assert out["cpi"] == 35.1
    assert out["cpi_source"] == "CourtSpeed"
    assert out["cpi_source_year"] == 2025
    assert out["surface_type"] == "Hard"
    assert out["environment"] == "Indoor"
    assert out["production_blocking"] is False


def test_missing_courtspeed_field_falls_only_that_field_to_v5():
    out = resolve_court_conditions(
        "Paris Masters", 2026,
        snapshot=_snapshot(),
        refresh_status={"state": "READY", "run_timestamp": "2026-09-14T00:17:00+00:00"},
        now_utc="2026-09-14T03:00:00+00:00",
        v5_fallback={"relative_air_density": 0.97},
    )
    assert out["cpi_source"] == "CourtSpeed"
    assert out["relative_air_density"] == 0.97
    assert out["rad_source"] == "V5"
    assert out["courtspeed_health"] == "READY"
    assert out["production_blocking"] is False


def test_stale_courtspeed_falls_to_v5_without_blocking():
    out = resolve_court_conditions(
        "Paris Masters", 2026,
        snapshot=_snapshot(),
        refresh_status={"state": "READY", "run_timestamp": "2026-08-01T00:00:00+00:00"},
        now_utc="2026-09-14T03:00:00+00:00",
        max_source_age_hours=72,
        v5_fallback={"cpi": 1.25, "surface_type": "Hard", "environment": "Indoor"},
        schedule=pd.DataFrame(),
    )
    assert out["cpi"] == 1.25
    assert out["cpi_source"] == "V5"
    assert out["source_freshness"] == "FALLBACK_V5"
    assert out["courtspeed_health"] == "COURTSPEED_UNAVAILABLE"
    assert out["production_blocking"] is False


def test_canonical_court_file_is_used_when_courtspeed_has_no_current_event():
    schedule = pd.DataFrame([{
        "Year": 2026,
        "Circuit Tour": "ATP 250",
        "Tournament Name": "Testville Open (2026)",
        "City Venue": "Testville",
        "Surface": "Hard",
        "Setting": "Outdoor",
        "Altitude (m)": 612,
        "Altitude (ft)": 2008,
        "Speed Profile": "High Altitude / Fast Air",
        "Ball Characteristics": "Fast ball",
    }])
    out = resolve_court_conditions(
        "Testville Open", 2026,
        snapshot=pd.DataFrame(),
        refresh_status={"state": "STALE_LKG", "run_timestamp": "2026-09-15T00:17:00+00:00"},
        now_utc="2026-09-15T01:00:00+00:00",
        v5_fallback={"surface_type": "Hard"},
        schedule=schedule,
    )
    assert out["surface_type"] == "Hard"
    assert out["surface_source"] == "CanonicalCourtFile"
    assert out["altitude_m"] == 612
    assert out["altitude_source"] == "CanonicalCourtFile"
    assert out["source_freshness"] == "CANONICAL_COURT_FILE"
    assert out["production_blocking"] is False


def test_missing_every_court_source_still_returns_runnable_unknown():
    out = resolve_court_conditions(
        "Unknown Event", 2026,
        snapshot=pd.DataFrame(),
        refresh_status={},
        schedule=pd.DataFrame(),
    )
    assert out["source_freshness"] == "UNKNOWN_NONBLOCKING"
    assert out["production_blocking"] is False
    assert out["cpi"] is None
