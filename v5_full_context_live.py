from __future__ import annotations

from pathlib import Path
import json
import math

import numpy as np
import pandas as pd

from build_v5_context_matchups import enrich_player_history
from v5_advanced_model import (
    damp_probability_by_uncertainty,
    predict_logit_stack,
    predict_offset_logistic,
    uncertainty_score,
)
from v5_context_model import predict_symmetric_logistic
from v5_matchup_features import build_matchup_features
from v5_player_state import build_player_state


DEFAULT_CANDIDATE_PATH = Path("experiments/acceptance/production_candidate.json")


def load_production_candidate(path: str | Path = DEFAULT_CANDIDATE_PATH) -> dict:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Validated production candidate missing: {p}")
    data = json.loads(p.read_text(encoding="utf-8"))
    if "MEN" not in data or "WTA" not in data or "version" not in data:
        raise ValueError("Invalid full-context production candidate contract")
    return data


def _clip(p: float) -> float:
    return min(max(float(p), 1e-8), 1.0 - 1e-8)


def _logit(p: float) -> float:
    p = _clip(p)
    return math.log(p / (1.0 - p))


def predict_with_production_candidate(
    candidate: dict,
    *,
    tour: str,
    baseline_probability: float,
    signed_features: pd.DataFrame,
) -> dict:
    """Apply only the candidate selected by chronological production acceptance."""
    key = "WTA" if str(tour).upper() == "WTA" else "MEN"
    bundle = candidate[key]
    selected = str(bundle.get("selected_candidate", "accepted_baseline"))
    baseline = np.asarray([_clip(baseline_probability)], dtype=float)
    row = signed_features.copy().reset_index(drop=True)
    context_cols = [c for c in row.columns if c.startswith("ctx_")]

    components: dict[str, float] = {"accepted_baseline": float(baseline[0])}
    if selected != "accepted_baseline" or bundle.get("direct_context_model"):
        direct_model = bundle.get("direct_context_model") or {}
        if direct_model.get("feature_names"):
            direct = predict_symmetric_logistic(direct_model, row)[0]
            components["direct_context"] = float(direct)
        else:
            direct = baseline[0]
    else:
        direct = baseline[0]

    residual_model = bundle.get("residual_model") or {}
    if residual_model.get("feature_names"):
        residual = predict_offset_logistic(residual_model, baseline, row[context_cols])[0]
        components["residual"] = float(residual)
    else:
        residual = baseline[0]

    uncertainty = float(uncertainty_score(row, [residual], [direct])[0])
    gamma = float((bundle.get("uncertainty_model") or {}).get("gamma", 0.0))
    residual_uncertainty = float(damp_probability_by_uncertainty([residual], [uncertainty], gamma=gamma)[0])
    components["residual_uncertainty"] = residual_uncertainty

    stack_model = bundle.get("stack_model") or {}
    weights = stack_model.get("weights") or {}
    if weights:
        stack_inputs = {}
        for name in weights:
            if name == "accepted_baseline":
                stack_inputs[name] = np.asarray([baseline[0]])
            elif name == "direct_context":
                stack_inputs[name] = np.asarray([direct])
            elif name == "residual_uncertainty":
                stack_inputs[name] = np.asarray([residual_uncertainty])
            elif name == "residual":
                stack_inputs[name] = np.asarray([residual])
            else:
                raise ValueError(f"Unknown ensemble component in production candidate: {name}")
        ensemble = float(predict_logit_stack(stack_model, stack_inputs)[0])
        components["ensemble"] = ensemble
    else:
        ensemble = baseline[0]

    selected_probability = {
        "accepted_baseline": float(baseline[0]),
        "direct_context": float(direct),
        "residual": float(residual),
        "residual_uncertainty": residual_uncertainty,
        "ensemble": float(ensemble),
    }.get(selected)
    if selected_probability is None:
        raise ValueError(f"Unsupported selected_candidate: {selected}")

    component_values = np.asarray(list(components.values()), dtype=float)
    return {
        "probability": float(selected_probability),
        "selected_candidate": selected,
        "model_version": str(candidate["version"]),
        "uncertainty_score": uncertainty,
        "component_probability_range": float(component_values.max() - component_values.min()),
        "component_probability_std": float(component_values.std(ddof=0)),
        "component_probabilities": components,
    }


