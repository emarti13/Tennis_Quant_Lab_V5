import numpy as np
import pandas as pd

from v5_weather_features import attach_live_weather


def test_live_weather_replaces_numeric_placeholder_metadata_columns_with_text():
    """Parquet history can infer all-null weather metadata as float before live rows are appended."""
    rows = pd.DataFrame(
        {
            "match_id": ["live_fixture", "live_fixture"],
            "result_file": ["LIVE_TARGET", "LIVE_TARGET"],
            "match_date": [pd.Timestamp("2026-09-03 16:40:00"), pd.Timestamp("2026-09-03 16:40:00")],
            "venue_latitude": [np.nan, np.nan],
            "venue_longitude": [np.nan, np.nan],
            "venue_timezone": [np.nan, np.nan],
            "weather_source_quality": pd.Series([np.nan, np.nan], dtype="float64"),
            "weather_forecast_hour": pd.Series([np.nan, np.nan], dtype="float64"),
        }
    )

    out = attach_live_weather(rows, client=object())

    assert out["weather_source_quality"].tolist() == ["unresolved_live_venue", "unresolved_live_venue"]
    assert out["weather_forecast_hour"].tolist() == ["", ""]
