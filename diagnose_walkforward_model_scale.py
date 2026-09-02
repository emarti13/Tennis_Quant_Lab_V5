from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path("v5_daily_ready/walkforward_model_scale_diagnostic.json")
FILES = {
    "MEN": Path("v5_men_walkforward.csv"),
    "WTA": Path("v5_wta_walkforward.csv"),
}


def clip_prob(x):
    return np.clip(np.asarray(x, dtype=float), 1e-5, 1 - 1e-5)


def logit(x):
    p = clip_prob(x)
    return np.log(p / (1 - p))


def sigmoid(z):
    z = np.asarray(z, dtype=float)
    out = np.empty_like(z)
    pos = z >= 0
    out[pos] = 1 / (1 + np.exp(-z[pos]))
    ez = np.exp(z[~pos])
    out[~pos] = ez / (1 + ez)
    return out


def fit_symmetric_logistic(x_win, l2=1e-3, max_iter=100):
    x_win = np.asarray(x_win, dtype=float)
    if x_win.ndim == 1:
        x_win = x_win[:, None]
    x = np.vstack([x_win, -x_win])
    y = np.concatenate([np.ones(len(x_win)), np.zeros(len(x_win))])
    beta = np.zeros(x.shape[1], dtype=float)
    eye = np.eye(x.shape[1])
    for _ in range(max_iter):
        p = sigmoid(x @ beta)
        w = np.clip(p * (1 - p), 1e-8, None)
        grad = x.T @ (p - y) + l2 * beta
        hess = x.T @ (x * w[:, None]) + l2 * eye
        step = np.linalg.solve(hess, grad)
        beta_next = beta - step
        if np.max(np.abs(beta_next - beta)) < 1e-10:
            beta = beta_next
            break
        beta = beta_next
    return beta


def metrics(p_win):
    p = clip_prob(p_win)
    return {
        "n": int(len(p)),
        "mean_predicted_winner_probability": float(np.mean(p)),
        "brier": float(np.mean((1 - p) ** 2)),
        "log_loss": float(np.mean(-np.log(p))),
        "winner_rank_accuracy": float(np.mean(p > 0.5)),
        "winner_predicted_below_20pct_rate": float(np.mean(p < 0.2)),
        "winner_predicted_below_10pct_rate": float(np.mean(p < 0.1)),
    }


def prepare(path):
    d = pd.read_csv(path, low_memory=False)
    d["date"] = pd.to_datetime(d["date"], errors="coerce")
    for c in ("winner_serve_p", "loser_serve_p", "elo_winner_p"):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d.dropna(subset=["date", "winner_serve_p", "loser_serve_p", "elo_winner_p"]).copy()
    d = d[
        d["winner_serve_p"].between(0.001, 0.999)
        & d["loser_serve_p"].between(0.001, 0.999)
        & d["elo_winner_p"].between(0.001, 0.999)
    ].copy()
    d["x_sr"] = logit(d["winner_serve_p"].to_numpy()) - logit(d["loser_serve_p"].to_numpy())
    d["x_elo"] = logit(d["elo_winner_p"].to_numpy())
    return d


def fit_and_evaluate(train, test):
    models = {}
    specs = {
        "serve_return_only": ["x_sr"],
        "elo_only_recalibrated": ["x_elo"],
        "serve_return_plus_elo": ["x_sr", "x_elo"],
    }
    for name, cols in specs.items():
        beta = fit_symmetric_logistic(train[cols].to_numpy())
        train_p = sigmoid(train[cols].to_numpy() @ beta)
        test_p = sigmoid(test[cols].to_numpy() @ beta) if len(test) else np.array([])
        models[name] = {
            "features": cols,
            "coefficients": {c: float(v) for c, v in zip(cols, beta)},
            "train_2025": metrics(train_p),
            "validation_2026": metrics(test_p) if len(test_p) else None,
        }
    # Unmodified surface Elo is already a probability and is an independent benchmark.
    models["raw_elo_benchmark"] = {
        "train_2025": metrics(train["elo_winner_p"].to_numpy()),
        "validation_2026": metrics(test["elo_winner_p"].to_numpy()) if len(test) else None,
    }
    return models


def segment_result(d, label):
    train = d[d["date"].dt.year == 2025].copy()
    test = d[d["date"].dt.year == 2026].copy()
    return {
        "segment": label,
        "rows_total": int(len(d)),
        "rows_2025_calibration": int(len(train)),
        "rows_2026_validation": int(len(test)),
        "date_min": str(d["date"].min().date()) if len(d) else None,
        "date_max": str(d["date"].max().date()) if len(d) else None,
        "levels": {str(k): int(v) for k, v in d["level"].astype(str).value_counts().to_dict().items()} if "level" in d.columns else {},
        "models": fit_and_evaluate(train, test) if len(train) else {},
    }


def main():
    result = {"method": {
        "calibration_year": 2025,
        "validation_year": 2026,
        "serve_return_feature": "logit(winner_serve_p) - logit(loser_serve_p)",
        "elo_feature": "logit(pre_match_surface_blended_elo_winner_p)",
        "fit": "symmetric no-intercept logistic regression; 2026 never used for fitting",
        "note": "Walk-forward serve probabilities are pre-match and do not include the live simulator's form/volatility draw; this diagnoses matchup-strength scale independently of market prices.",
    }, "segments": {}}

    for tour, path in FILES.items():
        d = prepare(path)
        result["segments"][tour] = segment_result(d, tour)
        if tour == "MEN" and "level" in d.columns:
            # ATP source uses G for Grand Slam main draw; keep this diagnostic explicit.
            slam = d[d["level"].astype(str).str.upper() == "G"].copy()
            non_slam = d[d["level"].astype(str).str.upper() != "G"].copy()
            result["segments"]["MEN_GRAND_SLAM_LEVEL_G"] = segment_result(slam, "MEN_GRAND_SLAM_LEVEL_G")
            result["segments"]["MEN_NON_GRAND_SLAM"] = segment_result(non_slam, "MEN_NON_GRAND_SLAM")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
