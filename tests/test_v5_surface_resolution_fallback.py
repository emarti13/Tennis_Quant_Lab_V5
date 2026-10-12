"""Surface comes only from the tournament authority (CLAUDE.md, resolve_fixture_surface).

These tests used to assert a historical-surface fallback and a "Hard — review"
default. Both were retired: an event the authority cannot identify must fail
closed, even when match history suggests a surface.
"""
import pandas as pd
import pytest

import v5_daily_batch


def test_recurring_event_resolves_through_tournament_authority():
    surface, source = v5_daily_batch.resolve_fixture_surface(
        "WTA Sao Paulo, Brazil Women, Singles",
        start_time_utc="2026-09-14T13:00:00Z",
        tour="WTA",
    )
    assert surface == "Hard"
    assert source == "Tournament authority"


def test_historical_rows_never_stand_in_for_the_authority():
    history = pd.DataFrame([
        {"tourney_name": "Mystery Invitational", "match_date": "2025-09-01", "surface": "Clay"},
        {"tourney_name": "Mystery Invitational", "match_date": "2025-09-02", "surface": "Clay"},
    ])
    with pytest.raises(ValueError, match="TOURNAMENT_IDENTITY_UNRESOLVED"):
        v5_daily_batch.resolve_fixture_surface(
            "Mystery Invitational",
            start_time_utc="2026-09-14T13:00:00Z",
            context_history=history,
        )


def test_unknown_event_fails_closed_instead_of_defaulting_to_hard():
    with pytest.raises(ValueError, match="TOURNAMENT_IDENTITY_UNRESOLVED"):
        v5_daily_batch.resolve_fixture_surface("Mystery Open", start_time_utc="2026-09-14T13:00:00Z")
