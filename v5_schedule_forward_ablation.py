from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from build_v5_context_matchups import assemble_matchup_dataset, enrich_player_history, load_walkforward
from v5_advanced_model import binary_log_loss, brier_score, fit_offset_logistic, predict_offset_logistic
from v5_schedule_context import schedule_coverage_report

OUTDIR = Path("v5_schedule_forward_ablation")
# Schedule court conditions enter the matchup model through these interaction terms.
# Do not look for raw ctx_* columns: assemble_matchup_dataset intentionally converts
# event context into player-vs-player interactions before model fitting.
SCHEDULE_FEATURES = [
    "big_server_x_fast_court",
    "big_server_x_slow_court",
    "big_server_x_altitude",
    "court_speed_x_return_dominance_diff",
    "court_speed_x_serve_dominance_diff",
]


def _metrics(frame: pd.DataFrame, probability_col: str) -> dict:
    y = pd.to_numeric(frame["target_a_win"], errors="coerce").to_numpy(dtype=float)
    p = pd.to_numeric(frame[probability_col], errors="coerce").to_numpy(dtype=float)
    valid = np.isfinite(y) & np.isfinite(p)
    y, p = y[valid], p[valid]
    return {
        "n": int(len(y)),
        "brier": float(brier_score(y, p)),
        "log_loss": float(binary_log_loss(y, p)),
        "accuracy": float(np.mean((p >= 0.5) == (y >= 0.5))) if len(y) else None,
    }


def _fit_predict(train: pd.DataFrame, test: pd.DataFrame, feature_cols: list[str]) -> np.ndarray:
    if not feature_cols:
        raise RuntimeError("Schedule ablation resolved zero incremental matchup features")
    y = pd.to_numeric(train["target_a_win"], errors="coerce").to_numpy(dtype=float)
    base_train = pd.to_numeric(train["baseline_a_probability"], errors="coerce").to_numpy(dtype=float)
    base_test = pd.to_numeric(test["baseline_a_probability"], errors="coerce").to_numpy(dtype=float)
    model = fit_offset_logistic(base_train, train[feature_cols], y, l2=16.0)
    return predict_offset_logistic(model, base_test, test[feature_cols])


def _forward_predictions(frame: pd.DataFrame, feature_cols: list[str], *, fit_increment: bool) -> pd.DataFrame:
    """Expanding-year walk_forward evaluation: every test year uses only earlier years."""
    df = frame.copy()
    df["match_date"] = pd.to_datetime(df["match_date"], errors="coerce")
    df["year"] = df["match_date"].dt.year
    pieces = []
    years = sorted(int(y) for y in df["year"].dropna().unique())
    for test_year in years[1:]:
        train = df[df["year"] < test_year].copy()
        test = df[df["year"] == test_year].copy()
        if train.empty or test.empty:
            continue
        if fit_increment:
            test["ablation_probability"] = _fit_predict(train, test, feature_cols)
        else:
            test["ablation_probability"] = pd.to_numeric(test["baseline_a_probability"], errors="coerce").to_numpy(dtype=float)
        test["prediction_origin"] = "walk_forward"
        test["train_end"] = str(train["match_date"].max())
        pieces.append(test)
    return pd.concat(pieces, ignore_index=True, sort=False) if pieces else pd.DataFrame()


def _schedule_context_columns(frame: pd.DataFrame) -> list[str]:
    cols = [c for c in SCHEDULE_FEATURES if c in frame.columns]
    if not cols:
        raise RuntimeError("No schedule-derived matchup interaction columns found; ablation would be a false no-op")
    return cols


def _pass(player_rows: pd.DataFrame, walkforward: pd.DataFrame, *, schedule_context: bool) -> tuple[pd.DataFrame, dict]:
    enriched = enrich_player_history(player_rows)
    if not schedule_context:
        for col in [c for c in enriched.columns if c.startswith("schedule_")]:
            enriched[col] = np.nan
        if "schedule_altitude_m" in enriched.columns:
            enriched["schedule_altitude_m"] = np.nan
    matchups, qc = assemble_matchup_dataset(enriched, walkforward, target_years=(2025, 2026))
    if matchups.empty:
        raise RuntimeError("No matched warehouse/walk-forward rows available for ablation")
    return matchups, qc


