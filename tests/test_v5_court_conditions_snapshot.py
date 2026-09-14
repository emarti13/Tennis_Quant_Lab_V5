from pathlib import Path

import pandas as pd

from v5_court_conditions_source import load_condition_snapshot, lookup_court_conditions


def test_repository_snapshot_covers_current_courtspeed_events():
    path = Path("data/court_conditions/courtspeed_snapshot.csv")
    assert path.exists()
    df = load_condition_snapshot(path)
    assert len(df) == 42
    assert set(df["year"].dropna().astype(int)) == {2024, 2025, 2026}
    for event in ("paris_masters", "atp_finals", "cincinnati", "wimbledon", "madrid"):
        assert event in set(df["event_key"])


def test_2026_indoor_events_use_current_metadata_and_prior_measured_speed_when_needed():
    df = load_condition_snapshot()
    paris = lookup_court_conditions("Rolex Paris Masters", 2026, df)
    finals = lookup_court_conditions("Nitto ATP Finals", 2026, df)

    assert paris["environment"] == "Indoor"
    assert paris["environment_source_year"] == 2026
    assert paris["cpi"] == 35.1
    assert paris["cpi_source_year"] == 2025
    assert paris["ball_type"] == "Penn/Head"
    assert paris["ball_type_source_year"] == 2026

    assert finals["environment"] == "Indoor"
    assert finals["cpi"] == 40.1
    assert finals["cpi_source_year"] == 2025
    assert finals["ball_type"] == "Dunlop"
