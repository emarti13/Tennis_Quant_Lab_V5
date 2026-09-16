import pandas as pd
import pytest

from v5_signal_tracking import tracking_tables


def test_tracking_tables_split_market_tour_and_signal_with_five_stats():
    df = pd.DataFrame([
        {"market_group":"moneyline","tour":"ATP","tournament":"ATP Rome","signal":"BET","result_status":"SETTLED","settled_result":"WIN","profit_units":1.0},
        {"market_group":"moneyline","tour":"ATP","tournament":"ATP Rome","signal":"BET","result_status":"SETTLED","settled_result":"LOSS","profit_units":-1.0},
        {"market_group":"moneyline","tour":"WTA","tournament":"WTA Rome","signal":"LEAN","result_status":"SETTLED","settled_result":"WIN","profit_units":0.8},
        {"market_group":"moneyline","tour":"Challenger","tournament":"ATP Challenger Como","signal":"REVIEW","result_status":"SETTLED","settled_result":"WIN","profit_units":1.2},
        {"market_group":"game_spread","tour":"ATP","tournament":"ATP Rome","signal":"PASS","result_status":"SETTLED","settled_result":"LOSS","profit_units":-1.0},
        {"market_group":"total_games","tour":"WTA","tournament":"WTA Rome","signal":"BET","result_status":"SETTLED","settled_result":"PUSH","profit_units":0.0},
    ])
    tables = tracking_tables(df)
    assert set(tables) == {"Moneyline", "Spread", "Totals"}
    ml = tables["Moneyline"]
    assert list(ml.index) == ["ATP", "WTA", "Challenger", "All"]
    assert ml.loc["ATP", ("BET", "Win Rate")] == pytest.approx(.5)
    assert ml.loc["ATP", ("BET", "W-L")] == "1-1"
    assert ml.loc["ATP", ("BET", "N")] == 2
    assert ml.loc["ATP", ("BET", "Units")] == pytest.approx(0.0)
    assert ml.loc["ATP", ("BET", "ROI")] == pytest.approx(0.0)
    assert ml.loc["Challenger", ("REVIEW", "W-L")] == "1-0"
    assert ml.loc["All", ("Overall", "N")] == 4
    assert tables["Spread"].loc["ATP", ("PASS", "W-L")] == "0-1"
    assert tables["Totals"].loc["WTA", ("BET", "N")] == 0


def test_challenger_is_not_swallowed_into_atp():
    df = pd.DataFrame([{"market_group":"moneyline","tour_v5":"MEN","tournament":"ATP Challenger Manacor","signal":"BET","result_status":"SETTLED","settled_result":"WIN","profit_units":1.0}])
    ml = tracking_tables(df)["Moneyline"]
    assert ml.loc["Challenger", ("BET", "N")] == 1
    assert ml.loc["ATP", ("BET", "N")] == 0
