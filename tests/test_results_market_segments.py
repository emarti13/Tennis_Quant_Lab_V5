import pandas as pd
from v5_results_segments import recommendation_accuracy_tables


def _row(market, tour, signal, result, units, odds=None):
    return {"market_group": market, "tour_v5": tour, "signal": signal, "result_status": "SETTLED", "settled_result": result, "profit_units": units, "best_american_odds": odds}


def test_tables_split_market_tour_and_signal_with_units_roi():
    df = pd.DataFrame([
        _row("moneyline", "ATP", "BET", "WIN", 0.9, 90),
        _row("moneyline", "ATP", "BET", "LOSS", -1.0, -110),
        _row("game_spread", "WTA", "REVIEW", "WIN", 0.8, -125),
        _row("total_games", "CHALLENGER", "PASS", "LOSS", -1.0, -110),
    ])
    tables = recommendation_accuracy_tables(df)
    assert set(tables) == {"Moneyline", "Spread", "Totals"}
    ml = tables["Moneyline"]
    assert "ATP" in ml.index and "All" in ml.index
    assert "BET" in ml.columns and "Overall" in ml.columns
    assert "50.0%" in ml.loc["ATP", "BET"]
    assert "1-1" in ml.loc["ATP", "BET"]
    assert "N=2" in ml.loc["ATP", "BET"]
    assert "-0.10u" in ml.loc["ATP", "BET"]
    assert "-5.0% ROI" in ml.loc["ATP", "BET"]
    assert "100.0%" in tables["Spread"].loc["WTA", "REVIEW"]
    assert "CHALLENGER" in tables["Totals"].index


def test_push_is_counted_in_sample_but_excluded_from_win_rate_and_units_zero():
    df = pd.DataFrame([
        _row("moneyline", "ATP", "LEAN", "WIN", 1.0, 100),
        _row("moneyline", "ATP", "LEAN", "PUSH", 0.0, -110),
    ])
    cell = recommendation_accuracy_tables(df)["Moneyline"].loc["ATP", "LEAN"]
    assert "100.0%" in cell
    assert "1-0" in cell
    assert "N=2" in cell
    assert "+1.00u" in cell
