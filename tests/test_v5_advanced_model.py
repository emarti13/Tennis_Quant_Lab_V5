import numpy as np
import pandas as pd

from v5_advanced_model import (
    fit_offset_logistic,
    predict_offset_logistic,
    uncertainty_score,
    damp_probability_by_uncertainty,
    fit_logit_stack,
    predict_logit_stack,
    chronological_split,
)


def test_offset_logistic_preserves_player_swap_symmetry():
    X = pd.DataFrame({"ctx_a": [-1.0, -0.5, 0.5, 1.0]})
    y = np.array([0, 0, 1, 1], dtype=float)
    baseline = np.array([0.35, 0.42, 0.58, 0.65])
    model = fit_offset_logistic(baseline, X, y, l2=2.0)
    p = predict_offset_logistic(model, np.array([0.60]), pd.DataFrame({"ctx_a": [0.7]}))[0]
    q = predict_offset_logistic(model, np.array([0.40]), pd.DataFrame({"ctx_a": [-0.7]}))[0]
    assert np.isclose(p + q, 1.0, atol=1e-10)


def test_uncertainty_increases_with_missing_context_and_model_disagreement():
    clean = pd.DataFrame({"ctx_a": [1.0], "ctx_b": [2.0]})
    sparse = pd.DataFrame({"ctx_a": [np.nan], "ctx_b": [np.nan]})
    a = uncertainty_score(clean, np.array([0.62]), np.array([0.60]))[0]
    b = uncertainty_score(sparse, np.array([0.80]), np.array([0.55]))[0]
    assert b > a


def test_uncertainty_damping_moves_probability_toward_half_without_changing_side():
    p = damp_probability_by_uncertainty(np.array([0.80, 0.20]), np.array([1.0, 1.0]), gamma=2.0)
    assert 0.5 < p[0] < 0.80
    assert 0.20 < p[1] < 0.5
    assert np.isclose(p[0] + p[1], 1.0, atol=1e-12)


def test_logit_stack_is_convex_and_swap_symmetric():
    y = np.array([0, 0, 1, 1], dtype=float)
    preds = {
        "baseline": np.array([0.30, 0.40, 0.60, 0.70]),
        "residual": np.array([0.25, 0.35, 0.65, 0.75]),
        "context": np.array([0.32, 0.38, 0.62, 0.68]),
    }
    model = fit_logit_stack(preds, y, step=0.25)
    assert np.isclose(sum(model["weights"].values()), 1.0)
    assert all(v >= 0 for v in model["weights"].values())
    p = predict_logit_stack(model, {k: np.array([v[2]]) for k, v in preds.items()})[0]
    q = predict_logit_stack(model, {k: np.array([1.0 - v[2]]) for k, v in preds.items()})[0]
    assert np.isclose(p + q, 1.0, atol=1e-10)


def test_chronological_split_never_trains_on_later_rows():
    frame = pd.DataFrame({"match_date": pd.date_range("2025-01-01", periods=10), "x": range(10)})
    train, calibrate = chronological_split(frame, fraction=0.7)
    assert len(train) == 7
    assert len(calibrate) == 3
    assert train["match_date"].max() < calibrate["match_date"].min()
