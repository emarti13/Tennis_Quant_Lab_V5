import pandas as pd

from v5_daily_forecast import forecast_rows_from_board, market_probability_rows_from_board


def _board():
    common = {
        "fixture_id": "fx1",
        "start_time_utc": "2026-09-08T18:00:00Z",
        "tournament": "Test Open",
        "tour_v5": "MEN",
        "surface": "Hard",
        "surface_source": "Auto — tournament map",
        "best_of": 3,
        "player1": "Player One",
        "player2": "Player Two",
        "resolved_player1": "Player One",
        "resolved_player2": "Player Two",
        "model_version": "v5-model-1",
        "selected_model_candidate": "ensemble",
        "score_model_version": "v5-score-1",
        "selected_score_candidate": "conditioned_mechanistic",
        "full_context_probability_p1": 0.67,
        "accepted_baseline_probability_p1": 0.61,
        "elo_probability_p1": 0.64,
        "serve_probability_p1": 0.63,
        "serve_probability_p2": 0.60,
        "expected_margin": 3.2,
        "expected_total": 22.4,
        "context_quality_a": 0.9,
        "context_quality_b": 0.8,
        "ctx_serve_dominance_diff": 0.12,
        "ctx_rest_log1p_diff": 0.20,
        "ctx_travel_km_diff": -300.0,
        "state_confidence_p1": 0.9,
        "state_confidence_p2": 0.8,
        "weather_source_quality": "cached",
        "court_speed_source_quality": "registry",
        "frozen_at_utc": "2026-09-08T12:30:00Z",
    }
    return pd.DataFrame([
        {**common, "market_group": "moneyline", "selection": "Player One", "model_probability": 0.67, "model_win_probability": 0.67, "model_push_probability": 0.0, "model_loss_probability": 0.33, "model_fair_american": -203, "state_confidence": 0.9, "best_american_odds": -130, "consensus_no_vig_prob": 0.56, "expected_value": 0.08, "edge_vs_consensus": 0.11, "signal": "BET"},
        {**common, "market_group": "game_spread", "selection": "Player One", "line": -2.5, "model_probability": 0.59, "model_win_probability": 0.59, "model_push_probability": 0.0, "model_loss_probability": 0.41, "model_fair_american": -144, "state_confidence": 0.9, "best_american_odds": 105, "consensus_no_vig_prob": 0.49, "expected_value": 0.04, "edge_vs_consensus": 0.10, "signal": "LEAN"},
    ])


def test_forecast_rows_are_one_per_fixture_and_exclude_market_dependent_fields():
    out = forecast_rows_from_board(_board(), forecast_date="2026-09-08")
    assert len(out) == 1
    row = out.iloc[0]
    assert row["fixture_id"] == "fx1"
    assert row["forecast_date"] == "2026-09-08"
    assert row["full_context_probability_p1"] == 0.67
    assert row["selected_model_candidate"] == "ensemble"
    assert row["ctx_serve_dominance_diff"] == 0.12
    for forbidden in ["market_group", "selection", "line", "best_american_odds", "consensus_no_vig_prob", "expected_value", "signal"]:
        assert forbidden not in out.columns


def test_market_probability_rows_preserve_model_and_context_but_strip_sportsbook_inputs():
    out = market_probability_rows_from_board(_board(), forecast_date="2026-09-08")
    assert len(out) == 2
    ml = out[out["market_group"].eq("moneyline")].iloc[0]
    assert ml["model_probability"] == 0.67
    assert ml["ctx_rest_log1p_diff"] == 0.20
    assert ml["state_confidence_p1"] == 0.9
    assert ml["market_key"] == "fx1|moneyline|player one|"
    for forbidden in ["best_american_odds", "consensus_no_vig_prob", "expected_value", "edge_vs_consensus", "signal"]:
        assert forbidden not in out.columns


def test_forecast_rows_are_idempotent_when_market_rows_repeat():
    board = pd.concat([_board(), _board()], ignore_index=True)
    out = forecast_rows_from_board(board, forecast_date="2026-09-08")
    assert len(out) == 1
