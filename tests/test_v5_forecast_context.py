import pandas as pd

from v5_forecast_context import enrich_daily_board_context


def test_empty_board_is_safe_and_does_not_invent_context():
    out, errors = enrich_daily_board_context(
        pd.DataFrame(), pd.DataFrame(), {}, {}, pd.DataFrame()
    )
    assert out.empty
    assert errors == []


def test_missing_market_fixture_is_reported_not_guessed():
    board = pd.DataFrame([{"fixture_id": "fx1", "model_probability": 0.6}])
    out, errors = enrich_daily_board_context(
        board, pd.DataFrame(columns=["fixture_id"]), {}, {}, pd.DataFrame()
    )
    assert len(out) == 1
    assert errors == [{"fixture_id": "fx1", "stage": "context_display", "error": "market fixture missing"}]
