from pathlib import Path

import pandas as pd

from v5_ui_today import match_card_html


def _row():
    return pd.Series({
        "Fixture ID": "fx1",
        "Tournament": "Test Open",
        "Start": "2026-09-03T18:00:00Z",
        "Tour": "MEN",
        "Surface": "Hard",
        "Best Of": 3,
        "Player 1": "Alpha",
        "Player 2": "Beta",
        "P1 V5 %": 0.64,
        "P1 Fair": -178,
        "P2 V5 %": 0.36,
        "P2 Fair": 178,
        "Expected Margin": 3.25,
        "Expected Total": 22.4,
        "Model Gap": 0.035,
        "Agreement": "LOW",
        "P1 Form": 0.041,
        "P1 Form Percentile": 82.0,
        "P2 Form": -0.018,
        "P2 Form Percentile": 34.0,
        "P1 Volatility": 0.052,
        "P1 Volatility Percentile": 41.0,
        "P1 Volatility Label": "Average",
        "P2 Volatility": 0.081,
        "P2 Volatility Percentile": 76.0,
        "P2 Volatility Label": "High",
        "P1 State Conf": 0.91,
        "P2 State Conf": 0.84,
        "P1 State Conf Label": "High",
        "P2 State Conf Label": "Good",
        "Surface Elo P1 %": 0.605,
        "P1 ML": -115,
        "P1 ML EV": 0.196,
        "P1 ML Signal": "BET",
        "P2 ML": 105,
        "P2 ML EV": -0.262,
        "P2 ML Signal": "PASS",
    })


def test_today_card_contains_matchup_lab_projection_and_state_output():
    html = match_card_html(_row())
    for text in (
        "64.0%", "-178", "+3.25", "22.40",
        "Recent form", "82nd", "Match-day volatility", "State confidence",
        "Simulator vs Surface Elo", "3.5%", "BET", "+19.6%",
    ):
        assert text in html


def test_daily_batch_carries_matchup_lab_state_fields():
    source = Path("tennis_quant_app_v5.py").read_text(encoding="utf-8")
    for field in (
        '"P1 Form"', '"P2 Form"', '"P1 Form Percentile"', '"P2 Form Percentile"',
        '"P1 Volatility"', '"P2 Volatility"', '"P1 Volatility Label"', '"P2 Volatility Label"',
        '"P1 State Conf Label"', '"P2 State Conf Label"', '"Surface Elo P1 %"',
    ):
        assert field in source


def test_today_advanced_section_retains_requested_operational_features():
    source = Path("v5_ui_host.py").read_text(encoding="utf-8")
    for text in (
        "Slate setup / advanced",
        "Simulation precision",
        "Current market slate",
        "Surface inference",
        "could not be matched to the V5 ratings database",
        "Tour", "Surface", "Best Of",
    ):
        assert text in source
