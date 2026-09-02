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
        "x_sr_a": [-0.4, -0.2, 0.2, 0.4, -0.1, 0.1], "x_elo_a": [-0.5, -0.3, 0.3, 0.5, -0.2, 0.2],
        "ctx_rest_log1p_diff": [-0.2, -0.1, 0.1, 0.2, -0.05, 0.05], "actual_margin_a": [-7, -4, 4, 8, -2, 2],
        "actual_total": [20, 22, 22, 20, 24, 24],
    })
    features = ["x_sr_a", "x_elo_a", "ctx_rest_log1p_diff"]
    model = fit_gaussian_score_model(train, features=features, l2=2.0)
    a = pd.DataFrame([{"x_sr_a": .25, "x_elo_a": .35, "ctx_rest_log1p_diff": .10}]); b = -a
    pa = predict_gaussian_score_model(model, a); pb = predict_gaussian_score_model(model, b)
    assert pa["margin_mean"][0] == pytest.approx(-pb["margin_mean"][0], abs=1e-8)
    assert pa["total_mean"][0] == pytest.approx(pb["total_mean"][0], abs=1e-8)


def test_score_metrics_reward_better_distribution():
    from v5_score_walkforward import distribution_metrics
    actual_margin = np.array([4.0, -3.0]); actual_total = np.array([22.0, 24.0])
    good = {"margin_mean": np.array([3.5, -2.5]), "margin_sd": np.array([2.0, 2.0]), "total_mean": np.array([22.5, 23.5]), "total_sd": np.array([2.0, 2.0])}
    bad = {"margin_mean": np.array([-5.0, 5.0]), "margin_sd": np.array([2.0, 2.0]), "total_mean": np.array([30.0, 15.0]), "total_sd": np.array([2.0, 2.0])}
    mg = distribution_metrics(actual_margin, actual_total, good); mb = distribution_metrics(actual_margin, actual_total, bad)
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


def test_contextual_gaussian_score_bundle_prices_requested_lines_without_changing_winner_probability():
    from v5_score_walkforward import fit_gaussian_score_model
    from v5_score_distribution import predict_score_distribution
    train = pd.DataFrame({
        "x_sr_a": [-.5,-.3,-.1,.1,.3,.5], "x_elo_a": [-.6,-.4,-.2,.2,.4,.6],
        "actual_margin_a": [-8,-5,-2,2,5,8], "actual_total": [20,22,24,24,22,20],
    })
    model = fit_gaussian_score_model(train, features=["x_sr_a","x_elo_a"], l2=2.0)
    out = predict_score_distribution(
        {"serve_probability_p1": .64, "serve_probability_p2": .61, "winner_probability_p1": .67, "best_of": 3,
         "spread_lines": [-2.5, 2.5], "total_lines": [21.5, 22.5], "score_features": {"x_sr_a": .25, "x_elo_a": .35}},
        {"model_type": "gaussian_contextual", "model": model, "simulations": 1200, "seed": 3},
    )
    assert out.match_win_probability_p1 == pytest.approx(.67)
    assert out.model_type == "gaussian_contextual"
    assert 0 < out.spread_probability_p1["-2.5"] < 1
    assert 0 < out.over_probability["21.5"] < 1
    assert out.margin_sd > 0 and out.total_sd > 0


def test_score_holdout_cap_is_deterministic_and_spans_full_chronology():
    from diagnose_v5_score_distribution import _deterministic_cap

    frame = pd.DataFrame({"match_date": pd.date_range("2026-01-01", periods=101, freq="D"), "row_id": range(101)})
    a = _deterministic_cap(frame, 11)
    b = _deterministic_cap(frame.sample(frac=1.0, random_state=7), 11)

    assert a["row_id"].tolist() == b["row_id"].tolist()
    assert len(a) == 11
    assert a.iloc[0]["row_id"] == 0
    assert a.iloc[-1]["row_id"] == 100
    assert a["row_id"].is_monotonic_increasing
