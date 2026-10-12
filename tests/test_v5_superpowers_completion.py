from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


def test_score_distribution_keeps_independent_winner_target():
    from v5_score_distribution import predict_score_distribution

    result = predict_score_distribution(
        {
            "serve_probability_p1": 0.64,
            "serve_probability_p2": 0.61,
            "winner_probability_p1": 0.68,
            "best_of": 3,
            "spread_lines": [-2.5, 2.5],
            "total_lines": [21.5, 22.5],
        },
        {"model_type": "conditioned_mechanistic", "simulations": 2500, "seed": 7},
    )
    assert result.model_type == "conditioned_mechanistic"
    assert result.match_win_probability_p1 == pytest.approx(0.68, abs=1e-12)
    assert np.isfinite(result.expected_margin)
    assert np.isfinite(result.expected_total)
    assert "+2.5" in result.spread_probability_p1
    assert "21.5" in result.over_probability
    assert 0.0 <= result.tiebreak_probability <= 1.0


def test_experiment_runner_persists_acceptance_and_rejection(tmp_path):
    from v5_experiments import ExperimentConfig, run_experiment

    good = ExperimentConfig(
        experiment_id="good",
        git_sha="abc123",
        feature_set_version="ctx-v1",
        model_version="candidate-v1",
        training_window="2025-01-01/2025-09-30",
        validation_window="2026-01-01/2026-08-31",
        baseline_metrics={"brier": 0.23, "log_loss": 0.65, "accuracy": 0.64},
        candidate_metrics={"brier": 0.22, "log_loss": 0.63, "accuracy": 0.64},
    )
    result = run_experiment(good, registry_dir=tmp_path)
    assert result.promoted is True
    saved = json.loads((tmp_path / "good.json").read_text())
    assert saved["promotion_decision"] == "promote"

    bad = ExperimentConfig(
        experiment_id="bad",
        git_sha="abc123",
        feature_set_version="ctx-v1",
        model_version="candidate-v2",
        training_window="2025",
        validation_window="2026",
        baseline_metrics={"brier": 0.23, "log_loss": 0.65, "accuracy": 0.64},
        candidate_metrics={"brier": 0.24, "log_loss": 0.66, "accuracy": 0.65},
    )
    result_bad = run_experiment(bad, registry_dir=tmp_path)
    assert result_bad.promoted is False
    assert (tmp_path / "bad.json").exists()


def test_market_evaluation_is_post_prediction_only_and_never_mutates_model_probability():
    from v5_market_evaluation import evaluate_market_edges

    frozen = pd.DataFrame(
        {
            "freeze_key": ["f1|moneyline|a|"],
            "fixture_id": ["f1"],
            "market_group": ["moneyline"],
            "selection": ["A"],
            "line": [np.nan],
            "frozen_at_utc": ["2026-09-01T12:00:00Z"],
            "model_probability": [0.60],
            "settled_result": ["WIN"],
            "profit_units": [0.80],
        }
    )
    odds = pd.DataFrame(
        {
            "fixture_id": ["f1"],
            "market_group": ["moneyline"],
            "selection": ["A"],
            "line": [np.nan],
            "snapshot_utc": ["2026-09-01T12:05:00Z"],
            "consensus_no_vig_prob": [0.55],
            "best_decimal_odds": [1.80],
        }
    )
    original = frozen["model_probability"].copy()
    report = evaluate_market_edges(frozen, odds)
    assert frozen["model_probability"].equals(original)
    assert report["joined_rows"] == 1
    assert report["edge_mean"] == pytest.approx(0.05)
    assert report["roi"] == pytest.approx(0.80)


