from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from v5_advanced_model import (
    brier_score,
    binary_log_loss,
    chronological_split,
    damp_probability_by_uncertainty,
    fit_logit_stack,
    fit_offset_logistic,
    fit_uncertainty_gamma,
    predict_logit_stack,
    predict_offset_logistic,
    uncertainty_score,
)
from v5_context_model import fit_symmetric_logistic, predict_symmetric_logistic

OUTDIR = Path("v5_advanced_diagnostic")


def _metrics(y, p):
    y = np.asarray(y, dtype=float)
    p = np.asarray(p, dtype=float)
    call = p >= 0.5
    return {
        "n": int(len(y)),
        "brier": brier_score(y, p),
        "log_loss": binary_log_loss(y, p),
        "accuracy": float(np.mean(call == (y >= 0.5))),
        "mean_probability": float(np.mean(p)),
    }


def _monthly_metrics(frame: pd.DataFrame, probability_col: str):
    out = {}
    dates = pd.to_datetime(frame["match_date"], errors="coerce")
    for period, group in frame.assign(_month=dates.dt.to_period("M").astype(str)).groupby("_month", sort=True):
        if period in {"NaT", "nan"}:
            continue
        out[str(period)] = _metrics(
            pd.to_numeric(group["target_a_win"], errors="coerce"),
            pd.to_numeric(group[probability_col], errors="coerce"),
        )
    return out


def _candidate_gate(baseline: dict, candidate: dict) -> dict:
    brier_gain = float(baseline["brier"] - candidate["brier"])
    log_gain = float(baseline["log_loss"] - candidate["log_loss"])
    accuracy_delta = float(candidate["accuracy"] - baseline["accuracy"])
    accepted = brier_gain > 0 and log_gain > 0 and accuracy_delta >= -0.005
    return {
        "accepted": bool(accepted),
        "brier_improvement": brier_gain,
        "log_loss_improvement": log_gain,
        "accuracy_delta": accuracy_delta,
    }


def evaluate_tour(frame: pd.DataFrame, tour: str) -> dict:
    frame = frame.copy()
    frame["match_date"] = pd.to_datetime(frame["match_date"], errors="coerce")
    fit_2025 = frame[pd.to_numeric(frame["year"], errors="coerce") == 2025].copy()
    valid_2026 = frame[pd.to_numeric(frame["year"], errors="coerce") == 2026].copy()
    train, calibrate = chronological_split(fit_2025, fraction=0.70)

    context_cols = sorted(c for c in frame.columns if c.startswith("ctx_"))
    base_cols = ["x_sr_a", "x_elo_a"]
    signed_cols = base_cols + context_cols

    y_train = pd.to_numeric(train["target_a_win"], errors="coerce").to_numpy(dtype=float)
    y_cal = pd.to_numeric(calibrate["target_a_win"], errors="coerce").to_numpy(dtype=float)
    y_valid = pd.to_numeric(valid_2026["target_a_win"], errors="coerce").to_numpy(dtype=float)
    baseline_train = pd.to_numeric(train["baseline_a_probability"], errors="coerce").to_numpy(dtype=float)
    baseline_cal = pd.to_numeric(calibrate["baseline_a_probability"], errors="coerce").to_numpy(dtype=float)
    baseline_valid = pd.to_numeric(valid_2026["baseline_a_probability"], errors="coerce").to_numpy(dtype=float)

    direct_model = fit_symmetric_logistic(train[signed_cols], y_train, l2=12.0)
    residual_model = fit_offset_logistic(baseline_train, train[context_cols], y_train, l2=16.0)

    direct_cal = predict_symmetric_logistic(direct_model, calibrate[signed_cols])
    residual_cal = predict_offset_logistic(residual_model, baseline_cal, calibrate[context_cols])
    uncertainty_cal = uncertainty_score(calibrate, residual_cal, direct_cal)
    gamma_model = fit_uncertainty_gamma(residual_cal, uncertainty_cal, y_cal)
    residual_damped_cal = damp_probability_by_uncertainty(
        residual_cal, uncertainty_cal, gamma=gamma_model["gamma"]
    )

    stack_model = fit_logit_stack(
        {
            "accepted_baseline": baseline_cal,
            "residual_uncertainty": residual_damped_cal,
            "direct_context": direct_cal,
        },
        y_cal,
        step=0.05,
    )

    direct_valid = predict_symmetric_logistic(direct_model, valid_2026[signed_cols])
    residual_valid = predict_offset_logistic(residual_model, baseline_valid, valid_2026[context_cols])
    uncertainty_valid = uncertainty_score(valid_2026, residual_valid, direct_valid)
    residual_damped_valid = damp_probability_by_uncertainty(
        residual_valid, uncertainty_valid, gamma=gamma_model["gamma"]
    )
    stack_valid = predict_logit_stack(
        stack_model,
        {
            "accepted_baseline": baseline_valid,
            "residual_uncertainty": residual_damped_valid,
            "direct_context": direct_valid,
        },
    )

    predictions = valid_2026.copy()
    predictions["accepted_baseline_probability"] = baseline_valid
    predictions["direct_context_probability"] = direct_valid
    predictions["residual_probability"] = residual_valid
    predictions["uncertainty_score"] = uncertainty_valid
    predictions["residual_uncertainty_probability"] = residual_damped_valid
    predictions["ensemble_probability"] = stack_valid

    metrics = {
        "accepted_baseline": _metrics(y_valid, baseline_valid),
        "direct_context": _metrics(y_valid, direct_valid),
        "residual": _metrics(y_valid, residual_valid),
        "residual_uncertainty": _metrics(y_valid, residual_damped_valid),
        "ensemble": _metrics(y_valid, stack_valid),
    }
    gates = {name: _candidate_gate(metrics["accepted_baseline"], value) for name, value in metrics.items() if name != "accepted_baseline"}
    eligible = [name for name, gate in gates.items() if gate["accepted"]]
    if eligible:
        selected = min(eligible, key=lambda name: (metrics[name]["log_loss"], metrics[name]["brier"]))
    else:
        selected = "accepted_baseline"

    predictions["selected_probability"] = predictions[
        {
            "accepted_baseline": "accepted_baseline_probability",
            "direct_context": "direct_context_probability",
            "residual": "residual_probability",
            "residual_uncertainty": "residual_uncertainty_probability",
            "ensemble": "ensemble_probability",
        }[selected]
    ]

    monthly = {name: _monthly_metrics(predictions, col) for name, col in {
        "accepted_baseline": "accepted_baseline_probability",
        "residual_uncertainty": "residual_uncertainty_probability",
        "ensemble": "ensemble_probability",
        "selected": "selected_probability",
    }.items()}

    return {
        "tour": tour,
        "architecture": {
            "component_fit": "earliest 70% of chronological 2025",
            "uncertainty_and_stack_fit": "latest 30% of chronological 2025",
            "final_validation": "all matched 2026; no market prices used",
            "train_rows": int(len(train)),
            "calibration_rows": int(len(calibrate)),
            "validation_rows": int(len(valid_2026)),
            "train_end": str(train["match_date"].max()),
            "calibration_start": str(calibrate["match_date"].min()),
        },
        "metrics_2026": metrics,
        "gates_vs_accepted_baseline": gates,
        "selected_candidate": selected,
        "selected_metrics_2026": metrics[selected],
        "uncertainty_model": gamma_model,
        "stack_model": stack_model,
        "residual_model": residual_model,
        "direct_context_model": direct_model,
        "monthly_2026": monthly,
        "predictions": predictions,
    }


