from __future__ import annotations

import math
from itertools import product
from typing import Iterable

import numpy as np
import pandas as pd


def _clip(p):
    return np.clip(np.asarray(p, dtype=float), 1e-8, 1.0 - 1e-8)


def _logit_array(p):
    p = _clip(p)
    return np.log(p / (1.0 - p))


def _logistic_array(z):
    z = np.clip(np.asarray(z, dtype=float), -35.0, 35.0)
    return 1.0 / (1.0 + np.exp(-z))


def _prepare_signed_matrix(frame: pd.DataFrame):
    cols = list(frame.columns)
    raw = frame.apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float, copy=True)
    raw[~np.isfinite(raw)] = 0.0
    scales = np.sqrt(np.mean(raw * raw, axis=0))
    scales = np.where(np.isfinite(scales) & (scales > 1e-8), scales, 1.0)
    return raw / scales, cols, scales


def fit_offset_logistic(
    baseline_probability: Iterable[float],
    X: pd.DataFrame,
    y: Iterable[float],
    *,
    l2: float = 12.0,
    max_iter: int = 80,
    tolerance: float = 1e-9,
) -> dict:
    """Fit a signed residual log-odds correction on top of an accepted baseline."""
    base = _clip(list(baseline_probability))
    y_arr = np.asarray(list(y), dtype=float)
    if len(base) != len(X) or len(y_arr) != len(X):
        raise ValueError("baseline/X/y length mismatch")
    z, cols, scales = _prepare_signed_matrix(X)
    base_eta = _logit_array(base)

    z_aug = np.vstack([z, -z])
    eta_aug = np.concatenate([base_eta, -base_eta])
    y_aug = np.concatenate([y_arr, 1.0 - y_arr])
    w = np.zeros(z.shape[1], dtype=float)
    ridge = max(float(l2), 0.0)
    for _ in range(int(max_iter)):
        p = _logistic_array(eta_aug + z_aug @ w)
        variance = np.clip(p * (1.0 - p), 1e-8, None)
        gradient = z_aug.T @ (y_aug - p) - ridge * w
        hessian = (z_aug.T * variance) @ z_aug + ridge * np.eye(z_aug.shape[1])
        try:
            step = np.linalg.solve(hessian, gradient)
        except np.linalg.LinAlgError:
            step = np.linalg.pinv(hessian) @ gradient
        w_next = w + step
        if float(np.max(np.abs(w_next - w))) < float(tolerance):
            w = w_next
            break
        w = w_next
    return {
        "version": "v5-offset-residual-logistic-1",
        "feature_names": cols,
        "scales": scales.tolist(),
        "coefficients": w.tolist(),
        "l2": ridge,
        "training_rows": int(len(X)),
        "symmetric_no_intercept": True,
    }


def predict_offset_logistic(model: dict, baseline_probability, X: pd.DataFrame) -> np.ndarray:
    cols = list(model["feature_names"])
    raw = X.reindex(columns=cols).apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float, copy=True)
    raw[~np.isfinite(raw)] = 0.0
    scales = np.asarray(model["scales"], dtype=float)
    w = np.asarray(model["coefficients"], dtype=float)
    return _logistic_array(_logit_array(baseline_probability) + (raw / scales) @ w)


def uncertainty_score(frame: pd.DataFrame, residual_probability, context_probability) -> np.ndarray:
    """Epistemic uncertainty from missing evidence plus independent model disagreement."""
    ctx_cols = [c for c in frame.columns if str(c).startswith("ctx_")]
    if ctx_cols:
        numeric = frame[ctx_cols].apply(pd.to_numeric, errors="coerce")
        missing_fraction = numeric.isna().mean(axis=1).to_numpy(dtype=float)
    else:
        missing_fraction = np.ones(len(frame), dtype=float)
    disagreement = np.abs(np.asarray(residual_probability, dtype=float) - np.asarray(context_probability, dtype=float))
    # Missing evidence has larger weight; model disagreement catches cases where architecture itself is unstable.
    return np.clip(0.70 * missing_fraction + 2.0 * disagreement, 0.0, 2.0)


