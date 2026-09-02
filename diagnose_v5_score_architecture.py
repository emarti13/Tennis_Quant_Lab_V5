from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from historical_score_calibration import build_result_index, load_historical_results, matched_walkforward_scores
from v5_core import logistic, logit, simulate_match
from v5_daily_batch import infer_best_of
from v5_model_calibration import calibrated_match_probability
from v5_score_architecture import actual_score_decomposition, score_decomposition
from v5_strength_conditioning import condition_serve_pair_to_match_probability

OUT = Path("v5_score_diagnostic/report.json")
OFFSETS = [-0.60, -0.45, -0.30, -0.15, 0.0, 0.15]
DOMINANCE = [0.50, 0.75, 1.00, 1.25, 1.50, 1.75, 2.00, 2.50]
SEARCH_SIMS = 100
FINAL_SIMS = 160
LIMITS = {"MEN_BO3": 420, "MEN_BO5": 260, "WTA_BO3": 360}
SPREAD_LINES = [x + 0.5 for x in range(-13, 13)]
TOTAL_LINES_BO3 = [x + 0.5 for x in range(14, 36)]
TOTAL_LINES_BO5 = [x + 0.5 for x in range(24, 58)]


def _load_walkforward(tour):
    path = Path("v5_wta_walkforward.csv" if tour == "WTA" else "v5_men_walkforward.csv")
    df = pd.read_csv(path, low_memory=False)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    return df[df["date"].dt.year.isin([2025, 2026])].copy()


def _segment(row, tour):
    best_of = infer_best_of(row.get("tournament"), tour)
    return "MEN_BO5" if tour == "MEN" and best_of == 5 else ("MEN_BO3" if tour == "MEN" else "WTA_BO3")


def _sample(frame, year, seed, limit):
    x = frame[frame["date"].dt.year == int(year)].copy()
    if len(x) <= limit:
        return x.sort_values("date").reset_index(drop=True)
    return x.sample(n=limit, random_state=seed).sort_values("date").reset_index(drop=True)


def _prepare(frame, tour, seed_base):
    rows = []
    for i, (_, row) in enumerate(frame.iterrows()):
        target = calibrated_match_probability(row["a_serve_p"], row["b_serve_p"], row["elo_a_p"], tour)
        best_of = infer_best_of(row.get("tournament"), tour)
        p1, p2, meta = condition_serve_pair_to_match_probability(
            row["a_serve_p"], row["b_serve_p"], target,
            best_of=best_of, n=SEARCH_SIMS, seed=seed_base + i, max_iter=7,
        )
        actual_d = actual_score_decomposition(row.get("score"), row.get("actual_total"))
        rows.append({
            **row.to_dict(),
            "conditioned_a_serve": p1,
            "conditioned_b_serve": p2,
            "target_probability_a": target,
            "best_of": best_of,
            "conditioning_achieved": meta["achieved_probability"],
            **actual_d,
        })
    return pd.DataFrame(rows)


def _candidate_pair(p1, p2, offset, dominance):
    a = logit(p1); b = logit(p2)
    mean = (a + b) / 2.0 + float(offset)
    diff = (a - b) * float(dominance)
    return logistic(mean + diff / 2.0), logistic(mean - diff / 2.0)


def _float_map(mapping):
    return {float(k): float(v) for k, v in mapping.items()}


def _evaluate(prepared, offset, dominance, seed_base):
    margin_brier = []
    total_brier = []
    margin_err = []
    total_err = []
    sets_err = []
    gps_err = []
    predicted_sets = []
    actual_sets = []
    predicted_gps = []
    actual_gps = []
    p_miss = []
    for i, (_, row) in enumerate(prepared.iterrows()):
        pa, pb = _candidate_pair(row["conditioned_a_serve"], row["conditioned_b_serve"], offset, dominance)
        total_lines = TOTAL_LINES_BO5 if int(row["best_of"]) == 5 else TOTAL_LINES_BO3
        sim = simulate_match(
            pa, pb, best_of=int(row["best_of"]), n=FINAL_SIMS, seed=seed_base + i,
            state_variation=False, target_pA_win=float(row["target_probability_a"]),
            spread_lines=SPREAD_LINES, total_lines=total_lines,
        )
        spreads = _float_map(sim["spread"])
        overs = _float_map(sim["over"])
        actual_margin = float(row["actual_margin_a"])
        actual_total = float(row["actual_total"])
        for line in SPREAD_LINES:
            margin_brier.append((spreads[line] - float(actual_margin + line > 0)) ** 2)
        for line in total_lines:
            total_brier.append((overs[line] - float(actual_total > line)) ** 2)
        margin_err.append(float(sim["expected_margin"]) - actual_margin)
        total_err.append(float(sim["expected_total"]) - actual_total)
        d = score_decomposition(sim)
        if row.get("actual_sets") is not None and d["expected_sets"] is not None:
            ae = float(row["actual_sets"])
            pe = float(d["expected_sets"])
            sets_err.append(pe - ae)
            actual_sets.append(ae); predicted_sets.append(pe)
        if row.get("actual_games_per_set") is not None and d["expected_games_per_set"] is not None:
            ag = float(row["actual_games_per_set"])
            pg = float(d["expected_games_per_set"])
            gps_err.append(pg - ag)
            actual_gps.append(ag); predicted_gps.append(pg)
        p_miss.append(abs(float(sim["raw_pA_win"]) - float(row["target_probability_a"])))

    me = np.asarray(margin_err, dtype=float)
    te = np.asarray(total_err, dtype=float)
    se = np.asarray(sets_err, dtype=float)
    ge = np.asarray(gps_err, dtype=float)
    mb = float(np.mean(margin_brier)) if margin_brier else None
    tb = float(np.mean(total_brier)) if total_brier else None
    return {
        "n": int(len(prepared)),
        "margin_cdf_brier": mb,
        "total_cdf_brier": tb,
        "joint_cdf_brier": None if mb is None or tb is None else float((mb + tb) / 2.0),
        "margin_mean_error_games": None if not len(me) else float(me.mean()),
        "margin_mae_games": None if not len(me) else float(np.abs(me).mean()),
        "margin_rmse_games": None if not len(me) else float(np.sqrt(np.mean(me ** 2))),
        "total_mean_error_games": None if not len(te) else float(te.mean()),
        "total_mae_games": None if not len(te) else float(np.abs(te).mean()),
        "total_rmse_games": None if not len(te) else float(np.sqrt(np.mean(te ** 2))),
        "sets_mean_error": None if not len(se) else float(se.mean()),
        "sets_mae": None if not len(se) else float(np.abs(se).mean()),
        "games_per_set_mean_error": None if not len(ge) else float(ge.mean()),
        "games_per_set_mae": None if not len(ge) else float(np.abs(ge).mean()),
        "mean_actual_sets": None if not actual_sets else float(np.mean(actual_sets)),
        "mean_predicted_sets": None if not predicted_sets else float(np.mean(predicted_sets)),
        "mean_actual_games_per_set": None if not actual_gps else float(np.mean(actual_gps)),
        "mean_predicted_games_per_set": None if not predicted_gps else float(np.mean(predicted_gps)),
        "mean_raw_probability_miss_pp": None if not p_miss else float(np.mean(p_miss) * 100.0),
    }


