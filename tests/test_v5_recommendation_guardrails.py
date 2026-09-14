import pandas as pd

from v5_recommendation_ledger import update_official_recommendations


def test_actionable_recommendation_without_start_time_fails_closed():
    observation = pd.DataFrame([{
        "fixture_id": "fx-missing-start",
        "market_group": "moneyline",
        "selection": "Player One",
        "market_key": "fx-missing-start|moneyline|player one|",
        "signal": "BET",
        "best_american_odds": 120,
        "best_decimal_odds": 2.2,
        "model_probability": .60,
        "expected_value": .32,
        "snapshot_utc": "2026-09-14T15:00:00Z",
        "start_time_utc": None,
    }])

    ledger, audit = update_official_recommendations(pd.DataFrame(), observation)

    assert ledger.empty
    assert (audit["event"] == "BLOCKED_MISSING_START").any()