def run(base_dir: str | Path = ".") -> dict:
    base = Path(base_dir)
    player_path = base / "context_warehouse" / "player_match_rows.parquet"
    if not player_path.exists():
        raise FileNotFoundError("context_warehouse/player_match_rows.parquet missing")
    player_rows = pd.read_parquet(player_path)
    walkforward = load_walkforward(base)

    baseline, baseline_qc = _pass(player_rows, walkforward, schedule_context=False)
    enriched, enriched_qc = _pass(player_rows, walkforward, schedule_context=True)
    baseline_match_ids = set(baseline["match_id"].astype(str))
    enriched_match_ids = set(enriched["match_id"].astype(str))
    if baseline_match_ids != enriched_match_ids:
        raise RuntimeError("Two-pass ablation changed the evaluated match universe")

    common_ids = sorted(baseline_match_ids)
    baseline = baseline.set_index("match_id").loc[common_ids].reset_index()
    enriched = enriched.set_index("match_id").loc[common_ids].reset_index()

    baseline_pred = _forward_predictions(baseline, [], fit_increment=False)
    enriched_features = _schedule_context_columns(enriched)
    enriched_pred = _forward_predictions(enriched, enriched_features, fit_increment=True)

    baseline_metrics = _metrics(baseline_pred, "ablation_probability")
    enriched_metrics = _metrics(enriched_pred, "ablation_probability")
    joined = baseline_pred[["match_id", "ablation_probability"]].rename(columns={"ablation_probability": "baseline_probability"}).merge(
        enriched_pred[["match_id", "ablation_probability"]].rename(columns={"ablation_probability": "enriched_probability"}),
        on="match_id", how="inner", validate="one_to_one",
    )
    joined = joined.merge(enriched[[c for c in ["match_id", "match_date", "tour", "surface", "tourney_name", "target_a_win"] if c in enriched.columns]], on="match_id", how="left")
    joined["probability_change"] = joined["enriched_probability"] - joined["baseline_probability"]

    enriched_player_rows = enrich_player_history(player_rows)
    coverage = schedule_coverage_report(enriched_player_rows)
    if "schedule_match_score" in enriched_player_rows.columns:
        resolved = enriched_player_rows[enriched_player_rows.get("schedule_match_method").isin(["exact", "alias", "fuzzy_high"])].copy()
        coverage["mean_schedule_match_score"] = None if resolved.empty else float(pd.to_numeric(resolved["schedule_match_score"], errors="coerce").mean())

    abs_change = joined["probability_change"].abs()
    probability_change = {
        "mean_abs": float(abs_change.mean()),
        "median_abs": float(abs_change.median()),
        "p95_abs": float(abs_change.quantile(0.95)),
        "max_abs": float(abs_change.max()),
        "changed_over_1pp": int((abs_change >= 0.01).sum()),
        "changed_over_3pp": int((abs_change >= 0.03).sum()),
    }
    delta = {
        "brier_improvement": float(baseline_metrics["brier"] - enriched_metrics["brier"]),
        "log_loss_improvement": float(baseline_metrics["log_loss"] - enriched_metrics["log_loss"]),
        "accuracy_delta": float(enriched_metrics["accuracy"] - baseline_metrics["accuracy"]),
    }
    report = {
        "version": "v5-schedule-court-forward-ablation-2",
        "design": "two pass expanding-year walk_forward on identical warehouse match universe",
        "schedule_context_is_enrichment_only": True,
        "warehouse_event_coverage_is_authoritative": True,
        "baseline": baseline_metrics,
        "schedule_enriched": enriched_metrics,
        "delta": delta,
        "probability_change": probability_change,
        "schedule_coverage": coverage,
        "incremental_features": enriched_features,
        "baseline_join_qc": baseline_qc,
        "enriched_join_qc": enriched_qc,
        "evaluated_match_ids": int(len(common_ids)),
    }
    out = base / OUTDIR
    out.mkdir(parents=True, exist_ok=True)
    joined.to_csv(out / "forward_ablation_predictions.csv", index=False)
    (out / "forward_ablation_summary.json").write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(report, indent=2, allow_nan=False))
    return report


if __name__ == "__main__":
    run(".")
