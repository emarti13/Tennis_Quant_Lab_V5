from __future__ import annotations

import numpy as np
import pandas as pd

from v5_score_walkforward import distribution_metrics, fit_gaussian_score_model, predict_gaussian_score_model
from v5_tournament_challenger import authority_feature_groups, non_court_context_columns


def _outcome_gate(control: dict, candidate: dict, prefix: str) -> bool:
    crps_gain = float(control[f"{prefix}_crps"]) - float(candidate[f"{prefix}_crps"])
    rmse_ratio = float(candidate[f"{prefix}_rmse"]) / max(float(control[f"{prefix}_rmse"]), 1e-9)
    bias_ok = abs(float(candidate[f"{prefix}_bias"])) <= abs(float(control[f"{prefix}_bias"])) + 0.35
    return bool(crps_gain > 0 and rmse_ratio <= 1.01 and bias_ok)


def evaluate_score_challenger_frame(
    frame: pd.DataFrame,
    *,
    fit_year: int = 2025,
    validation_year: int = 2026,
    l2: float = 16.0,
) -> dict:
    """Evaluate new tournament-authority features for margin (spread) and total games.

    The model is trained only on the fit year and evaluated only on the later
    validation year. No sportsbook price or line is used. Spread here means the
    full game-margin distribution; totals means the full total-games distribution.
    """
    df = frame.copy()
    train = df[pd.to_numeric(df["year"], errors="coerce").eq(int(fit_year))].copy()
    valid = df[pd.to_numeric(df["year"], errors="coerce").eq(int(validation_year))].copy()
    if train.empty or valid.empty:
        raise ValueError("Both fit and validation years require completed-score rows")
    for target in ("actual_margin_a", "actual_total"):
        if target not in df.columns:
            raise ValueError(f"Score challenger requires {target}")

    base = [column for column in ("x_sr_a", "x_elo_a") if column in df.columns]
    if len(base) != 2:
        raise ValueError("Score challenger requires x_sr_a and x_elo_a")
    control_features = base + non_court_context_columns(df)

    control_model = fit_gaussian_score_model(train, features=control_features, l2=l2)
    control_prediction = predict_gaussian_score_model(control_model, valid)
    control_metrics = distribution_metrics(valid["actual_margin_a"], valid["actual_total"], control_prediction)
    models = {"control": control_metrics}
    deltas: dict[str, dict] = {}
    eligibility: dict[str, dict[str, bool]] = {}

    for name, extra in authority_feature_groups(df).items():
        if not extra:
            continue
        features = control_features + extra
        model = fit_gaussian_score_model(train, features=features, l2=l2)
        prediction = predict_gaussian_score_model(model, valid)
        metrics = distribution_metrics(valid["actual_margin_a"], valid["actual_total"], prediction)
        models[name] = metrics
        margin_rmse_ratio = float(metrics["margin_rmse"]) / max(float(control_metrics["margin_rmse"]), 1e-9)
        total_rmse_ratio = float(metrics["total_rmse"]) / max(float(control_metrics["total_rmse"]), 1e-9)
        delta = {
            "margin_crps_gain": float(control_metrics["margin_crps"] - metrics["margin_crps"]),
            "total_crps_gain": float(control_metrics["total_crps"] - metrics["total_crps"]),
            "margin_rmse_gain": float(control_metrics["margin_rmse"] - metrics["margin_rmse"]),
            "total_rmse_gain": float(control_metrics["total_rmse"] - metrics["total_rmse"]),
            "margin_rmse_ratio": margin_rmse_ratio,
            "total_rmse_ratio": total_rmse_ratio,
            "margin_bias_change_abs": float(abs(metrics["margin_bias"]) - abs(control_metrics["margin_bias"])),
            "total_bias_change_abs": float(abs(metrics["total_bias"]) - abs(control_metrics["total_bias"])),
        }
        deltas[name] = delta
        spread_ok = _outcome_gate(control_metrics, metrics, "margin")
        total_ok = _outcome_gate(control_metrics, metrics, "total")
        eligibility[name] = {"spread": spread_ok, "total": total_ok, "both": bool(spread_ok and total_ok)}

    return {
        "fit_year": int(fit_year),
        "validation_year": int(validation_year),
        "fit_rows": int(len(train)),
        "validation_rows": int(len(valid)),
        "market_prices_used": False,
        "spread_definition": "game-margin distribution for player A; not sportsbook ATS hit rate",
        "total_definition": "total-games distribution; not sportsbook over/under hit rate",
        "control_features": control_features,
        "authority_feature_groups": authority_feature_groups(df),
        "models": models,
        "deltas_vs_control": deltas,
        "eligibility": eligibility,
    }
