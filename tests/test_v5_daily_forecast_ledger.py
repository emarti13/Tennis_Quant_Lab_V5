import pandas as pd

from v5_daily_forecast import forecast_rows_from_board


def _board():
    common = {
        "fixture_id": "fx1",
        "start_time_utc": "2026-09-08T18:00:00Z",
        "tournament": "Test Open",
        "tour_v5": "MEN",
        "surface": "Hard",
        "best_of": 3,
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
        "margin_sd": 4.5,
        "total_sd": 5.8,
        "spread_probability_p1_json": '{"-2.5": 0.59}',
        "spread_push_probability_json": '{"-2.5": 0.0}',
        "over_probability_json": '{"21.5": 0.57}',
        "total_push_probability_json": '{"21.5": 0.0}',
        "context_quality_a": 0.9,
        "context_quality_b": 0.8,
        "weather_source_quality": "cached",
        "court_speed_source_quality": "registry",
        "frozen_at_utc": "2026-09-08T12:30:00Z",
    }
    return pd.DataFrame([
        {**common, "market_group": "moneyline", "selection": "Player One", "best_american_odds": -130, "expected_value": 0.08, "signal": "BET"},
        {**common, "market_group": "game_spread", "selection": "Player One", "line": -2.5, "best_american_odds": 105, "expected_value": 0.04, "signal": "LEAN"},
    ])


def test_forecast_rows_are_one_per_fixture_and_exclude_market_dependent_fields():
    out = forecast_rows_from_board(_board(), forecast_date="2026-09-08")
    assert len(out) == 1
    row = out.iloc[0]
    assert row["fixture_id"] == "fx1"
    assert row["forecast_date"] == "2026-09-08"
    assert row["full_context_probability_p1"] == 0.67
    assert row["selected_model_candidate"] == "ensemble"
    assert row["spread_probability_p1_json"] == '{"-2.5": 0.59}'
    for forbidden in ["market_group", "selection", "line", "best_american_odds", "expected_value", "signal"]:
        assert forbidden not in out.columns


def test_forecast_rows_are_idempotent_when_market_rows_repeat():
    board = pd.concat([_board(), _board()], ignore_index=True)
    out = forecast_rows_from_board(board, forecast_date="2026-09-08")
    assert len(out) == 1
