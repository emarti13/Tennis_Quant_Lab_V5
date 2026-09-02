import pandas as pd

from v5_daily_policy_postprocess import apply_daily_policy


def test_daily_policy_suppresses_disabled_score_signals_and_preserves_moneyline():
    board = pd.DataFrame([
        {"market_group":"game_spread","tour_v5":"MEN","best_of":5,"signal":"BET"},
        {"market_group":"total_games","tour_v5":"MEN","best_of":5,"signal":"LEAN"},
        {"market_group":"moneyline","tour_v5":"MEN","best_of":5,"signal":"BET"},
    ])
    config = {"score_markets":{"MEN_BO5":{"enabled":False}}}
    out = apply_daily_policy(board, config)
    assert list(out["signal"]) == ["REVIEW", "REVIEW", "BET"]
    assert list(out["production_market_enabled"]) == [False, False, True]
