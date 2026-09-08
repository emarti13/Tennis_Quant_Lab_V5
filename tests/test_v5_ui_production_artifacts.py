import json

import pandas as pd

from v5_ui_production import load_canonical_today_board, production_ui_state


def _repriced():
    return pd.DataFrame([{
        "snapshot_utc": "2026-09-08T12:15:00Z",
        "fixture_id": "fx1",
        "start_time_utc": "2026-09-08T18:00:00Z",
        "tournament": "Test Open",
        "tour": "ATP",
        "tour_v5": "MEN",
        "player1": "Player One",
        "player2": "Player Two",
        "resolved_player1": "Player One",
        "resolved_player2": "Player Two",
        "surface": "Hard",
        "surface_source": "Auto — tournament map",
        "best_of": 3,
        "market_group": "moneyline",
        "selection": "Player One",
        "line": None,
        "best_american_odds": 100,
        "best_decimal_odds": 2.0,
        "model_probability": 0.60,
        "expected_value": 0.20,
        "signal": "BET",
        "full_context_probability_p1": 0.60,
        "elo_probability_p1": 0.57,
        "expected_margin": 2.4,
        "expected_total": 22.1,
        "model_gap": 0.03,
        "model_disagreement": "LOW",
        "selected_model_candidate": "ensemble",
        "selected_score_candidate": "conditioned_mechanistic",
        "ctx_serve_dominance_diff": 0.12,
        "ctx_rest_log1p_diff": 0.20,
        "ctx_travel_km_diff": -300.0,
        "ctx_court_speed_x_serve_dominance_diff": 0.05,
        "ctx_state_uncertainty_diff": -0.03,
        "state_confidence_p1": 0.9,
        "state_confidence_p2": 0.8,
    }])


def test_canonical_today_board_loads_without_interactive_run(tmp_path):
    ready = tmp_path / "v5_daily_ready"
    ready.mkdir()
    _repriced().to_csv(ready / "latest_repriced_board.csv", index=False)
    (ready / "repricing_status.json").write_text(json.dumps({"state": "success", "freshness": "READY"}))

    board = load_canonical_today_board(tmp_path)
    assert len(board) == 1
    row = board.iloc[0]
    assert row["Fixture ID"] == "fx1"
    assert row["P1 V5 %"] == 0.60
    assert row["P1 ML Signal"] == "BET"
    assert row["Matchup Context"] != "Unavailable"
    assert row["Workload Context"] != "Unavailable"
    assert row["Travel Context"] != "Unavailable"


def test_production_ui_state_distinguishes_ready_stale_missing_and_no_future():
    assert production_ui_state({"state": "success", "freshness": "READY"}) == "READY"
    assert production_ui_state({"state": "blocked", "freshness": "STALE_PRICES"}) == "STALE_PRICES"
    assert production_ui_state({"state": "blocked", "freshness": "NO_FUTURE_FIXTURES"}) == "NO_FUTURE_FIXTURES"
    assert production_ui_state({}) == "MISSING"
