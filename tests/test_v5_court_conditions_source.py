import pandas as pd

from v5_court_conditions_source import lookup_court_conditions, normalize_event_name


def _snapshot():
    return pd.DataFrame([
        {
            "event_key": "paris_masters", "event_name": "Paris Masters", "year": 2024,
            "surface_type": "Hard", "environment": "Indoor", "cpi": 45.5,
            "ace_rate_pct": 13.3, "rally_length": 3.78, "relative_air_density": None,
            "altitude_m": 47, "ball_type": "Penn/Head", "overall_speed_rating": "Fast",
            "source_name": "CourtSpeed", "source_updated_at": "2026-08-27",
        },
        {
            "event_key": "paris_masters", "event_name": "Paris Masters", "year": 2025,
            "surface_type": "Hard", "environment": "Indoor", "cpi": 35.1,
            "ace_rate_pct": 10.5, "rally_length": 4.05, "relative_air_density": None,
            "altitude_m": 47, "ball_type": "Penn/Head", "overall_speed_rating": "Med fast",
            "source_name": "CourtSpeed", "source_updated_at": "2026-08-27",
        },
        {
            "event_key": "paris_masters", "event_name": "Paris Masters", "year": 2026,
            "surface_type": "Hard", "environment": "Indoor", "cpi": None,
            "ace_rate_pct": None, "rally_length": None, "relative_air_density": None,
            "altitude_m": 47, "ball_type": "Penn/Head", "overall_speed_rating": None,
            "source_name": "CourtSpeed", "source_updated_at": "2026-08-27",
        },
        {
            "event_key": "cincinnati", "event_name": "Cincinnati", "year": 2025,
            "surface_type": "Hard", "environment": "Outdoor", "cpi": 43.0,
            "ace_rate_pct": 12.8, "rally_length": 3.58, "relative_air_density": 0.922,
            "altitude_m": 240, "ball_type": "Wilson", "overall_speed_rating": "Fast",
            "source_name": "CourtSpeed", "source_updated_at": "2026-08-27",
        },
        {
            "event_key": "cincinnati", "event_name": "Cincinnati", "year": 2026,
            "surface_type": "Hard", "environment": "Outdoor", "cpi": 39.0,
            "ace_rate_pct": None, "rally_length": 3.82, "relative_air_density": 0.931,
            "altitude_m": 240, "ball_type": "Wilson", "overall_speed_rating": "Med fast",
            "source_name": "CourtSpeed", "source_updated_at": "2026-08-27",
        },
    ])


def test_aliases_normalize_to_stable_event_keys():
    assert normalize_event_name("Rolex Paris Masters") == "paris_masters"
    assert normalize_event_name("ATP Cincinnati") == "cincinnati"


def test_exact_year_values_win_and_environment_is_separate_from_surface():
    out = lookup_court_conditions("Paris Masters", 2025, _snapshot())
    assert out["surface_type"] == "Hard"
    assert out["environment"] == "Indoor"
    assert out["cpi"] == 35.1
    assert out["cpi_source_year"] == 2025
    assert out["source_quality"] == "exact"


def test_metric_specific_prior_fallback_never_looks_forward():
    out = lookup_court_conditions("Cincinnati", 2026, _snapshot())
    assert out["cpi"] == 39.0
    assert out["cpi_source_year"] == 2026
    assert out["ace_rate_pct"] == 12.8
    assert out["ace_rate_pct_source_year"] == 2025
    assert out["rally_length"] == 3.82
    assert out["rally_length_source_year"] == 2026
    assert out["source_quality"] == "prior_fallback"

    before = lookup_court_conditions("Cincinnati", 2024, _snapshot())
    assert before["cpi"] is None
    assert before["ace_rate_pct"] is None


def test_missing_event_returns_safe_unknown_record():
    out = lookup_court_conditions("Unknown Invitational", 2026, _snapshot())
    assert out["source_quality"] == "missing"
    assert out["cpi"] is None
    assert out["environment"] is None


def test_raw_external_cpi_is_not_internal_court_speed_state():
    out = lookup_court_conditions("Paris Masters", 2026, _snapshot())
    assert out["cpi"] == 35.1
    assert out["cpi_source_year"] == 2025
    assert "court_speed_blended" not in out
