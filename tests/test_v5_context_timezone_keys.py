import pandas as pd

from build_v5_context_matchups import _normalize_calendar_date


def test_normalize_calendar_date_strips_timezone_without_changing_match_day():
    value = pd.Timestamp("2025-01-10 00:00:00", tz="UTC")
    out = _normalize_calendar_date(value)
    assert out == pd.Timestamp("2025-01-10")
    assert out.tzinfo is None


def test_normalize_calendar_date_handles_naive_iso_date():
    assert _normalize_calendar_date("2026-08-30") == pd.Timestamp("2026-08-30")
