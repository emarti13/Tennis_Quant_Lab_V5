from __future__ import annotations

import pytest


def test_daily_score_bundle_promotes_validated_contextual_candidate():
    from v5_daily_batch import _score_model_bundle

    candidate = {
        "version": "v5-score-walkforward-test",
        "market_prices_used": False,
        "MEN": {
            "selected_candidate": "gaussian_contextual",
            "model": {
                "version": "v5-gaussian-score-1",
                "feature_names": ["x_sr_a", "ctx_rest_log1p_diff"],
            },
        },
    }
    live_features = {
        "x_sr_a": 0.12,
        "ctx_rest_log1p_diff": -0.35,
        "ctx_unused": 99.0,
    }

    bundle = _score_model_bundle(
        candidate,
        tour="MEN",
        live_features=live_features,
        simulations=5000,
    )

    assert bundle["model_type"] == "gaussian_contextual"
    assert bundle["model"] == candidate["MEN"]["model"]
    assert bundle["score_features"] == {
        "x_sr_a": pytest.approx(0.12),
        "ctx_rest_log1p_diff": pytest.approx(-0.35),
    }
    assert bundle["simulations"] == 5000


def test_daily_score_bundle_falls_back_only_when_mechanistic_was_selected():
    from v5_daily_batch import _score_model_bundle

    candidate = {
        "version": "v5-score-walkforward-test",
        "market_prices_used": False,
        "WTA": {"selected_candidate": "conditioned_mechanistic", "model": None},
    }

    bundle = _score_model_bundle(
        candidate,
        tour="WTA",
        live_features={"x_sr_a": 0.08},
        simulations=3000,
    )

    assert bundle["model_type"] == "conditioned_mechanistic"
    assert bundle["simulations"] == 3000
    assert "model" not in bundle
    assert "score_features" not in bundle


def test_daily_score_bundle_rejects_missing_validated_candidate():
    from v5_daily_batch import _score_model_bundle

    with pytest.raises(ValueError, match="validated score candidate"):
        _score_model_bundle(None, tour="MEN", live_features={}, simulations=1000)