def damp_probability_by_uncertainty(probability, uncertainty, *, gamma: float) -> np.ndarray:
    p = _clip(probability)
    u = np.maximum(np.asarray(uncertainty, dtype=float), 0.0)
    scale = 1.0 / (1.0 + max(float(gamma), 0.0) * u)
    return _logistic_array(_logit_array(p) * scale)


def binary_log_loss(y, p) -> float:
    y = np.asarray(y, dtype=float)
    p = _clip(p)
    return float(-np.mean(y * np.log(p) + (1.0 - y) * np.log(1.0 - p)))


def brier_score(y, p) -> float:
    y = np.asarray(y, dtype=float)
    p = np.asarray(p, dtype=float)
    return float(np.mean((p - y) ** 2))


def fit_uncertainty_gamma(probability, uncertainty, y, candidates=None) -> dict:
    candidates = candidates if candidates is not None else np.linspace(0.0, 4.0, 33)
    rows = []
    for gamma in candidates:
        p = damp_probability_by_uncertainty(probability, uncertainty, gamma=float(gamma))
        rows.append((float(gamma), binary_log_loss(y, p), brier_score(y, p)))
    gamma, loss, brier = min(rows, key=lambda row: (row[1], row[2], row[0]))
    return {"gamma": gamma, "calibration_log_loss": loss, "calibration_brier": brier}


def _weight_grid(names: list[str], step: float):
    if len(names) == 1:
        yield {names[0]: 1.0}
        return
    units = int(round(1.0 / float(step)))
    if not math.isclose(units * step, 1.0, abs_tol=1e-9):
        raise ValueError("step must divide 1.0")
    if len(names) == 3:
        for a in range(units + 1):
            for b in range(units - a + 1):
                c = units - a - b
                yield {names[0]: a / units, names[1]: b / units, names[2]: c / units}
        return
    # Generic recursive integer composition for small model counts.
    def rec(prefix, remaining, slots):
        if slots == 1:
            yield prefix + [remaining]
            return
        for value in range(remaining + 1):
            yield from rec(prefix + [value], remaining - value, slots - 1)
    for weights in rec([], units, len(names)):
        yield {name: value / units for name, value in zip(names, weights)}


def predict_logit_stack(model: dict, predictions: dict[str, np.ndarray]) -> np.ndarray:
    eta = None
    for name, weight in model["weights"].items():
        component = _logit_array(predictions[name]) * float(weight)
        eta = component if eta is None else eta + component
    return _logistic_array(eta)


def fit_logit_stack(predictions: dict[str, np.ndarray], y, *, step: float = 0.05) -> dict:
    names = list(predictions)
    if not names:
        raise ValueError("No component predictions supplied")
    y_arr = np.asarray(y, dtype=float)
    best = None
    for weights in _weight_grid(names, step):
        model = {"weights": weights}
        p = predict_logit_stack(model, predictions)
        score = (binary_log_loss(y_arr, p), brier_score(y_arr, p))
        if best is None or score < best[0]:
            best = (score, weights)
    return {
        "version": "v5-logit-stack-1",
        "weights": best[1],
        "calibration_log_loss": best[0][0],
        "calibration_brier": best[0][1],
        "grid_step": float(step),
    }


def chronological_split(frame: pd.DataFrame, *, fraction: float = 0.70, date_col: str = "match_date"):
    if not 0.0 < fraction < 1.0:
        raise ValueError("fraction must be between zero and one")
    ordered = frame.copy()
    ordered[date_col] = pd.to_datetime(ordered[date_col], errors="coerce")
    ordered = ordered.sort_values([date_col], kind="stable").reset_index(drop=True)
    cut = min(max(int(math.floor(len(ordered) * fraction)), 1), max(len(ordered) - 1, 1))
    return ordered.iloc[:cut].copy(), ordered.iloc[cut:].copy()
