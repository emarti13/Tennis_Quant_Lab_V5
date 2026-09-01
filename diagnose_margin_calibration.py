from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from historical_score_calibration import build_result_index, load_historical_results, matched_walkforward_scores
from v5_core import logistic, logit, simulate_match
from v5_daily_batch import infer_best_of
from v5_model_calibration import calibrated_match_probability
from v5_strength_conditioning import condition_serve_pair_to_match_probability

OUT = Path("v5_daily_ready/margin_calibration_diagnostic.json")
MULTIPLIERS = [0.75, 1.0, 1.25, 1.5, 1.75, 2.0]
SEARCH_SIMS = 120
SEARCH_ITERATIONS = 7
FINAL_SIMS = 180


def _load_walkforward(tour):
    path = Path("v5_wta_walkforward.csv" if tour == "WTA" else "v5_men_walkforward.csv")
    df = pd.read_csv(path, low_memory=False)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    return df[df["date"].dt.year.isin([2025, 2026])].copy()


def _segment(row, tour):
    best_of = infer_best_of(row.get("tournament"), tour)
    return "MEN_BO5" if tour == "MEN" and best_of == 5 else ("MEN_BO3" if tour == "MEN" else "WTA_BO3")


def _sample(frame, n, seed):
    if len(frame) <= n:
        return frame.sort_values("date").reset_index(drop=True)
    return frame.sample(n=n, random_state=seed).sort_values("date").reset_index(drop=True)


def _conditioned_base(row, tour, seed):
    target = calibrated_match_probability(
        row["winner_serve_p"], row["loser_serve_p"], row["elo_winner_p"], tour
    )
    best_of = infer_best_of(row.get("tournament"), tour)
    p1, p2, meta = condition_serve_pair_to_match_probability(
        row["winner_serve_p"], row["loser_serve_p"], target,
        best_of=best_of, n=SEARCH_SIMS, seed=seed, max_iter=SEARCH_ITERATIONS,
    )
    return p1, p2, target, best_of, meta


def _score_pair(p1, p2, multiplier):
    e1 = logit(p1); e2 = logit(p2)
    mean = (e1 + e2) / 2.0
    diff = (e1 - e2) * float(multiplier)
    return logistic(mean + diff / 2.0), logistic(mean - diff / 2.0)


def _prepare(frame, tour, seed_base):
    rows = []
    for i, (_, row) in enumerate(frame.iterrows()):
        p1, p2, target, best_of, meta = _conditioned_base(row, tour, seed_base + i)
        rows.append({
            **row.to_dict(),
            "conditioned_p1": p1,
            "conditioned_p2": p2,
            "target_probability": target,
            "best_of": best_of,
            "conditioning_achieved": meta["achieved_probability"],
        })
    return pd.DataFrame(rows)


def _evaluate(prepared, multiplier, seed_base):
    actual = []
    predicted = []
    target_errors = []
    for i, (_, row) in enumerate(prepared.iterrows()):
        p1, p2 = _score_pair(row["conditioned_p1"], row["conditioned_p2"], multiplier)
        result = simulate_match(
            p1, p2, best_of=int(row["best_of"]), n=FINAL_SIMS, seed=seed_base + i,
            state_variation=False, target_pA_win=float(row["target_probability"]),
            spread_lines=[], total_lines=[],
        )
        actual.append(float(row["actual_margin"]))
        predicted.append(float(result["expected_margin"]))
        target_errors.append(abs(float(result["raw_pA_win"]) - float(row["target_probability"])))
    a = np.asarray(actual); p = np.asarray(predicted); err = p - a
    corr = float(np.corrcoef(a, p)[0, 1]) if len(a) > 2 and np.std(a) > 0 and np.std(p) > 0 else None
    return {
        "n": int(len(a)),
        "mean_actual_margin": float(a.mean()) if len(a) else None,
        "mean_predicted_margin": float(p.mean()) if len(p) else None,
        "mean_error_games": float(err.mean()) if len(err) else None,
        "mae_games": float(np.abs(err).mean()) if len(err) else None,
        "rmse_games": float(np.sqrt(np.mean(err ** 2))) if len(err) else None,
        "correlation": corr,
        "mean_raw_probability_miss_pp_before_final_weight": float(np.mean(target_errors) * 100) if target_errors else None,
    }


def main():
    results, loaded, missing = load_historical_results((2025, 2026))
    lookup = build_result_index(results)
    payload = {
        "method": {
            "fit_year": 2025,
            "validation_year": 2026,
            "market_prices_used": False,
            "parameter": "multiplier on relative serve-logit difference after independent match-probability conditioning",
            "property": "mean serve environment held fixed; final win probability restored to independent calibrated target",
            "multipliers": MULTIPLIERS,
            "search_simulations": SEARCH_SIMS,
            "final_simulations": FINAL_SIMS,
        },
        "score_files_loaded": loaded,
        "score_files_missing": missing,
        "segments": {},
    }

    segment_frames = {}
    for tour in ("MEN", "WTA"):
        matched = matched_walkforward_scores(_load_walkforward(tour), lookup)
        if matched.empty:
            continue
        matched["segment"] = matched.apply(lambda row: _segment(row, tour), axis=1)
        matched["tour"] = tour
        for segment, group in matched.groupby("segment"):
            segment_frames[segment] = group.copy()

    limits = {"MEN_BO3": 650, "MEN_BO5": 300, "WTA_BO3": 450}
    for segment, frame in segment_frames.items():
        tour = "WTA" if segment.startswith("WTA") else "MEN"
        train = _sample(frame[frame["date"].dt.year == 2025], limits.get(segment, 400), 2025)
        valid = _sample(frame[frame["date"].dt.year == 2026], limits.get(segment, 400), 2026)
        prepared_train = _prepare(train, tour, 100000)
        prepared_valid = _prepare(valid, tour, 700000)
        train_metrics = {
            str(mult): _evaluate(prepared_train, mult, 200000 + j * 10000)
            for j, mult in enumerate(MULTIPLIERS)
        }
        eligible = [(float(k), v) for k, v in train_metrics.items() if v["rmse_games"] is not None]
        if not eligible:
            payload["segments"][segment] = {"error": "no evaluable training rows"}
            continue
        selected = min(eligible, key=lambda item: item[1]["rmse_games"])[0]
        validation_selected = _evaluate(prepared_valid, selected, 800000)
        validation_baseline = _evaluate(prepared_valid, 1.0, 900000)
        payload["segments"][segment] = {
            "available_2025": int((frame["date"].dt.year == 2025).sum()),
            "available_2026": int((frame["date"].dt.year == 2026).sum()),
            "sample_2025": int(len(train)),
            "sample_2026": int(len(valid)),
            "train_candidates": train_metrics,
            "selected_multiplier_from_2025": selected,
            "validation_2026_selected": validation_selected,
            "validation_2026_baseline_1_0": validation_baseline,
            "validation_rmse_improvement_games": (
                validation_baseline["rmse_games"] - validation_selected["rmse_games"]
                if validation_baseline["rmse_games"] is not None and validation_selected["rmse_games"] is not None else None
            ),
        }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(json.dumps(payload, indent=2, default=str))


if __name__ == "__main__":
    main()
