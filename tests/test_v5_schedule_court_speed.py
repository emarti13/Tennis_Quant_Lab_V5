import numpy as np
import pandas as pd

from v5_court_speed import build_court_speed_features


def _row(event, when, residual, profile="slow_clay", altitude=20, surface="Clay", setting="Outdoor"):
    return {
        "canonical_event_id": event,
        "tour": "MEN",
        "surface": surface,
        "indoor": setting == "Indoor",
        "match_start": when,
        "speed_residual": residual,
        "schedule_speed_profile_family": profile,
        "schedule_setting": setting,
        "schedule_altitude_m": altitude,
    }


def test_schedule_structural_cohort_is_used_before_generic_surface_fallback():
    frame = pd.DataFrame([
        _row("MEN:event-a", "2025-04-01T12:00:00Z", 0.12),
        _row("MEN:event-b", "2026-04-01T12:00:00Z", np.nan),
    ])
    out = build_court_speed_features(frame)
    target = out.iloc[1]
    assert target["court_speed_prior_level"] == "schedule_structural"
    assert target["court_speed_structural_sample_size"] == 1
    assert np.isclose(target["court_speed_structural_prior"], 0.12)
    assert np.isclose(target["court_speed_historical_prior"], 0.12)


def test_same_event_history_has_precedence_over_structural_cohort():
    frame = pd.DataFrame([
        _row("MEN:event-a", "2025-04-01T12:00:00Z", 0.20),
        _row("MEN:event-b", "2025-04-02T12:00:00Z", 0.02),
        _row("MEN:event-a", "2026-04-01T12:00:00Z", np.nan),
    ])
    out = build_court_speed_features(frame)
    target = out.iloc[2]
    assert target["court_speed_prior_level"] == "same_event"
    assert np.isclose(target["court_speed_historical_prior"], 0.20)
    assert target["court_speed_structural_sample_size"] == 2


def test_altitude_band_prevents_false_structural_pooling():
    frame = pd.DataFrame([
        _row("MEN:event-a", "2025-04-01T12:00:00Z", 0.25, altitude=1800),
        _row("MEN:event-b", "2026-04-01T12:00:00Z", np.nan, altitude=20),
    ])
    out = build_court_speed_features(frame)
    target = out.iloc[1]
    assert target["court_speed_structural_sample_size"] == 0
    assert target["court_speed_prior_level"] in {"tour_surface_indoor", "none"}
