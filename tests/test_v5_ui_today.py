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


def test_today_summary_reports_best_edge_and_qualified_play_count():
    from v5_ui_today import today_summary

    board = pd.DataFrame(
        [
            {"Best Signal": "BET", "Primary Edge": 0.084},
            {"Best Signal": "LEAN", "Primary Edge": 0.051},
            {"Best Signal": "PASS", "Primary Edge": -0.02},
        ]
    )
    market_feed = pd.DataFrame(
        [
            {"fixture_id": "a", "bookmaker": "Book A"},
            {"fixture_id": "a", "bookmaker": "Book B"},
            {"fixture_id": "b", "bookmaker": "Book A"},
        ]
    )

    out = today_summary(board, market_feed, "2026-09-02T21:00:00Z")

    assert out["best_edge"] == 0.084
    assert out["qualified_plays"] == 2
    assert out["matches_analyzed"] == 3
    assert out["markets_live"] == 2
    assert out["snapshot"] == "2026-09-02T21:00:00Z"


def test_match_card_html_contains_primary_decision_fields():
    from v5_ui_today import match_card_html

    row = pd.Series(
        {
            "Player 1": "Jannik Sinner",
            "Player 2": "Alex de Minaur",
            "Tournament": "US Open",
            "Start": "2026-09-03T23:00:00Z",
            "Tour": "MEN",
            "Best Of": 5,
            "P1 V5 %": 0.67,
            "P1 Fair": -203,
            "Best Signal": "BET",
            "Primary Market": "Jannik Sinner -4.5",
            "Primary Edge": 0.135,
            "Primary Market Odds": -115,
            "Agreement": 0.90,
            "Expected Margin": 5.1,
        }
    )

    html = match_card_html(row)

    assert "Jannik Sinner" in html
    assert "Alex de Minaur" in html
    assert "US Open" in html
    assert "Bo5" in html
    assert "Jannik Sinner -4.5" in html
    assert "BET" in html
    assert "67.0%" in html
    assert "-203" in html
    assert "-115" in html
    assert "+13.5%" in html


def test_render_today_results_has_deliberate_empty_state():
    from v5_ui_today import render_today_results

    class FakeSt:
        def __init__(self):
            self.info_messages = []
            self.markdown_messages = []

        def info(self, message):
            self.info_messages.append(message)

        def markdown(self, message, **kwargs):
            self.markdown_messages.append(message)

    fake = FakeSt()
    render_today_results(fake, pd.DataFrame(), pd.DataFrame(), "Unknown")

    assert fake.info_messages
    assert "no modeled matches" in fake.info_messages[0].lower()
