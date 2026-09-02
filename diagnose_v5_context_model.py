from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from build_v5_context_matchups import assemble_matchup_dataset, enrich_player_history, load_walkforward
from v5_context_model import evaluate_context_models, predict_symmetric_logistic


BANDS = [
    ("under_10", 0.00, 0.10),
    ("10_to_20", 0.10, 0.20),
    ("20_to_40", 0.20, 0.40),
    ("40_to_60", 0.40, 0.60),
    ("60_to_80", 0.60, 0.80),
    ("80_to_90", 0.80, 0.90),
    ("over_90", 0.90, 1.0000001),
]


def probability_band_report(frame: pd.DataFrame, *, probability_col: str) -> dict:
    """Report candidate calibration inside bands defined by accepted-baseline strength."""
    if frame is None or frame.empty:
        return {name: {"n": 0, "mean_prediction": None, "actual_win_rate": None, "calibration_error": None} for name, _, _ in BANDS}
    baseline = pd.to_numeric(frame["baseline_a_probability"], errors="coerce")
    candidate = pd.to_numeric(frame[probability_col], errors="coerce")
    actual = pd.to_numeric(frame["target_a_win"], errors="coerce")
    out = {}
    for name, low, high in BANDS:
        mask = baseline.ge(low) & baseline.lt(high) & candidate.notna() & actual.notna()
        n = int(mask.sum())
        if n == 0:
            out[name] = {"n": 0, "mean_prediction": None, "actual_win_rate": None, "calibration_error": None}
            continue
        mean_p = float(candidate[mask].mean())
        actual_rate = float(actual[mask].mean())
        out[name] = {
            "n": n,
            "mean_prediction": mean_p,
            "actual_win_rate": actual_rate,
            "calibration_error": mean_p - actual_rate,
        }
    return out


def feature_coverage_report(frame: pd.DataFrame) -> dict:
    report = {}
    for col in sorted(c for c in frame.columns if c.startswith("ctx_")):
        values = pd.to_numeric(frame[col], errors="coerce")
        finite = values[np.isfinite(values)]
        unique = int(finite.nunique()) if len(finite) else 0
        report[col] = {
            "non_missing_fraction": float(values.notna().mean()) if len(values) else 0.0,
            "finite_unique_values": unique,
            "constant": bool(unique <= 1),
            "mean": None if len(finite) == 0 else float(finite.mean()),
            "std": None if len(finite) <= 1 else float(finite.std(ddof=0)),
        }
    return report


def prediction_flip_report(frame: pd.DataFrame, *, max_rows: int = 50) -> dict:
    """Compare accepted baseline winner calls with the candidate combined model."""
    if frame is None or frame.empty:
        return {
            "n": 0, "old_accuracy": None, "new_accuracy": None, "flips": 0,
            "old_wrong_new_correct": 0, "old_correct_new_wrong": 0,
            "net_corrected_flips": 0, "flip_rows": [],
        }
    df = frame.copy()
    actual = pd.to_numeric(df["target_a_win"], errors="coerce")
    old_p = pd.to_numeric(df["accepted_baseline_probability"], errors="coerce")
    new_p = pd.to_numeric(df["combined_probability"], errors="coerce")
    valid = actual.notna() & old_p.notna() & new_p.notna()
    df = df.loc[valid].copy()
    actual = actual.loc[valid].astype(int)
    old_p = old_p.loc[valid]
    new_p = new_p.loc[valid]
    old_call = old_p.ge(0.5).astype(int)
    new_call = new_p.ge(0.5).astype(int)
    old_correct = old_call.eq(actual)
    new_correct = new_call.eq(actual)
    flips = old_call.ne(new_call)
    corrected = flips & (~old_correct) & new_correct
    harmed = flips & old_correct & (~new_correct)

    flip_rows = df.loc[flips].copy()
    if not flip_rows.empty:
        flip_rows["_old_p"] = old_p.loc[flips]
        flip_rows["_new_p"] = new_p.loc[flips]
        flip_rows["_actual"] = actual.loc[flips]
        flip_rows["_swing"] = (flip_rows["_new_p"] - flip_rows["_old_p"]).abs()
        flip_rows = flip_rows.sort_values("_swing", ascending=False).head(int(max_rows))

    rows = []
    for _, row in flip_rows.iterrows():
        actual_a = int(row["_actual"])
        old_a = int(float(row["_old_p"]) >= 0.5)
        new_a = int(float(row["_new_p"]) >= 0.5)
        a = str(row.get("player_a") or "")
        b = str(row.get("player_b") or "")
        date = pd.to_datetime(row.get("match_date"), errors="coerce")
        rows.append({
            "match_date": None if pd.isna(date) else date.strftime("%Y-%m-%d"),
            "tour": row.get("tour"),
            "surface": row.get("surface"),
            "tourney_name": row.get("tourney_name"),
            "actual_winner": a if actual_a else b,
            "actual_loser": b if actual_a else a,
            "old_predicted_winner": a if old_a else b,
            "old_predicted_probability": float(row["_old_p"] if old_a else 1.0 - row["_old_p"]),
            "new_predicted_winner": a if new_a else b,
            "new_predicted_probability": float(row["_new_p"] if new_a else 1.0 - row["_new_p"]),
            "probability_swing_a": float(row["_new_p"] - row["_old_p"]),
            "old_correct": bool(old_a == actual_a),
            "new_correct": bool(new_a == actual_a),
        })

    n = int(len(df))
    return {
        "n": n,
        "old_accuracy": None if n == 0 else float(old_correct.mean()),
        "new_accuracy": None if n == 0 else float(new_correct.mean()),
        "flips": int(flips.sum()),
        "old_wrong_new_correct": int(corrected.sum()),
        "old_correct_new_wrong": int(harmed.sum()),
        "net_corrected_flips": int(corrected.sum() - harmed.sum()),
        "flip_rows": rows,
    }


