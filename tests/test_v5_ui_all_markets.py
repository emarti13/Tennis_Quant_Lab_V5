from __future__ import annotations

import pandas as pd


def test_filter_all_markets_preserves_source_values_and_only_filters_rows():
    from v5_ui_all_markets import filter_all_markets

    source = pd.DataFrame(
        [
            {"Fixture ID": "a", "Tour": "MEN", "Tournament": "US Open", "Best Of": 5, "Best Signal": "BET", "Primary Market Family": "spread", "P1 V5 %": 0.67, "Primary Edge": 0.09},
            {"Fixture ID": "b", "Tour": "WTA", "Tournament": "US Open", "Best Of": 3, "Best Signal": "LEAN", "Primary Market Family": "total", "P1 V5 %": 0.58, "Primary Edge": 0.05},
            {"Fixture ID": "c", "Tour": "MEN", "Tournament": "Cincinnati", "Best Of": 3, "Best Signal": "PASS", "Primary Market Family": "moneyline", "P1 V5 %": 0.72, "Primary Edge": -0.01},
        ]
    )

    out = filter_all_markets(
        source,
        tour="MEN",
        tournament="US Open",
        market_family="spread",
        signal="BET",
        best_of=5,
    )

    assert out["Fixture ID"].tolist() == ["a"]
    assert out.iloc[0]["P1 V5 %"] == 0.67
    assert out.iloc[0]["Primary Edge"] == 0.09
    assert source.shape == (3, 8)


def test_default_all_markets_columns_are_compact_but_keep_decision_fields():
    from v5_ui_all_markets import default_columns

    frame = pd.DataFrame(
        columns=[
            "Fixture ID", "Start", "Tournament", "Player 1", "Player 2", "Tour", "Best Of",
            "Best Signal", "Primary Market", "P1 V5 %", "P1 Fair", "Primary Market Odds", "Primary Edge",
            "Expected Margin", "Expected Total", "Agreement", "Model Gap", "some_raw_debug_field",
        ]
    )

    cols = default_columns(frame)

    for required in ("Fixture ID", "Player 1", "Player 2", "Best Signal", "Primary Market", "Primary Edge"):
        assert required in cols
    assert "some_raw_debug_field" not in cols
