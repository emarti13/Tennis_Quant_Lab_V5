from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


def test_parse_completed_score_counts_games_and_sets():
    from v5_score_walkforward import parse_completed_score

    out = parse_completed_score("6-4 7-6(5)")
    assert out["completed"] is True
    assert out["winner_games"] == 13
    assert out["loser_games"] == 10
    assert out["total_games"] == 23
    assert out["winner_margin"] == 3
    assert out["sets"] == 2


def test_parse_score_rejects_retirement_and_walkover():
    from v5_score_walkforward import parse_completed_score

    assert parse_completed_score("6-4 2-1 RET")["completed"] is False
    assert parse_completed_score("W/O")["completed"] is False


def test_gaussian_score_model_is_player_swap_symmetric():
    from v5_score_walkforward import fit_gaussian_score_model, predict_gaussian_score_model

    train = pd.DataFrame({
        "x_sr_a": [-0.4, -0.2, 0.2, 0.4, -0.1, 0.1],
        "x_elo_a": [-0.5, -0.3, 0.3, 0.5, -0.2, 0.2],
        "ctx_rest_log1p_diff": [-0.2, -0.1, 0.1, 0.2, -0.05, 0.05],
        "actual_margin_a": [-7, -4, 4, 8, -2, 2],
        "actual_total": [20, 22, 22, 20, 24, 24],
    })
    features = ["x_sr_a", "x_elo_a", "ctx_rest_log1p_diff"]
    model = fit_gaussian_score_model(train, features=features, l2=2.0)
    a = pd.DataFrame([{"x_sr_a": .25, "x_elo_a": .35, "ctx_rest_log1p_diff": .10}])
    b = -a
    pa = predict_gaussian_score_model(model, a)
    pb = predict_gaussian_score_model(model, b)
    assert pa["margin_mean"][0] == pytest.approx(-pb["margin_mean"][0], abs=1e-8)
    assert pa["total_mean"][0] == pytest.approx(pb["total_mean"][0], abs=1e-8)


def test_score_metrics_reward_better_distribution():
    from v5_score_walkforward import distribution_metrics

    actual_margin = np.array([4.0, -3.0])
    actual_total = np.array([22.0, 24.0])
    good = {
        "margin_mean": np.array([3.5, -2.5]), "margin_sd": np.array([2.0, 2.0]),
        "total_mean": np.array([22.5, 23.5]), "total_sd": np.array([2.0, 2.0]),
    }
    bad = {
        "margin_mean": np.array([-5.0, 5.0]), "margin_sd": np.array([2.0, 2.0]),
        "total_mean": np.array([30.0, 15.0]), "total_sd": np.array([2.0, 2.0]),
    }
    mg = distribution_metrics(actual_margin, actual_total, good)
    mb = distribution_metrics(actual_margin, actual_total, bad)
    assert mg["margin_crps"] < mb["margin_crps"]
    assert mg["total_crps"] < mb["total_crps"]
    assert mg["margin_rmse"] < mb["margin_rmse"]
    assert mg["total_rmse"] < mb["total_rmse"]


def test_score_candidate_gate_requires_distribution_improvement_without_material_bias_regression():
    from v5_score_walkforward import score_candidate_gate

    baseline = {"margin_crps": 2.0, "total_crps": 2.2, "margin_rmse": 5.0, "total_rmse": 4.5, "margin_bias": .2, "total_bias": .3}
    better = {"margin_crps": 1.9, "total_crps": 2.1, "margin_rmse": 4.9, "total_rmse": 4.4, "margin_bias": .25, "total_bias": .2}
    worse = {"margin_crps": 2.1, "total_crps": 2.0, "margin_rmse": 5.1, "total_rmse": 4.3, "margin_bias": .2, "total_bias": .3}
    assert score_candidate_gate(baseline, better)["accepted"] is True
    assert score_candidate_gate(baseline, worse)["accepted"] is False
