from __future__ import annotations

import math
import re
from typing import Iterable

import numpy as np
import pandas as pd


def parse_completed_score(score: object) -> dict[str, float | int | bool]:
    text = str(score or "").strip().upper()
    if not text or any(token in text for token in ("RET", "W/O", "WO", "WALKOVER", "ABD", "DEF")):
        return {"completed": False, "winner_games": np.nan, "loser_games": np.nan, "total_games": np.nan, "winner_margin": np.nan, "sets": np.nan}
    winner_games = loser_games = sets = 0
    for token in text.split():
        match = re.match(r"^(\d+)-(\d+)(?:\([^)]*\))?$", token)
        if not match:
            continue
        a, b = int(match.group(1)), int(match.group(2))
        winner_games += a; loser_games += b; sets += 1
    completed = sets >= 2 and winner_games > loser_games
    return {
        "completed": bool(completed),
        "winner_games": int(winner_games) if completed else np.nan,
        "loser_games": int(loser_games) if completed else np.nan,
        "total_games": int(winner_games + loser_games) if completed else np.nan,
        "winner_margin": int(winner_games - loser_games) if completed else np.nan,
        "sets": int(sets) if completed else np.nan,
    }


def _numeric_matrix(frame: pd.DataFrame, features: list[str], *, absolute: bool = False) -> tuple[np.ndarray, np.ndarray]:
    x = frame.reindex(columns=features).apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float, copy=True)
    x[~np.isfinite(x)] = 0.0
    if absolute:
        x = np.abs(x)
    scales = np.sqrt(np.mean(x * x, axis=0)) if x.shape[1] else np.array([], dtype=float)
    scales = np.where(np.isfinite(scales) & (scales > 1e-8), scales, 1.0)
    return x / scales, scales


def _ridge_fit(x: np.ndarray, y: np.ndarray, l2: float, *, intercept: bool) -> tuple[np.ndarray, float]:
    if intercept:
        design = np.column_stack([np.ones(len(x)), x])
        penalty = np.eye(design.shape[1]) * float(max(l2, 0.0)); penalty[0, 0] = 0.0
        coef = np.linalg.pinv(design.T @ design + penalty) @ design.T @ y
        return coef[1:], float(coef[0])
    penalty = np.eye(x.shape[1]) * float(max(l2, 0.0))
    coef = np.linalg.pinv(x.T @ x + penalty) @ x.T @ y
    return coef, 0.0


def fit_gaussian_score_model(frame: pd.DataFrame, *, features: list[str], l2: float = 12.0) -> dict:
    """Fit symmetric margin and swap-invariant total Gaussian distributions."""
    margin = pd.to_numeric(frame["actual_margin_a"], errors="coerce").to_numpy(dtype=float)
    total = pd.to_numeric(frame["actual_total"], errors="coerce").to_numpy(dtype=float)
    valid = np.isfinite(margin) & np.isfinite(total)
    if valid.sum() < 4:
        raise ValueError("At least four completed score rows are required")
    train = frame.loc[valid].reset_index(drop=True); margin = margin[valid]; total = total[valid]
    x_signed, scales = _numeric_matrix(train, features, absolute=False)
    x_total, total_scales = _numeric_matrix(train, features, absolute=True)
    margin_coef, _ = _ridge_fit(x_signed, margin, l2, intercept=False)
    total_coef, total_intercept = _ridge_fit(x_total, total, l2, intercept=True)
    margin_fit = x_signed @ margin_coef
    total_fit = total_intercept + x_total @ total_coef
    margin_sd = max(float(np.sqrt(np.mean((margin - margin_fit) ** 2))), 1.0)
    total_sd = max(float(np.sqrt(np.mean((total - total_fit) ** 2))), 1.0)
    return {
        "version": "v5-gaussian-score-1",
        "feature_names": list(features),
        "scales": scales.tolist(),
        "total_scales": total_scales.tolist(),
        "margin_coefficients": margin_coef.tolist(),
        "total_coefficients": total_coef.tolist(),
        "total_intercept": total_intercept,
        "margin_sd": margin_sd,
        "total_sd": total_sd,
        "l2": float(l2),
        "training_rows": int(valid.sum()),
        "market_prices_used": False,
        "margin_player_swap_symmetric": True,
        "total_player_swap_invariant": True,
    }


