from __future__ import annotations

import pandas as pd


def test_page_registry_makes_daily_board_default_and_keeps_decision_feed_separate():
    from v5_ui_navigation import PAGE_ORDER, page_registry

    registry = page_registry()

    assert PAGE_ORDER[0] == "Daily Board"
    assert PAGE_ORDER[:6] == [
        "Daily Board",
        "Decision Feed",
        "Match Detail",
        "All Markets",
        "Performance",
        "Model Health",
    ]
    assert "Matchup Lab" in PAGE_ORDER
    assert set(PAGE_ORDER).issubset(registry)


def test_match_detail_sections_preserve_source_model_values():
    from v5_ui_match_detail import match_detail_sections

    row = pd.Series(
        {
            "Fixture ID": "fx-1",
            "Player 1": "A",
            "Player 2": "B",
            "P1 V5 %": 0.643,
            "P1 Fair": -180,
            "Expected Margin": 3.25,
            "Expected Total": 22.7,
            "Best Signal": "BET",
            "Primary Market": "A -2.5",
            "Primary Edge": 0.074,
            "Primary Market Odds": -110,
            "Agreement": 0.88,
            "Model Gap": 0.025,
            "best_of": 3,
        }
    )
    prices = pd.DataFrame(
        [
            {"fixture_id": "fx-1", "bookmaker": "Book A", "market": "spread", "line": -2.5, "odds": -110},
            {"fixture_id": "fx-2", "bookmaker": "Book B", "market": "spread", "line": -1.5, "odds": -105},
        ]
    )

    sections = match_detail_sections(row, prices)

    assert sections["overview"]["p1_probability"] == 0.643
    assert sections["overview"]["p1_fair"] == -180
    assert sections["overview"]["expected_margin"] == 3.25
    assert sections["overview"]["expected_total"] == 22.7
    assert sections["overview"]["signal"] == "BET"
    assert sections["market_board"]["fixture_id"].tolist() == ["fx-1"]
    assert row["P1 V5 %"] == 0.643


def test_match_detail_missing_optional_context_is_explicitly_unavailable():
    from v5_ui_match_detail import match_detail_sections

    row = pd.Series({"Fixture ID": "fx-1", "Player 1": "A", "Player 2": "B"})
    sections = match_detail_sections(row, pd.DataFrame())

    assert sections["context"]["rest_workload"] == "Unavailable"
    assert sections["context"]["travel"] == "Unavailable"
    assert sections["context"]["court"] == "Unavailable"
    assert sections["context"]["player_state"] == "Unavailable"
