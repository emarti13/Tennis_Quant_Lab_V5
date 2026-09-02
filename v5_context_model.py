from __future__ import annotations

import math
from typing import Iterable

import numpy as np
import pandas as pd

from v5_matchup_features import build_matchup_features


def _prob(value: float) -> float:
    return min(max(float(value), 1e-8), 1.0 - 1e-8)


def _logit(value: float) -> float:
    p = _prob(value)
    return math.log(p / (1.0 - p))


def _logistic_array(values: np.ndarray) -> np.ndarray:
    z = np.clip(np.asarray(values, dtype=float), -35.0, 35.0)
    return 1.0 / (1.0 + np.exp(-z))


def context_feature_family(name: str) -> str:
    key = str(name or "").lower()
    if any(token in key for token in ("layoff", "rest_", "comeback")):
        return "rest_layoff"
    if any(token in key for token in ("matches_3d", "games_3d", "matches_7d", "games_7d", "minutes_7d", "matches_14d", "games_14d", "matches_30d", "games_30d", "previous_match", "consecutive_play", "workload")):
        return "workload"
    if any(token in key for token in ("travel", "timezone", "continent", "altitude_change")):
        return "travel"
    if any(token in key for token in ("court_speed", "weather", "heat", "humidity", "wind", "big_server_x_altitude")):
        return "environment"
    if any(token in key for token in ("serve_first", "serve_second", "ace_rate", "double_fault", "return_strength", "serve_dominance", "return_dominance", "serve_dependence", "weak_second")):
        return "serve_return_geometry"
    if "trajectory" in key:
        return "trajectory"
    if any(token in key for token in ("uncertainty", "context_quality")):
        return "uncertainty_quality"
    if "rank" in key:
        return "rank"
    return "other"


def orient_matchup_row(
    player_one: dict | pd.Series,
    player_two: dict | pd.Series,
    *,
    baseline_winner_probability: float,
    base_features: dict[str, float] | None = None,
    context: dict | None = None,
) -> dict[str, float | str | int]:
    one = dict(player_one)
    two = dict(player_two)
    name_one = str(one.get("player_name") or "")
    name_two = str(two.get("player_name") or "")
    if name_one.casefold() <= name_two.casefold():
        a, b = one, two
    else:
        a, b = two, one

    a_is_winner = str(a.get("player_role") or "").lower() == "winner"
    winner_p = _prob(baseline_winner_probability)
    base = dict(base_features or {})
    sign = 1.0 if a_is_winner else -1.0

    row: dict[str, float | str | int] = {
        "player_a": str(a.get("player_name") or ""),
        "player_b": str(b.get("player_name") or ""),
        "target_a_win": int(a_is_winner),
        "baseline_a_probability": winner_p if a_is_winner else 1.0 - winner_p,
        "x_sr_a": sign * float(base.get("x_sr_winner", np.nan)),
        "x_elo_a": sign * float(base.get("x_elo_winner", np.nan)),
    }
    for key, value in build_matchup_features(a, b, dict(context or {})).items():
        row[f"ctx_{key}"] = value
    return row


def _prepare_training_matrix(frame: pd.DataFrame) -> tuple[np.ndarray, list[str], np.ndarray, np.ndarray, np.ndarray]:
    cols = list(frame.columns)
    raw = frame.apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float, copy=True)
    fill_values = np.zeros(len(cols), dtype=float)
    for j in range(len(cols)):
        raw[~np.isfinite(raw[:, j]), j] = fill_values[j]
    means = np.zeros(len(cols), dtype=float)
    scales = np.sqrt(np.mean(raw * raw, axis=0))
    scales = np.where(np.isfinite(scales) & (scales > 1e-8), scales, 1.0)
    return raw / scales, cols, fill_values, means, scales


def fit_symmetric_logistic(
    X: pd.DataFrame,
    y: Iterable[float],
    *,
    l2: float = 4.0,
    max_iter: int = 80,
    tolerance: float = 1e-9,
) -> dict:
    if X is None or len(X) == 0:
        raise ValueError("Cannot fit contextual model with zero rows")
    y_arr = np.asarray(list(y), dtype=float)
    if len(y_arr) != len(X):
        raise ValueError("X/y length mismatch")
    if not np.isin(y_arr, [0.0, 1.0]).all():
        raise ValueError("Targets must be binary 0/1")

    z, cols, fill_values, means, scales = _prepare_training_matrix(X)
    z_aug = np.vstack([z, -z])
    y_aug = np.concatenate([y_arr, 1.0 - y_arr])
    w = np.zeros(z_aug.shape[1], dtype=float)
    ridge = max(float(l2), 0.0)

    for _ in range(int(max_iter)):
        p = _logistic_array(z_aug @ w)
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
        "version": "v5-context-symmetric-logistic-2",
        "feature_names": cols,
        "coefficients": w.tolist(),
        "medians": fill_values.tolist(),
        "means": means.tolist(),
        "scales": scales.tolist(),
        "l2": ridge,
        "training_rows": int(len(X)),
        "mirrored_training_rows": int(len(y_aug)),
        "symmetric_no_intercept": True,
        "missing_signed_value_policy": "neutral_zero",
    }


