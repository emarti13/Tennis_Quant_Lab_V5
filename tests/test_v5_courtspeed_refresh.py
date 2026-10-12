from pathlib import Path

import pandas as pd

from v5_courtspeed_fetch import parse_metric_table
from v5_refresh_court_conditions import (
    count_updated_fields,
    discover_target_events,
    merge_courtspeed_snapshot,
    validate_snapshot,
)


def test_parse_metric_table_extracts_year_values_and_conditions():
    html = """
    <table>
      <thead><tr><th>Tournament</th><th>’25</th><th>’26</th></tr></thead>
      <tbody>
        <tr><td>Paris Hard · indoor</td><td>35.1</td><td>40.2</td></tr>
      </tbody>
    </table>
    """
    out = parse_metric_table(html, metric="cpi", fetched_at_utc="2026-09-14T04:00:00+00:00")
    assert list(out["year"]) == [2025, 2026]
    assert set(out["event_key"]) == {"paris_masters"}
    assert set(out["surface_type"]) == {"Hard"}
    assert set(out["environment"]) == {"Indoor"}
    assert out.loc[out["year"].eq(2026), "cpi"].iloc[0] == 40.2


def test_unknown_source_event_is_reported_not_persisted():
    html = """
    <table>
      <thead><tr><th>Tournament</th><th>’26</th></tr></thead>
      <tbody>
        <tr><td>Paris Hard · indoor</td><td>40.2</td></tr>
        <tr><td>Mystery Invitational Hard</td><td>38.8</td></tr>
      </tbody>
    </table>
    """
    out = parse_metric_table(html, metric="cpi", fetched_at_utc="2026-09-14T04:00:00+00:00")
    assert set(out["event_key"]) == {"paris_masters"}
    assert out.attrs["unresolved_events"] == ["Mystery Invitational Hard"]


def test_partial_refresh_preserves_existing_non_null_values():
    existing = pd.DataFrame([{
        "event_key": "paris_masters", "event_name": "Paris", "year": 2026,
        "surface_type": "Hard", "environment": "Indoor", "cpi": 35.1,
        "ace_rate_pct": 10.5, "rally_length": 4.0, "relative_air_density": None,
        "altitude_m": 47, "ball_type": "Penn/Head", "overall_speed_rating": "Med fast",
        "source_name": "CourtSpeed", "source_updated_at": "2026-08-27",
        "source_refreshed_at": "2026-09-13T04:00:00+00:00",
    }])
    fresh = pd.DataFrame([{
        "event_key": "paris_masters", "event_name": "Paris", "year": 2026,
        "surface_type": "Hard", "environment": "Indoor", "cpi": 40.2,
        "ace_rate_pct": None, "rally_length": None, "relative_air_density": None,
        "altitude_m": None, "ball_type": None, "overall_speed_rating": None,
        "source_name": "CourtSpeed", "source_updated_at": "2026-09-14",
        "source_refreshed_at": "2026-09-14T04:00:00+00:00",
    }])
    merged = merge_courtspeed_snapshot(existing, fresh)
    row = merged.iloc[0]
    assert row["cpi"] == 40.2
    assert row["ace_rate_pct"] == 10.5
    assert row["ball_type"] == "Penn/Head"
    assert row["source_refreshed_at"] == "2026-09-14T04:00:00+00:00"
    assert count_updated_fields(existing, fresh) == 1


def test_target_discovery_uses_canonical_future_market_fixture(tmp_path):
    path = tmp_path / "market_board_input.csv"
    pd.DataFrame([
        {"tournament": "Paris Masters", "start_time_utc": "2026-09-20T12:00:00Z"},
        {"tournament": "Cincinnati", "start_time_utc": "2026-11-20T12:00:00Z"},
    ]).to_csv(path, index=False)
    out = discover_target_events(path, now_utc="2026-09-14T00:00:00Z", horizon_days=21)
    assert out == ["paris_masters"]


def test_validation_rejects_duplicate_event_year_rows():
    duplicate = pd.DataFrame([
        {"event_key": "miami", "year": 2026, "surface_type": "Hard", "environment": "Outdoor"},
        {"event_key": "miami", "year": 2026, "surface_type": "Hard", "environment": "Outdoor"},
    ])
    try:
        validate_snapshot(duplicate)
    except ValueError as exc:
        assert "duplicate" in str(exc).lower()
    else:
        raise AssertionError("duplicate snapshot rows must be rejected")
