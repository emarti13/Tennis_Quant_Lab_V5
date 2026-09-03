from __future__ import annotations


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
