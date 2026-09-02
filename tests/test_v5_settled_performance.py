from __future__ import annotations

import pandas as pd
import pytest


def _sample():
    return pd.DataFrame([
        {"freeze_key":"a1","fixture_id":"A","market_group":"total_games","selection":"OVER","line":20.5,"signal":"BET","settled_result":"WIN","profit_units":0.90,"model_probability":0.61,"consensus_no_vig_prob":0.52,"tour_v5":"MEN","best_of":3},
        {"freeze_key":"a2","fixture_id":"A","market_group":"total_games","selection":"OVER","line":21.5,"signal":"BET","settled_result":"WIN","profit_units":0.90,"model_probability":0.59,"consensus_no_vig_prob":0.50,"tour_v5":"MEN","best_of":3},
        {"freeze_key":"a3","fixture_id":"A","market_group":"total_games","selection":"OVER","line":22.5,"signal":"BET","settled_result":"WIN","profit_units":0.90,"model_probability":0.56,"consensus_no_vig_prob":0.48,"tour_v5":"MEN","best_of":3},
        {"freeze_key":"b1","fixture_id":"B","market_group":"moneyline","selection":"P1","line":None,"signal":"BET","settled_result":"LOSS","profit_units":-1.0,"model_probability":0.72,"consensus_no_vig_prob":0.65,"tour_v5":"MEN","best_of":3},
        {"freeze_key":"c1","fixture_id":"C","market_group":"moneyline","selection":"P2","line":None,"signal":"BET","settled_result":"LOSS","profit_units":-1.0,"model_probability":0.40,"consensus_no_vig_prob":0.35,"tour_v5":"WTA","best_of":3},
        # duplicate ledger row must not change performance
        {"freeze_key":"c1","fixture_id":"C","market_group":"moneyline","selection":"P2","line":None,"signal":"BET","settled_result":"LOSS","profit_units":-1.0,"model_probability":0.40,"consensus_no_vig_prob":0.35,"tour_v5":"WTA","best_of":3},
    ])


def test_raw_and_fixture_cluster_metrics_are_kept_separate():
    from diagnose_v5_settled_performance import settled_performance_report

    report = settled_performance_report(_sample())
    raw = report["raw_markets"]
    fixtures = report["fixture_clusters"]

    assert raw["bets"] == 5
    assert raw["wins"] == 3
    assert raw["losses"] == 2
    assert raw["win_rate"] == pytest.approx(0.60)

    assert fixtures["fixtures"] == 3
    assert fixtures["profitable_fixtures"] == 1
    assert fixtures["losing_fixtures"] == 2
    assert fixtures["profitable_fixture_rate"] == pytest.approx(1 / 3)
    assert fixtures["max_markets_on_one_fixture"] == 3


def test_moneyline_calibration_uses_one_settled_market_row_per_freeze_key():
    from diagnose_v5_settled_performance import settled_performance_report

    report = settled_performance_report(_sample())
    ml = report["moneyline_calibration"]
    assert ml["n"] == 2
    assert ml["observed_win_rate"] == 0.0
    assert ml["mean_model_probability"] == pytest.approx(0.56)
    assert ml["brier"] > 0
    assert ml["log_loss"] > 0


def test_report_breaks_out_market_signal_tour_and_format():
    from diagnose_v5_settled_performance import settled_performance_report

    report = settled_performance_report(_sample())
    assert report["by_market_group"]["total_games"]["bets"] == 3
    assert report["by_market_group"]["moneyline"]["bets"] == 2
    assert report["by_signal"]["BET"]["bets"] == 5
    assert report["by_tour"]["MEN"]["bets"] == 4
    assert report["by_tour"]["WTA"]["bets"] == 1
    assert report["by_best_of"]["3"]["bets"] == 5