def predict_gaussian_score_model(model: dict, frame: pd.DataFrame) -> dict[str, np.ndarray]:
    features = list(model["feature_names"])
    raw = frame.reindex(columns=features).apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float, copy=True)
    raw[~np.isfinite(raw)] = 0.0
    signed = raw / np.asarray(model["scales"], dtype=float)
    total_x = np.abs(raw) / np.asarray(model["total_scales"], dtype=float)
    margin_mean = signed @ np.asarray(model["margin_coefficients"], dtype=float)
    total_mean = float(model["total_intercept"]) + total_x @ np.asarray(model["total_coefficients"], dtype=float)
    return {
        "margin_mean": np.asarray(margin_mean, dtype=float),
        "margin_sd": np.full(len(frame), float(model["margin_sd"]), dtype=float),
        "total_mean": np.asarray(total_mean, dtype=float),
        "total_sd": np.full(len(frame), float(model["total_sd"]), dtype=float),
    }


def _normal_crps(y: np.ndarray, mean: np.ndarray, sd: np.ndarray) -> np.ndarray:
    sd = np.maximum(np.asarray(sd, dtype=float), 1e-6)
    z = (np.asarray(y, dtype=float) - np.asarray(mean, dtype=float)) / sd
    erf = np.vectorize(math.erf)
    phi = np.exp(-0.5 * z * z) / math.sqrt(2.0 * math.pi)
    Phi = 0.5 * (1.0 + erf(z / math.sqrt(2.0)))
    return sd * (z * (2.0 * Phi - 1.0) + 2.0 * phi - 1.0 / math.sqrt(math.pi))


def distribution_metrics(actual_margin: Iterable[float], actual_total: Iterable[float], prediction: dict[str, np.ndarray]) -> dict[str, float | int]:
    margin = np.asarray(list(actual_margin), dtype=float); total = np.asarray(list(actual_total), dtype=float)
    mm = np.asarray(prediction["margin_mean"], dtype=float); ms = np.asarray(prediction["margin_sd"], dtype=float)
    tm = np.asarray(prediction["total_mean"], dtype=float); ts = np.asarray(prediction["total_sd"], dtype=float)
    valid = np.isfinite(margin) & np.isfinite(total) & np.isfinite(mm) & np.isfinite(ms) & np.isfinite(tm) & np.isfinite(ts)
    if not valid.any():
        return {"n": 0, "margin_crps": np.nan, "total_crps": np.nan, "margin_bias": np.nan, "total_bias": np.nan, "margin_rmse": np.nan, "total_rmse": np.nan, "margin_mae": np.nan, "total_mae": np.nan}
    margin, total, mm, ms, tm, ts = margin[valid], total[valid], mm[valid], ms[valid], tm[valid], ts[valid]
    me = mm - margin; te = tm - total
    return {
        "n": int(len(margin)),
        "margin_crps": float(np.mean(_normal_crps(margin, mm, ms))),
        "total_crps": float(np.mean(_normal_crps(total, tm, ts))),
        "margin_bias": float(np.mean(me)), "total_bias": float(np.mean(te)),
        "margin_rmse": float(np.sqrt(np.mean(me * me))), "total_rmse": float(np.sqrt(np.mean(te * te))),
        "margin_mae": float(np.mean(np.abs(me))), "total_mae": float(np.mean(np.abs(te))),
    }


def score_candidate_gate(baseline: dict, candidate: dict) -> dict[str, float | bool | str]:
    margin_gain = float(baseline["margin_crps"]) - float(candidate["margin_crps"])
    total_gain = float(baseline["total_crps"]) - float(candidate["total_crps"])
    margin_rmse_ratio = float(candidate["margin_rmse"]) / max(float(baseline["margin_rmse"]), 1e-9)
    total_rmse_ratio = float(candidate["total_rmse"]) / max(float(baseline["total_rmse"]), 1e-9)
    bias_ok = abs(float(candidate["margin_bias"])) <= abs(float(baseline["margin_bias"])) + 0.35 and abs(float(candidate["total_bias"])) <= abs(float(baseline["total_bias"])) + 0.35
    accepted = margin_gain > 0 and total_gain > 0 and margin_rmse_ratio <= 1.01 and total_rmse_ratio <= 1.01 and bias_ok
    return {
        "accepted": bool(accepted), "margin_crps_gain": margin_gain, "total_crps_gain": total_gain,
        "margin_rmse_ratio": margin_rmse_ratio, "total_rmse_ratio": total_rmse_ratio, "bias_ok": bool(bias_ok),
        "reason": "improves both later-period distributions without material RMSE/bias regression" if accepted else "score distribution promotion gate failed",
    }
