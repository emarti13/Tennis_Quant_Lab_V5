import pandas as pd

import v5_daily_batch


def test_recurring_unmapped_event_uses_historical_context_surface_instead_of_review_default():
    history = pd.DataFrame([
        {
            "tourney_name": "WTA Sao Paulo, Brazil Women, Singles",
            "match_date": "2025-09-08",
            "surface": "Hard",
        },
        {
            "tourney_name": "WTA Sao Paulo, Brazil Women, Singles",
            "match_date": "2025-09-09",
            "surface": "Hard",
        },
    ])

    surface, source = v5_daily_batch.resolve_fixture_surface(
        "WTA Sao Paulo, Brazil Women, Singles",
        start_time_utc="2026-09-14T13:00:00Z",
        context_history=history,
    )

    assert surface == "Hard"
    assert source == "V5 historical event surface"


def test_historical_surface_fallback_never_uses_future_match_rows():
    history = pd.DataFrame([
        {
            "tourney_name": "Mystery Invitational",
            "match_date": "2026-09-15",
            "surface": "Clay",
        }
    ])

    surface, source = v5_daily_batch.resolve_fixture_surface(
        "Mystery Invitational",
        start_time_utc="2026-09-14T13:00:00Z",
        context_history=history,
    )

    assert surface == "Hard"
    assert source == "Auto default — review"


def test_conflicting_historical_surfaces_fail_closed_instead_of_guessing():
    history = pd.DataFrame([
        {"tourney_name": "Mystery Invitational", "match_date": "2025-09-01", "surface": "Hard"},
        {"tourney_name": "Mystery Invitational", "match_date": "2025-09-02", "surface": "Clay"},
    ])

    surface, source = v5_daily_batch.resolve_fixture_surface(
        "Mystery Invitational",
        start_time_utc="2026-09-14T13:00:00Z",
        context_history=history,
    )

    assert surface == "Hard"
    assert source == "Auto default — review"


def test_truly_unknown_event_still_fails_closed_to_review_default():
    history = pd.DataFrame([
        {"tourney_name": "Different Event", "match_date": "2025-01-01", "surface": "Clay"}
    ])

    surface, source = v5_daily_batch.resolve_fixture_surface(
        "Mystery Open",
        start_time_utc="2026-09-14T13:00:00Z",
        context_history=history,
    )

    assert surface == "Hard"
    assert source == "Auto default — review"