def _production_gate(segment, selected, baseline, boundary_hit):
    joint_gain = float(baseline["joint_cdf_brier"] - selected["joint_cdf_brier"])
    margin_bias = abs(float(selected["margin_mean_error_games"]))
    total_bias = abs(float(selected["total_mean_error_games"]))
    total_limit = 2.5 if segment == "MEN_BO5" else 1.5
    accepted = joint_gain > 0 and margin_bias <= 1.0 and total_bias <= total_limit and not boundary_hit
    return {
        "accepted": bool(accepted),
        "joint_cdf_brier_improvement": joint_gain,
        "absolute_margin_bias_games": margin_bias,
        "absolute_total_bias_games": total_bias,
        "total_bias_limit_games": total_limit,
        "selected_parameter_on_search_boundary": bool(boundary_hit),
    }


def run():
    results, loaded, missing = load_historical_results((2025, 2026))
    lookup = build_result_index(results)
    segments = {}
    for tour in ("MEN", "WTA"):
        matched = matched_walkforward_scores(_load_walkforward(tour), lookup)
        if matched.empty:
            continue
        matched["segment"] = matched.apply(lambda row: _segment(row, tour), axis=1)
        for segment, group in matched.groupby("segment"):
            segments[segment] = (tour, group.copy())

    payload = {
        "version": "v5-score-architecture-oriented-1",
        "method": {
            "fit_year": 2025,
            "validation_year": 2026,
            "market_prices_used": False,
            "margin_orientation": "deterministic alphabetical player A/B; actual margin signed A minus B",
            "bug_repaired": "winner-oriented positive actual margin was previously compared with unconditional A-minus-B model margin",
            "offsets": OFFSETS,
            "dominance": DOMINANCE,
            "final_simulations": FINAL_SIMS,
        },
        "score_files_loaded": loaded,
        "score_files_missing": missing,
        "segments": {},
    }

    for segment, (tour, frame) in segments.items():
        limit = LIMITS[segment]
        train = _prepare(_sample(frame, 2025, 2025, limit), tour, 100000)
        valid = _prepare(_sample(frame, 2026, 2026, limit), tour, 700000)
        candidates = {}
        for oi, offset in enumerate(OFFSETS):
            for di, dom in enumerate(DOMINANCE):
                key = f"offset={offset:+.2f}|dominance={dom:.2f}"
                candidates[key] = _evaluate(train, offset, dom, 200000 + oi * 10000 + di * 500)
        selected_key, train_selected = min(
            ((k, v) for k, v in candidates.items() if v["joint_cdf_brier"] is not None),
            key=lambda item: item[1]["joint_cdf_brier"],
        )
        pieces = dict(x.split("=") for x in selected_key.split("|"))
        offset = float(pieces["offset"]); dom = float(pieces["dominance"])
        selected = _evaluate(valid, offset, dom, 800000)
        baseline = _evaluate(valid, 0.0, 1.0, 900000)
        boundary = offset in {min(OFFSETS), max(OFFSETS)} or dom in {min(DOMINANCE), max(DOMINANCE)}
        payload["segments"][segment] = {
            "available_2025": int((frame["date"].dt.year == 2025).sum()),
            "available_2026": int((frame["date"].dt.year == 2026).sum()),
            "sample_2025": int(len(train)),
            "sample_2026": int(len(valid)),
            "selected_from_2025": {"offset": offset, "dominance": dom, "training_metrics": train_selected},
            "validation_2026_selected": selected,
            "validation_2026_baseline": baseline,
            "production_gate": _production_gate(segment, selected, baseline, boundary),
            "candidate_scores_2025": candidates,
        }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(payload, indent=2, allow_nan=False))
    return payload


if __name__ == "__main__":
    run()
