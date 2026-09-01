import pandas as pd

from v5_tournament_registry import TournamentRegistry, normalize_event_name


def _registry_frame():
    return pd.DataFrame([
        {
            "canonical_event_id": "us_open",
            "canonical_name": "US Open",
            "aliases": "U.S. Open|US Open Tennis Championships",
            "tour": "BOTH",
            "start_year": 1978,
            "end_year": None,
            "city": "New York",
            "country": "USA",
            "latitude": 40.7498,
            "longitude": -73.8469,
            "timezone": "America/New_York",
            "altitude_m": 6.0,
            "surface": "Hard",
            "indoor": False,
            "source_quality": "verified",
        },
        {
            "canonical_event_id": "madrid_open",
            "canonical_name": "Madrid Open",
            "aliases": "Mutua Madrid Open",
            "tour": "BOTH",
            "start_year": 2009,
            "end_year": None,
            "city": "Madrid",
            "country": "Spain",
            "latitude": 40.3687,
            "longitude": -3.6840,
            "timezone": "Europe/Madrid",
            "altitude_m": 657.0,
            "surface": "Clay",
            "indoor": False,
            "source_quality": "verified",
        },
    ])


def test_normalize_event_name_removes_punctuation_and_sponsor_noise_lightly():
    assert normalize_event_name("U.S. Open") == "us open"
    assert normalize_event_name("  US   Open ") == "us open"


def test_alias_resolution_is_deterministic_and_year_aware():
    registry = TournamentRegistry(_registry_frame())
    a = registry.resolve("U.S. Open", "MEN", 2026)
    b = registry.resolve("US Open Tennis Championships", "WTA", 2026)
    assert a.canonical_event_id == "us_open"
    assert b.canonical_event_id == "us_open"
    assert a.timezone == "America/New_York"


def test_unknown_event_is_explicit_not_guessed():
    registry = TournamentRegistry(_registry_frame())
    result = registry.resolve("Mystery Invitational", "MEN", 2026)
    assert result.canonical_event_id is None
    assert result.source_quality == "unresolved"
    assert result.latitude is None


def test_wrong_year_does_not_use_future_venue_record():
    frame = _registry_frame().copy()
    frame.loc[frame["canonical_event_id"] == "madrid_open", "start_year"] = 2030
    registry = TournamentRegistry(frame)
    result = registry.resolve("Madrid Open", "MEN", 2026)
    assert result.canonical_event_id is None
