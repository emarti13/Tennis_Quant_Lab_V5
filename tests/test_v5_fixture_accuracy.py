import pandas as pd
import pytest

from v5_fixture_accuracy import fixture_accuracy_records, fixture_accuracy_metrics


def _settled_fixture(*, p1_prob=.575, winner="Player One", winner_games=13, loser_games=9):
    base = {
        "fixture_id": "fx1",
        "resolved_player1": "Player One",
        "resolved_player2": "Player Two",
        "full_context_probability_p1": p1_prob,
        "expected_margin": .54,
        "expected_total": 22.5,
        "result_status": "SETTLED",
        "result_winner": winner,
        "result_loser": "Player Two" if winner == "Player One" else "Player One",
        "result_score": "6-4 7-5",
        "winner_games": winner_games,
        "loser_games": loser_games,
        "model_version": "v5-model-1",
        "selected_model_candidate": "ensemble",
        "selected_score_candidate": "conditioned_mechanistic",
    }
    rows = []
    for market_key in ("fx1|moneyline|player one|", "fx1|game_spread|player two|3.5", "fx1|total_games|over|22.5"):
        rows.append({**base, "market_key": market_key})
    return pd.DataFrame(rows)


def test_fixture_accuracy_collapses_many_market_rows_to_one_forecast_observation():
    records = fixture_accuracy_records(_settled_fixture())

    assert len(records) == 1
    row = records.iloc[0]
    assert row["fixture_id"] == "fx1"
    assert bool(row["winner_correct"]) is True
    assert row["brier_score"] == pytest.approx((.575 - 1.0) ** 2)
    assert row["actual_margin"] == pytest.approx(4.0)
    assert row["margin_error"] == pytest.approx(3.46)
    assert row["abs_margin_error"] == pytest.approx(3.46)
    assert row["actual_total"] == pytest.approx(22.0)
    assert row["total_error"] == pytest.approx(-.5)
    assert row["abs_total_error"] == pytest.approx(.5)


def test_fixture_accuracy_uses_negative_margin_from_player1_perspective_when_player2_wins():
    records = fixture_accuracy_records(
        _settled_fixture(p1_prob=.40, winner="Player Two", winner_games=14, loser_games=10)
    )
    row = records.iloc[0]

    assert bool(row["winner_correct"]) is True
    assert row["actual_p1_win"] == 0
    assert row["actual_margin"] == pytest.approx(-4.0)
    assert row["brier_score"] == pytest.approx(.40 ** 2)


def test_fixture_accuracy_metrics_use_fixture_count_not_market_count():
    second = _settled_fixture(p1_prob=.40, winner="Player Two", winner_games=14, loser_games=10).copy()
    second["fixture_id"] = "fx2"
    second["market_key"] = second["market_key"].str.replace("fx1", "fx2", regex=False)
    frozen = pd.concat([_settled_fixture(), second], ignore_index=True)

    records = fixture_accuracy_records(frozen)
    metrics = fixture_accuracy_metrics(records)

    assert metrics["settled_fixtures"] == 2
    assert metrics["winner_accuracy"] == pytest.approx(1.0)
    assert metrics["brier_score"] == pytest.approx((((.575 - 1.0) ** 2) + (.40 ** 2)) / 2)
    assert metrics["margin_mae"] == pytest.approx((3.46 + 4.54) / 2)
    assert metrics["total_mae"] == pytest.approx((.5 + 1.5) / 2)
