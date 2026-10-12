import numpy as np
import pandas as pd

import v5_full_context_live as live_context
from v5_full_context_live import _target_rows
from v5_interactive_production import _interactive_context_fixture


def test_indoor_and_surface_are_independent_dimensions():
    rows = _target_rows({
        "fixture_id": "fx-finals",
        "start_time_utc": "2026-11-12T19:00:00Z",
        "tournament": "Nitto ATP Finals",
        "tour": "MEN",
        "surface": "Hard",
        "best_of": 3,
        "player1": "Alpha",
        "player2": "Beta",
    })
    assert rows.iloc[0]["surface"] == "Hard"
    assert rows.iloc[0]["indoor_outdoor"] == "Indoor"


def test_v5_registry_environment_fallback_is_explicit_when_courtspeed_is_missing():
    helper = getattr(live_context, "_effective_environment", None)
    assert helper is not None
    environment, source = helper(pd.Series({
        "environment": np.nan,
        "indoor_outdoor": np.nan,
        "venue_indoor": True,
        "environment_source": "missing",
    }))
    assert environment == "Indoor"
    assert source == "V5 registry"


def test_interactive_context_passes_environment_and_internal_court_speed_override():
    prepared = {
        "first": pd.Series({
            "fixture_id": "fx1",
            "start_time_utc": "2026-10-28T18:00:00Z",
            "tournament_id": "p",
            "round": "R32",
            "v5_environment_override": "Outdoor",
            "v5_court_speed_override": 0.27,
            "v5_cpi_override": 41.2,
            "v5_ace_rate_override": 12.4,
            "v5_rally_length_override": 3.72,
            "v5_rad_override": 0.95,
            "v5_altitude_override": 55,
            "v5_ball_type_override": "Test Ball",
        }),
        "tournament": "Paris Masters",
        "tour": "MEN",
        "surface": "Hard",
        "best_of": 3,
        "p1": "Alpha",
        "p2": "Beta",
        "rating_p1": pd.Series({"rank": 10}),
        "rating_p2": pd.Series({"rank": 20}),
    }
    fixture = _interactive_context_fixture(prepared)
    assert fixture["environment"] == "Outdoor"
    assert fixture["court_speed_override"] == 0.27
    assert fixture["external_cpi_override"] == 41.2
    assert fixture["external_ace_rate_pct_override"] == 12.4
    assert fixture["external_rally_length_override"] == 3.72
    assert fixture["external_relative_air_density_override"] == 0.95
    assert fixture["external_altitude_m_override"] == 55.0
    assert fixture["external_ball_type_override"] == "Test Ball"
