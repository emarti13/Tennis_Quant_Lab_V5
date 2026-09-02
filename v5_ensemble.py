from __future__ import annotations

import math
from typing import Mapping

import numpy as np
import pandas as pd

from v5_advanced_model import fit_logit_stack, predict_logit_stack


def _entropy(p: float) -> float:
    p = min(max(float(p), 1e-12), 1.0 - 1e-12)
    return float(-(p * math.log(p) + (1.0 - p) * math.log(1.0 - p)))


def ensemble_features(predictions: Mapping[str, float]) -> dict[str, float]:
    values = np.asarray([float(v) for v in predictions.values() if np.isfinite(float(v))], dtype=float)
    if len(values) == 0:
        return {
            "probability_range": float("nan"),
            "probability_std": float("nan"),
            "entropy_mean": float("nan"),
        }
    return {
        "probability_range": float(values.max() - values.min()),
        "probability_std": float(values.std(ddof=0)),
        "entropy_mean": float(np.mean([_entropy(v) for v in values])),
    }


def fit_ensemble(oof_model_predictions: pd.DataFrame, y: np.ndarray, *, step: float = 0.05) -> dict:
    if oof_model_predictions is None or oof_model_predictions.empty:
        raise ValueError("No out-of-fold model predictions supplied")
    predictions = {
        str(col): pd.to_numeric(oof_model_predictions[col], errors="coerce").to_numpy(dtype=float)
        for col in oof_model_predictions.columns
    }
    if any(not np.isfinite(values).all() for values in predictions.values()):
        raise ValueError("Ensemble predictions contain missing values")
    model = fit_logit_stack(predictions, np.asarray(y, dtype=float), step=step)
    return {**model, "interface_version": "v5-ensemble-1"}


def predict_ensemble(model: dict, model_predictions: pd.DataFrame) -> np.ndarray:
    predictions = {
        str(name): pd.to_numeric(model_predictions[name], errors="coerce").to_numpy(dtype=float)
        for name in model["weights"]
    }
    return predict_logit_stack(model, predictions)