def _target_rows(fixture: dict) -> pd.DataFrame:
    match_id = f"live_{fixture.get('fixture_id') or 'unknown'}"
    start = pd.to_datetime(fixture.get("start_time_utc"), errors="coerce", utc=True)
    common = {
        "match_id": match_id,
        "tour": "WTA" if str(fixture.get("tour") or "").upper() == "WTA" or "women" in str(fixture.get("tournament") or "").lower() else "MEN",
        "match_date": start,
        "tourney_id": fixture.get("tournament_id"),
        "tourney_name": fixture.get("tournament") or "",
        "match_num": np.nan,
        "round": fixture.get("round"),
        "surface": fixture.get("surface"),
        "best_of": fixture.get("best_of", 3),
        "result_file": "LIVE_TARGET",
        "source_quality": "live_pre_match_target",
        "match_games": np.nan,
        "match_sets": np.nan,
        "match_duration_minutes": np.nan,
    }
    blank_stats = {
        "stat_aces": np.nan,
        "stat_double_faults": np.nan,
        "stat_service_points": np.nan,
        "stat_first_serves_in": np.nan,
        "stat_first_serve_points_won": np.nan,
        "stat_second_serve_points_won": np.nan,
        "stat_break_points_saved": np.nan,
        "stat_break_points_faced": np.nan,
        "stat_return_points_total": np.nan,
        "stat_return_points_won": np.nan,
        "stat_break_points_opportunities": np.nan,
        "stat_break_points_converted": np.nan,
    }
    p1, p2 = str(fixture.get("player1") or ""), str(fixture.get("player2") or "")
    return pd.DataFrame([
        {**common, **blank_stats, "player_name": p1, "opponent_name": p2, "player_role": "target", "player_rank": fixture.get("player1_rank"), "opponent_rank": fixture.get("player2_rank")},
        {**common, **blank_stats, "player_name": p2, "opponent_name": p1, "player_role": "target", "player_rank": fixture.get("player2_rank"), "opponent_rank": fixture.get("player1_rank")},
    ])


def build_live_matchup_features(
    historical_player_rows: pd.DataFrame,
    fixture: dict,
    *,
    baseline_probability: float,
    x_sr_p1: float,
    x_elo_p1: float,
    tournament_registry: pd.DataFrame | None = None,
) -> dict:
    """Build a live signed matchup row through the same historical feature builders.

    Outcome-empty target rows are appended after historical rows. Because rolling/workload/
    travel/court-speed builders emit features before ingesting the current row, the target
    fixture cannot leak its own result/statistics into its state.
    """
    target = _target_rows(fixture)
    history = historical_player_rows.copy() if historical_player_rows is not None else pd.DataFrame()
    combined = pd.concat([history, target], ignore_index=True, sort=False)
    enriched = enrich_player_history(combined, tournament_registry=tournament_registry)
    target_id = target.iloc[0]["match_id"]
    live = enriched[enriched["match_id"].astype(str) == str(target_id)].copy()
    if len(live) != 2:
        raise ValueError("Live context builder requires exactly two target player rows")

    p1 = str(fixture.get("player1") or "")
    p2 = str(fixture.get("player2") or "")
    row1 = live[live["player_name"].astype(str) == p1]
    row2 = live[live["player_name"].astype(str) == p2]
    if len(row1) != 1 or len(row2) != 1:
        raise ValueError("Live target players could not be resolved in contextual history")
    state1 = build_player_state(row1.iloc[0])
    state2 = build_player_state(row2.iloc[0])
    state1["player_name"] = p1
    state2["player_name"] = p2

    p1_is_a = p1.casefold() <= p2.casefold()
    state_a, state_b = (state1, state2) if p1_is_a else (state2, state1)
    a_name, b_name = (p1, p2) if p1_is_a else (p2, p1)
    baseline_a = _clip(baseline_probability if p1_is_a else 1.0 - baseline_probability)
    sign = 1.0 if p1_is_a else -1.0
    target_context = row1.iloc[0]

    def pick(*names):
        for name in names:
            if name in target_context.index and pd.notna(target_context.get(name)):
                return target_context.get(name)
        return np.nan

    context = {
        "court_speed": pick("court_speed_blended", "court_speed"),
        "altitude_m": pick("venue_altitude_m", "altitude_m"),
        "weather_temperature_c": pick("weather_temperature_c"),
        "weather_humidity_pct": pick("weather_humidity_pct"),
        "weather_wind_speed_kmh": pick("weather_wind_speed_kmh"),
        "weather_wind_gust_kmh": pick("weather_wind_gust_kmh"),
    }
    output = {
        "player_a": a_name,
        "player_b": b_name,
        "player1_is_a": bool(p1_is_a),
        "baseline_a_probability": baseline_a,
        "x_sr_a": sign * float(x_sr_p1),
        "x_elo_a": sign * float(x_elo_p1),
        "context_quality_a": float(state_a.get("context_quality", 0.0)),
        "context_quality_b": float(state_b.get("context_quality", 0.0)),
        "state_uncertainty_a": float(state_a.get("state_uncertainty", np.nan)),
        "state_uncertainty_b": float(state_b.get("state_uncertainty", np.nan)),
    }
    output.update({f"ctx_{k}": v for k, v in build_matchup_features(state_a, state_b, context).items()})
    return output
