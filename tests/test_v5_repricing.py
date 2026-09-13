import pandas as pd

from v5_reprice_markets import reprice_market_snapshot


def _forecast_prob():
    return pd.DataFrame([{
        "fixture_id": "fx1",
        "forecast_date": "2026-09-08",
        "market_group": "moneyline",
        "selection": "Player One",
        "line": None,
        "market_key": "fx1|moneyline|player one|",
        "model_probability": 0.60,
        "model_win_probability": 0.60,
        "model_push_probability": 0.0,
        "model_loss_probability": 0.40,
        "model_fair_american": -150.0,
        "state_confidence": 0.9,
        "surface_source": "Auto — tournament map",
        "model_version": "v5-model-1",
        "selected_model_candidate": "ensemble",
        "score_model_version": "v5-score-1",
        "selected_score_candidate": "conditioned_mechanistic",
    }])


def _price(american, decimal, consensus, snapshot):
    return pd.DataFrame([{
        "snapshot_utc": snapshot,
        "fixture_id": "fx1",
        "start_time_utc": "2026-09-08T18:00:00Z",
        "tournament": "Test Open",
        "tour": "ATP",
        "player1": "Player One",
        "player2": "Player Two",
        "market_group": "moneyline",
        "selection": "Player One",
        "line": None,
        "best_bookmaker": "pinnacle",
        "best_decimal_odds": decimal,
        "best_american_odds": american,
        "consensus_no_vig_prob": consensus,
    }])


def test_same_daily_model_probability_is_immutable_across_price_refreshes():
    first = reprice_market_snapshot(_price(100, 2.0, 0.49, "2026-09-08T12:00:00Z"), _forecast_prob(), prices_fresh=True)
    second = reprice_market_snapshot(_price(-180, 1.556, 0.62, "2026-09-08T14:00:00Z"), _forecast_prob(), prices_fresh=True)

    assert first.iloc[0]["model_probability"] == second.iloc[0]["model_probability"] == 0.60
    assert first.iloc[0]["model_version"] == second.iloc[0]["model_version"] == "v5-model-1"
    assert first.iloc[0]["expected_value"] != second.iloc[0]["expected_value"]
    assert first.iloc[0]["signal"] != second.iloc[0]["signal"]


def test_stale_prices_can_never_emit_bet_or_lean():
    out = reprice_market_snapshot(_price(150, 2.5, 0.40, "2026-09-08T12:00:00Z"), _forecast_prob(), prices_fresh=False)
    assert out.iloc[0]["model_probability"] == 0.60
    assert out.iloc[0]["signal"] == "STALE"
    assert not out["signal"].isin(["BET", "LEAN"]).any()


def test_unmodeled_new_market_line_is_not_guessed():
    price = _price(100, 2.0, 0.49, "2026-09-08T12:00:00Z")
    price["market_group"] = "game_spread"
    price["line"] = -7.5
    out = reprice_market_snapshot(price, _forecast_prob(), prices_fresh=True)
    assert pd.isna(out.iloc[0]["model_probability"])
    assert out.iloc[0]["signal"] == "N/A"