def predict_symmetric_logistic(model: dict, X: pd.DataFrame) -> np.ndarray:
    cols = list(model["feature_names"])
    frame = X.reindex(columns=cols).apply(pd.to_numeric, errors="coerce")
    raw = frame.to_numpy(dtype=float, copy=True)
    fill_values = np.asarray(model["medians"], dtype=float)
    scales = np.asarray(model["scales"], dtype=float)
    for j in range(raw.shape[1]):
        raw[~np.isfinite(raw[:, j]), j] = fill_values[j]
    z = raw / scales
    w = np.asarray(model["coefficients"], dtype=float)
    return _logistic_array(z @ w)


def probability_metrics(y: Iterable[float], p: Iterable[float]) -> dict[str, float | int]:
    actual = np.asarray(list(y), dtype=float)
    pred = np.asarray(list(p), dtype=float)
    pred = np.clip(pred, 1e-8, 1.0 - 1e-8)
    if len(actual) == 0:
        return {"n": 0, "brier": float("nan"), "log_loss": float("nan"), "accuracy": float("nan")}
    return {
        "n": int(len(actual)),
        "brier": float(np.mean((pred - actual) ** 2)),
        "log_loss": float(-np.mean(actual * np.log(pred) + (1.0 - actual) * np.log(1.0 - pred))),
        "accuracy": float(np.mean((pred >= 0.5) == (actual >= 0.5))),
    }


def _family_ablations(
    train: pd.DataFrame,
    valid: pd.DataFrame,
    y_train: np.ndarray,
    y_valid: np.ndarray,
    base_cols: list[str],
    context_cols: list[str],
    full_metrics: dict,
    *,
    l2: float,
) -> dict[str, dict]:
    families: dict[str, list[str]] = {}
    for col in context_cols:
        families.setdefault(context_feature_family(col), []).append(col)

    output: dict[str, dict] = {}
    for family, removed in sorted(families.items()):
        kept_context = [c for c in context_cols if c not in removed]
        kept = base_cols + kept_context
        if not kept:
            continue
        model = fit_symmetric_logistic(train[kept], y_train, l2=l2)
        pred = predict_symmetric_logistic(model, valid[kept])
        metrics = probability_metrics(y_valid, pred)
        output[family] = {
            "family": family,
            "removed_features": removed,
            "kept_context_features": int(len(kept_context)),
            "validation_metrics": metrics,
            # Positive delta means validation became worse when the family was removed,
            # therefore the family added OOS value in this frozen fit/validation split.
            "delta_brier_vs_full": float(metrics["brier"] - full_metrics["brier"]),
            "delta_log_loss_vs_full": float(metrics["log_loss"] - full_metrics["log_loss"]),
            "delta_accuracy_vs_full": float(metrics["accuracy"] - full_metrics["accuracy"]),
        }
    return output


def evaluate_context_models(
    frame: pd.DataFrame,
    *,
    fit_year: int = 2025,
    validation_year: int = 2026,
    l2_context: float = 8.0,
    l2_combined: float = 8.0,
) -> dict:
    df = frame.copy()
    train = df[pd.to_numeric(df["year"], errors="coerce") == int(fit_year)].copy()
    valid = df[pd.to_numeric(df["year"], errors="coerce") == int(validation_year)].copy()
    if train.empty or valid.empty:
        raise ValueError("Both fit and validation years require rows")

    context_cols = sorted(c for c in df.columns if c.startswith("ctx_"))
    base_cols = [c for c in ("x_sr_a", "x_elo_a") if c in df.columns]
    if not context_cols:
        raise ValueError("No contextual feature columns found")
    if len(base_cols) != 2:
        raise ValueError("Combined model requires x_sr_a and x_elo_a")

    y_train = pd.to_numeric(train["target_a_win"], errors="coerce").to_numpy(dtype=float)
    y_valid = pd.to_numeric(valid["target_a_win"], errors="coerce").to_numpy(dtype=float)

    context_model = fit_symmetric_logistic(train[context_cols], y_train, l2=l2_context)
    combined_model = fit_symmetric_logistic(train[base_cols + context_cols], y_train, l2=l2_combined)
    context_p = predict_symmetric_logistic(context_model, valid[context_cols])
    combined_p = predict_symmetric_logistic(combined_model, valid[base_cols + context_cols])
    baseline_p = pd.to_numeric(valid["baseline_a_probability"], errors="coerce").to_numpy(dtype=float)

    if not np.isfinite(baseline_p).all():
        raise ValueError("Accepted baseline contains missing validation probabilities")

    baseline_metrics = probability_metrics(y_valid, baseline_p)
    context_metrics = probability_metrics(y_valid, context_p)
    combined_metrics = probability_metrics(y_valid, combined_p)
    ablations = _family_ablations(
        train,
        valid,
        y_train,
        y_valid,
        base_cols,
        context_cols,
        combined_metrics,
        l2=l2_combined,
    )

    return {
        "fit_year": int(fit_year),
        "validation_year": int(validation_year),
        "fit_rows": int(len(train)),
        "validation_rows": int(len(valid)),
        "context_features": context_cols,
        "base_features": base_cols,
        "models": {
            "accepted_baseline": baseline_metrics,
            "context_only": context_metrics,
            "combined": combined_metrics,
        },
        "ablations": ablations,
        "context_model": context_model,
        "combined_model": combined_model,
    }
