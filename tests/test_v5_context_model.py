import numpy as np
import pandas as pd

from v5_context_model import (
    fit_symmetric_logistic,
    predict_symmetric_logistic,
    evaluate_context_models,
    orient_matchup_row,
)


def test_orientation_is_deterministic_and_reverses_winner_probability():
    feature_a = {"player_name": "Alpha", "player_role": "loser", "serve_first_won": .68, "return_strength": .39}
    feature_b = {"player_name": "Zulu", "player_role": "winner", "serve_first_won": .72, "return_strength": .43}
    out = orient_matchup_row(feature_a, feature_b, baseline_winner_probability=.70, base_features={"x_sr_winner": .18, "x_elo_winner": .55})
    assert out["player_a"] == "Alpha"
    assert out["player_b"] == "Zulu"
    assert out["target_a_win"] == 0
    assert np.isclose(out["baseline_a_probability"], .30)
    assert np.isclose(out["x_sr_a"], -.18)
    assert np.isclose(out["x_elo_a"], -.55)


def test_symmetric_logistic_prediction_complements_when_features_reverse():
    X = pd.DataFrame({"f1": [-2., -1., 1., 2.], "f2": [1., .5, -.5, -1.]})
    y = np.array([0, 0, 1, 1], dtype=float)
    model = fit_symmetric_logistic(X, y, l2=1.0)
    p = predict_symmetric_logistic(model, pd.DataFrame({"f1": [1.2], "f2": [-.4]}))[0]
    q = predict_symmetric_logistic(model, pd.DataFrame({"f1": [-1.2], "f2": [.4]}))[0]
    assert np.isclose(p + q, 1.0, atol=1e-10)


def test_missing_signed_feature_is_neutral_and_preserves_swap_symmetry():
    # f1 deliberately has a nonzero training median. A signed A-minus-B feature cannot
    # be imputed to that same positive value in both orientations; missing must be neutral 0.
    X = pd.DataFrame({"f1": [1., 2., 3., 4.], "f2": [-2., -.5, .5, 2.]})
    y = np.array([0, 0, 1, 1], dtype=float)
    model = fit_symmetric_logistic(X, y, l2=1.0)
    p = predict_symmetric_logistic(model, pd.DataFrame({"f1": [np.nan], "f2": [.8]}))[0]
    q = predict_symmetric_logistic(model, pd.DataFrame({"f1": [np.nan], "f2": [-.8]}))[0]
    assert np.isclose(p + q, 1.0, atol=1e-10)


def test_training_imputation_is_not_changed_by_validation_values():
    train_x = pd.DataFrame({"f1": [1., 2., np.nan, 4.], "f2": [0., 1., 0., 1.]})
    y = np.array([0, 0, 1, 1], dtype=float)
    a = fit_symmetric_logistic(train_x, y, l2=1.0)
    b = fit_symmetric_logistic(train_x, y, l2=1.0)
    validation_a = pd.DataFrame({"f1": [1000000.], "f2": [1.]})
    validation_b = pd.DataFrame({"f1": [-1000000.], "f2": [1.]})
    assert np.allclose(a["medians"], b["medians"])
    assert np.allclose(a["means"], b["means"])
    assert np.allclose(a["scales"], b["scales"])
    assert predict_symmetric_logistic(a, validation_a).shape == (1,)
    assert predict_symmetric_logistic(b, validation_b).shape == (1,)


def test_walkforward_evaluation_fits_2025_and_scores_2026_only():
    rows = []
    for year in (2025, 2026):
        for i in range(20):
            strength = (i - 9.5) / 5.0
            y = int(strength + (0.4 if year == 2026 else 0.0) > 0)
            baseline = 1.0 / (1.0 + np.exp(-0.8 * strength))
            rows.append({
                "year": year,
                "tour": "MEN",
                "target_a_win": y,
                "baseline_a_probability": baseline,
                "x_sr_a": strength * .12,
                "x_elo_a": strength * .7,
                "ctx_serve_first_won_diff": strength * .03,
                "ctx_return_strength_diff": strength * .02,
                "ctx_rest_days_diff": float(i % 3 - 1),
            })
    frame = pd.DataFrame(rows)
    report = evaluate_context_models(frame, fit_year=2025, validation_year=2026)
    assert report["fit_year"] == 2025
    assert report["validation_year"] == 2026
    assert report["validation_rows"] == 20
    assert set(report["models"]) == {"accepted_baseline", "context_only", "combined"}
    for model in report["models"].values():
        assert 0 <= model["brier"] <= 1
        assert model["log_loss"] >= 0
