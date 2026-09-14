from pathlib import Path
import json

import pandas as pd

from v5_courtspeed_fetch import parse_metric_table
from v5_refresh_court_conditions import merge_courtspeed_snapshot, validate_snapshot


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


def test_refresh_workflow_is_daily_manual_and_does_not_touch_oddspapi():
    text = Path(".github/workflows/courtspeed_conditions_refresh.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in text
    assert "schedule:" in text
    assert text.count("- cron:") == 1
    assert "v5_refresh_court_conditions.py" in text
    assert "oddspapi" not in text.lower()