def test_market_evaluation_rejects_pre_freeze_odds():
    from v5_market_evaluation import evaluate_market_edges

    frozen = pd.DataFrame(
        {
            "fixture_id": ["f1"], "market_group": ["moneyline"], "selection": ["A"], "line": [np.nan],
            "frozen_at_utc": ["2026-09-01T12:00:00Z"], "model_probability": [0.60],
        }
    )
    odds = pd.DataFrame(
        {
            "fixture_id": ["f1"], "market_group": ["moneyline"], "selection": ["A"], "line": [np.nan],
            "snapshot_utc": ["2026-09-01T11:55:00Z"], "consensus_no_vig_prob": [0.55], "best_decimal_odds": [1.80],
        }
    )
    report = evaluate_market_edges(frozen, odds)
    assert report["joined_rows"] == 0
    assert report["rejected_pre_freeze_odds"] == 1


def test_live_candidate_applies_only_selected_validated_architecture(tmp_path):
    from v5_full_context_live import load_production_candidate, predict_with_production_candidate

    candidate = {
        "version": "v5-advanced-test",
        "MEN": {
            "selected_candidate": "accepted_baseline",
            "direct_context_model": {},
            "residual_model": {},
            "uncertainty_model": {"gamma": 0.0},
            "stack_model": {"weights": {"accepted_baseline": 1.0}},
        },
        "WTA": {
            "selected_candidate": "accepted_baseline",
            "direct_context_model": {},
            "residual_model": {},
            "uncertainty_model": {"gamma": 0.0},
            "stack_model": {"weights": {"accepted_baseline": 1.0}},
        },
    }
    path = tmp_path / "candidate.json"
    path.write_text(json.dumps(candidate))
    loaded = load_production_candidate(path)
    out = predict_with_production_candidate(
        loaded,
        tour="MEN",
        baseline_probability=0.61,
        signed_features=pd.DataFrame([{"ctx_rest_log1p_diff": 0.2, "x_sr_a": 0.1, "x_elo_a": 0.2}]),
    )
    assert out["selected_candidate"] == "accepted_baseline"
    assert out["probability"] == pytest.approx(0.61)
    assert out["model_version"] == "v5-advanced-test"


def test_live_context_builder_uses_empty_target_rows_as_pre_match_state():
    from v5_full_context_live import build_live_matchup_features

    history = pd.DataFrame(
        [
            {
                "match_id": "old1", "tour": "MEN", "match_date": "2026-08-20", "tourney_id": "old", "tourney_name": "Old Event",
                "surface": "Hard", "best_of": 3, "player_name": "A", "opponent_name": "X", "player_role": "winner",
                "match_games": 20, "match_sets": 2, "match_duration_minutes": 90, "player_rank": 50,
                "stat_service_points": 60, "stat_first_serves_in": 36, "stat_first_serve_points_won": 26,
                "stat_second_serve_points_won": 12, "stat_aces": 5, "stat_double_faults": 2,
                "stat_break_points_saved": 4, "stat_break_points_faced": 5,
                "stat_return_points_total": 58, "stat_return_points_won": 22,
            },
            {
                "match_id": "old2", "tour": "MEN", "match_date": "2026-08-21", "tourney_id": "old", "tourney_name": "Old Event",
                "surface": "Hard", "best_of": 3, "player_name": "B", "opponent_name": "Y", "player_role": "loser",
                "match_games": 22, "match_sets": 2, "match_duration_minutes": 100, "player_rank": 70,
                "stat_service_points": 62, "stat_first_serves_in": 38, "stat_first_serve_points_won": 24,
                "stat_second_serve_points_won": 11, "stat_aces": 4, "stat_double_faults": 3,
                "stat_break_points_saved": 3, "stat_break_points_faced": 6,
                "stat_return_points_total": 61, "stat_return_points_won": 23,
            },
        ]
    )
    fixture = {
        "fixture_id": "future", "tour": "MEN", "start_time_utc": "2026-09-02T20:00:00Z", "tournament_id": "new",
        "tournament": "New Event", "surface": "Hard", "best_of": 3, "player1": "A", "player2": "B",
    }
    row = build_live_matchup_features(history, fixture, baseline_probability=0.57, x_sr_p1=0.08, x_elo_p1=0.12)
    assert row["player_a"] in {"A", "B"}
    assert "ctx_matches_7d_diff" in row
    assert "ctx_state_uncertainty_diff" in row
    assert np.isfinite(float(row["baseline_a_probability"]))
