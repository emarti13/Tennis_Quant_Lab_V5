import pandas as pd

from v5_official_performance import official_performance_report
from v5_settlement import settle_ledger


def _ledger():
    return pd.DataFrame([{
        "fixture_id": "fx1",
        "tournament": "US Open Men Singles",
        "player1": "Player One",
        "player2": "Player Two",
        "resolved_player1": "Player One",
        "resolved_player2": "Player Two",
        "start_time_utc": "2026-09-08T18:00:00Z",
        "market_group": "moneyline",
        "selection": "Player One",
        "line": None,
        "market_key": "fx1|moneyline|player one|",
        "official_signal": "BET",
        "signal": "BET",
        "official_price_american": 120,
        "official_price_decimal": 2.2,
        "best_american_odds": 120,
        "best_decimal_odds": 2.2,
        "official_model_probability": 0.60,
        "model_probability": 0.60,
        "official_at_utc": "2026-09-08T12:00:00Z",
        "model_version": "v5-model-1",
        "result_status": "OPEN",
        "settled_result": "",
        "profit_units": None,
    }])


def _results():
    return pd.DataFrame([{
        "winner_name": "Player One",
        "loser_name": "Player Two",
        "tourney_date": 20260907,
        "tourney_name": "US Open",
        "score": "6-4 6-4",
    }])


def test_official_market_settles_once_and_performance_counts_one_recommendation():
    settled, stats = settle_ledger(_ledger(), _results(), settled_at="2026-09-08T20:00:00Z")
    assert stats["settled"] == 1
    assert settled.iloc[0]["settled_result"] == "WIN"
    assert settled.iloc[0]["profit_units"] == 1.2

    report = official_performance_report(settled)
    assert report["official_recommendations"] == 1
    assert report["unique_fixtures"] == 1
    assert report["wins"] == 1
    assert report["losses"] == 0
    assert report["net_units"] == 1.2
    assert report["median_american_odds"] == 120.0
    assert report["underdog_recommendations"] == 1
    assert report["favorite_recommendations"] == 0


def test_duplicate_market_keys_are_deduped_before_headline_performance():
    frame = pd.concat([_ledger(), _ledger()], ignore_index=True)
    frame["result_status"] = "SETTLED"
    frame["settled_result"] = "LOSS"
    frame["profit_units"] = -1.0
    report = official_performance_report(frame)
    assert report["official_recommendations"] == 1
    assert report["losses"] == 1
    assert report["net_units"] == -1.0
