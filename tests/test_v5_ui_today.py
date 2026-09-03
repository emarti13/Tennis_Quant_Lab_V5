from __future__ import annotations

import pandas as pd


def test_ui_number_formatting_and_signal_classes():
    from v5_ui_theme import (
        format_american_odds,
        format_edge,
        format_probability,
        signal_class,
    )

    assert format_probability(0.673) == "67.3%"
    assert format_probability(None) == "—"
    assert format_american_odds(-203) == "-203"
    assert format_american_odds(145) == "+145"
    assert format_american_odds(None) == "—"
    assert format_edge(0.0841) == "+8.4%"
    assert format_edge(-0.021) == "-2.1%"
    assert format_edge(None) == "—"
    assert signal_class("BET") == "signal-bet"
    assert signal_class("PASS") == "signal-pass"
    assert signal_class("unknown") == "signal-neutral"


def test_prepare_today_board_preserves_source_values_and_ranks_signal_first():
    from v5_ui_today import prepare_today_board

    source = pd.DataFrame(
        [
            {
                "Fixture ID": "a",
                "Player 1": "A",
                "Player 2": "B",
                "P1 V5 %": 0.61,
                "P1 Fair": -156,
                "P1 ML EV": 0.05,
                "P1 ML Signal": "LEAN",
                "Expected Margin": 2.1,
                "Expected Total": 22.4,
            },
            {
                "Fixture ID": "b",
                "Player 1": "C",
                "Player 2": "D",
                "P1 V5 %": 0.58,
                "P1 Fair": -138,
                "P1 ML EV": 0.03,
                "P1 ML Signal": "BET",
                "Expected Margin": 1.3,
                "Expected Total": 21.8,
            },
        ]
    )

    out = prepare_today_board(source)

    assert out.iloc[0]["Fixture ID"] == "b"
    assert out.loc[out["Fixture ID"] == "a", "P1 V5 %"].iloc[0] == 0.61
    assert out.loc[out["Fixture ID"] == "a", "P1 Fair"].iloc[0] == -156
    assert out.loc[out["Fixture ID"] == "a", "Expected Margin"].iloc[0] == 2.1
    assert out.loc[out["Fixture ID"] == "a", "Expected Total"].iloc[0] == 22.4


def test_primary_market_uses_best_existing_signal_then_existing_ev():
    from v5_ui_today import primary_market_for_row

    row = pd.Series(
        {
            "Player 1": "A",
            "Player 2": "B",
            "P1 ML EV": 0.09,
            "P1 ML Signal": "LEAN",
            "P1 ML": -110,
            "P1 Spread": -2.5,
            "P1 Spread Odds": -105,
            "P1 Spread EV": 0.04,
            "P1 Spread Signal": "BET",
            "Over EV": 0.11,
            "Over Signal": "BET",
            "Total": 22.5,
            "Over Odds": -108,
        }
    )

    primary = primary_market_for_row(row)

    assert primary["signal"] == "BET"
    assert primary["family"] == "total"
    assert primary["selection"] == "Over 22.5"
    assert primary["edge"] == 0.11
    assert primary["market_odds"] == -108


def test_why_it_stands_out_is_deterministic_and_uses_only_present_fields():
    from v5_ui_today import why_it_stands_out

    row = pd.Series(
        {
            "Agreement": 0.91,
            "Model Gap": 0.03,
            "Expected Margin": 4.8,
            "Expected Total": 23.7,
        }
    )

    text = why_it_stands_out(row)

    assert "agreement" in text.lower()
    assert "margin" in text.lower()
    assert "travel" not in text.lower()
    assert "fatigue" not in text.lower()
