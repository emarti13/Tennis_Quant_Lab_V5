import pandas as pd

from v5_recommendation_policy import select_primary_market_rows


def test_primary_policy_returns_highest_ev_bet_once_per_fixture():
    rows = pd.DataFrame([
        {"fixture_id": "fx1", "market_key": "fx1|ml|a|", "signal": "BET", "expected_value": .20},
        {"fixture_id": "fx1", "market_key": "fx1|spread|b|3.5", "signal": "BET", "expected_value": .45},
        {"fixture_id": "fx1", "market_key": "fx1|total|over|22.5", "signal": "LEAN", "expected_value": .60},
        {"fixture_id": "fx2", "market_key": "fx2|ml|c|", "signal": "LEAN", "expected_value": .11},
    ])

    chosen = select_primary_market_rows(rows)

    assert list(chosen["market_key"]) == ["fx1|spread|b|3.5", "fx2|ml|c|"]


def test_primary_policy_uses_source_order_as_stable_tie_break():
    rows = pd.DataFrame([
        {"fixture_id": "fx1", "market_key": "first", "signal": "BET", "expected_value": .25},
        {"fixture_id": "fx1", "market_key": "second", "signal": "BET", "expected_value": .25},
    ])

    chosen = select_primary_market_rows(rows)

    assert chosen.iloc[0]["market_key"] == "first"
