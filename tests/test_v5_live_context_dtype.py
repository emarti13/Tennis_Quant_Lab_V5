import numpy as np
import pandas as pd

from v5_travel_features import build_travel_features


def test_travel_features_replace_numeric_placeholder_columns_with_text_metadata():
    """Live targets may append to warehouse columns inferred as float when history is all-null."""
    rows = pd.DataFrame(
        {
            "player_name": ["Player A", "Player B"],
            "match_date": ["2026-09-03", "2026-09-03"],
            "tour": ["MEN", "MEN"],
            "tourney_id": ["live-a", "live-a"],
            "tourney_name": ["Unknown Live Event", "Unknown Live Event"],
            "surface": ["Hard", "Hard"],
            # These reproduce the parquet/concat state seen in the live pipeline:
            # metadata columns exist but are numeric because historical values were null.
            "venue_source_quality": pd.Series([np.nan, np.nan], dtype="float64"),
            "venue_resolution_method": pd.Series([np.nan, np.nan], dtype="float64"),
            "travel_context_quality": pd.Series([np.nan, np.nan], dtype="float64"),
        }
    )

    out = build_travel_features(rows, pd.DataFrame())

    assert out["venue_source_quality"].tolist() == ["unresolved", "unresolved"]
    assert out["venue_resolution_method"].tolist() == ["unresolved", "unresolved"]
    assert out["travel_context_quality"].tolist() == ["no_prior", "no_prior"]