def run(base_dir: str | Path = ".") -> dict:
    base = Path(base_dir)
    path = base / "v5_context_diagnostic" / "matched_context_rows.parquet"
    if not path.exists():
        raise FileNotFoundError("Run diagnose_v5_context_model.py first")
    frame = pd.read_parquet(path)
    report = {
        "version": "v5-advanced-nested-chronological-1",
        "market_prices_used": False,
        "tours": {},
        "production_gate": {},
    }
    prediction_frames = []
    for tour in ("MEN", "WTA"):
        group = frame[frame["tour"].astype(str).str.upper() == tour].copy()
        result = evaluate_tour(group, tour)
        predictions = result.pop("predictions")
        prediction_frames.append(predictions.assign(model_tour=tour))
        report["tours"][tour] = result
        report["production_gate"][tour] = {
            "selected_candidate": result["selected_candidate"],
            "candidate_beats_baseline": result["selected_candidate"] != "accepted_baseline",
            "metrics": result["selected_metrics_2026"],
        }

    out_dir = base / OUTDIR
    out_dir.mkdir(parents=True, exist_ok=True)
    if prediction_frames:
        pd.concat(prediction_frames, ignore_index=True, sort=False).to_csv(out_dir / "advanced_predictions_2026.csv", index=False)
    (out_dir / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    production = {
        "version": report["version"],
        "MEN": {
            "selected_candidate": report["tours"]["MEN"]["selected_candidate"],
            "uncertainty_model": report["tours"]["MEN"]["uncertainty_model"],
            "stack_model": report["tours"]["MEN"]["stack_model"],
            "residual_model": report["tours"]["MEN"]["residual_model"],
            "direct_context_model": report["tours"]["MEN"]["direct_context_model"],
        },
        "WTA": {
            "selected_candidate": report["tours"]["WTA"]["selected_candidate"],
            "uncertainty_model": report["tours"]["WTA"]["uncertainty_model"],
            "stack_model": report["tours"]["WTA"]["stack_model"],
            "residual_model": report["tours"]["WTA"]["residual_model"],
            "direct_context_model": report["tours"]["WTA"]["direct_context_model"],
        },
    }
    (out_dir / "production_candidate.json").write_text(json.dumps(production, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(report, indent=2, allow_nan=False))
    return report


if __name__ == "__main__":
    run(".")
