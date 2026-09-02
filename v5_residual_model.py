from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd

from v5_advanced_model import fit_offset_logistic, predict_offset_logistic


_ALLOWED_ORIGINS = {"oof", "out_of_fold", "walk_forward", "walkforward"}


def _assert_oof(frame: pd.DataFrame) -> None:
    if "prediction_origin" not in frame.columns:
        raise ValueError("Residual training requires explicit out-of-fold or walk-forward prediction_origin metadata")
    origins = set(frame["prediction_origin"].astype(str).str.strip().str.lower())
    if not origins or not origins.issubset(_ALLOWED_ORIGINS):
        raise ValueError("Residual training accepts only out-of-fold or walk-forward base predictions")


def fit_residual_model(
    oof_predictions: pd.DataFrame,
    features: pd.DataFrame,
    target: str,
    *,
    baseline_col: str = "baseline_probability",
    l2: float = 16.0,
) -> dict:
    """Fit winner-logit residual correction only from OOF/walk-forward base predictions."""
    if oof_predictions is None or features is None or len(oof_predictions) != len(features):
        raise ValueError("oof_predictions/features length mismatch")
    _assert_oof(oof_predictions)
    if baseline_col not in oof_predictions.columns or target not in oof_predictions.columns:
        raise ValueError("Residual training requires baseline probability and target columns")
    baseline = pd.to_numeric(oof_predictions[baseline_col], errors="coerce").to_numpy(dtype=float)
    y = pd.to_numeric(oof_predictions[target], errors="coerce").to_numpy(dtype=float)
    if not np.isfinite(baseline).all() or not np.isfinite(y).all():
        raise ValueError("Residual training contains missing baseline/target values")
    model = fit_offset_logistic(baseline, features, y, l2=l2)
    return {
        **model,
        "interface_version": "v5-residual-model-1",
        "baseline_col": baseline_col,
        "target_col": target,
        "prediction_origin_required": True,
    }


def predict_residual_probability(model: dict, baseline_probability: Iterable[float], features: pd.DataFrame) -> np.ndarray:
    return predict_offset_logistic(model, baseline_probability, features)