def load_tournament_registry(base_dir: str | Path = ".") -> pd.DataFrame:
    path = Path(base_dir) / "context_registry" / "tournaments.csv"
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, low_memory=False)


def _validation_predictions(tour_frame: pd.DataFrame, evaluation: dict, validation_year: int = 2026) -> pd.DataFrame:
    valid = tour_frame[pd.to_numeric(tour_frame["year"], errors="coerce") == int(validation_year)].copy()
    context_cols = evaluation["context_features"]
    base_cols = evaluation["base_features"]
    valid["accepted_baseline_probability"] = pd.to_numeric(valid["baseline_a_probability"], errors="coerce")
    valid["context_only_probability"] = predict_symmetric_logistic(evaluation["context_model"], valid[context_cols])
    valid["combined_probability"] = predict_symmetric_logistic(evaluation["combined_model"], valid[base_cols + context_cols])
    return valid


def _coefficient_report(model: dict) -> list[dict]:
    rows = []
    for name, coefficient, scale in zip(model["feature_names"], model["coefficients"], model["scales"]):
        rows.append({
            "feature": str(name),
            "standardized_coefficient": float(coefficient),
            "training_rms_scale": float(scale),
            "absolute_coefficient": abs(float(coefficient)),
        })
    return sorted(rows, key=lambda row: row["absolute_coefficient"], reverse=True)


def run_diagnostic(base_dir: str | Path = ".", output_dir: str | Path = "v5_context_diagnostic") -> dict:
    base = Path(base_dir)
    out_dir = base / output_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    player_path = base / "context_warehouse" / "player_match_rows.parquet"
    if not player_path.exists():
        raise FileNotFoundError("context_warehouse/player_match_rows.parquet missing; build the context warehouse first")

    player_rows = pd.read_parquet(player_path)
    tournament_registry = load_tournament_registry(base)
    enriched = enrich_player_history(player_rows, tournament_registry=tournament_registry)
    walkforward = load_walkforward(base)
    matchups, join_qc = assemble_matchup_dataset(enriched, walkforward, target_years=(2025, 2026))
    if matchups.empty:
        raise RuntimeError("No exact contextual matchup rows were assembled")

    matchups.to_parquet(out_dir / "matched_context_rows.parquet", index=False)
    report = {
        "diagnostic_version": "v5-context-2025-2026-oos-3",
        "fit_year": 2025,
        "validation_year": 2026,
        "venue_registry_rows": int(len(tournament_registry)),
        "join_qc": join_qc,
        "matched_rows": int(len(matchups)),
        "matched_by_year": {str(int(k)): int(v) for k, v in matchups["year"].value_counts().sort_index().to_dict().items()},
        "matched_by_tour": {str(k): int(v) for k, v in matchups["tour"].value_counts().to_dict().items()},
        "feature_coverage_all": feature_coverage_report(matchups),
        "tours": {},
    }

    prediction_frames = []
    for tour in ("MEN", "WTA"):
        tour_frame = matchups[matchups["tour"].astype(str).str.upper() == tour].copy()
        fit_rows = int((pd.to_numeric(tour_frame["year"], errors="coerce") == 2025).sum())
        validation_rows = int((pd.to_numeric(tour_frame["year"], errors="coerce") == 2026).sum())
        if fit_rows == 0 or validation_rows == 0:
            report["tours"][tour] = {"status": "insufficient_rows", "fit_rows": fit_rows, "validation_rows": validation_rows}
            continue

        evaluation = evaluate_context_models(tour_frame, fit_year=2025, validation_year=2026)
        valid = _validation_predictions(tour_frame, evaluation, 2026)
        valid["model_tour"] = tour
        prediction_frames.append(valid)

        tail = {
            "accepted_baseline": probability_band_report(valid.rename(columns={"accepted_baseline_probability": "candidate_probability"}), probability_col="candidate_probability"),
            "context_only": probability_band_report(valid.rename(columns={"context_only_probability": "candidate_probability"}), probability_col="candidate_probability"),
            "combined": probability_band_report(valid.rename(columns={"combined_probability": "candidate_probability"}), probability_col="candidate_probability"),
        }
        report["tours"][tour] = {
            "status": "evaluated",
            "fit_rows": evaluation["fit_rows"],
            "validation_rows": evaluation["validation_rows"],
            "models": evaluation["models"],
            "ablations": evaluation["ablations"],
            "winner_call_flips": prediction_flip_report(valid),
            "tail_calibration_by_accepted_baseline_band": tail,
            "feature_coverage": feature_coverage_report(tour_frame),
            "context_coefficients": _coefficient_report(evaluation["context_model"]),
            "combined_coefficients": _coefficient_report(evaluation["combined_model"]),
        }

    if prediction_frames:
        predictions = pd.concat(prediction_frames, ignore_index=True, sort=False)
        report["combined_2026_winner_call_flips"] = prediction_flip_report(predictions, max_rows=100)
        keep = [
            c for c in ["match_id", "match_date", "tour", "surface", "level", "tourney_name", "player_a", "player_b",
                        "target_a_win", "baseline_a_probability", "accepted_baseline_probability", "context_only_probability",
                        "combined_probability"] if c in predictions.columns
        ]
        predictions[keep].to_csv(out_dir / "validation_predictions_2026.csv", index=False)
        pd.DataFrame(report["combined_2026_winner_call_flips"]["flip_rows"]).to_csv(out_dir / "prediction_flips_2026.csv", index=False)

    (out_dir / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(report, indent=2, allow_nan=False))
    return report


def main() -> int:
    run_diagnostic(".")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
