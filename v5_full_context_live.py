from __future__ import annotations

from pathlib import Path
import json

import numpy as np
import pandas as pd

from build_v5_context_matchups import enrich_player_history
from build_v5_weather_cache import attach_weather_cache
from v5_advanced_model import (
    damp_probability_by_uncertainty,
    predict_logit_stack,
    predict_offset_logistic,
    uncertainty_score,
)
from v5_context_model import predict_symmetric_logistic
from v5_court_conditions_source import resolve_court_conditions
from v5_matchup_features import build_matchup_features
from v5_player_state import build_player_state
from v5_weather_features import attach_live_weather


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


def predict_with_production_candidate(candidate: dict, *, tour: str, baseline_probability: float, signed_features: pd.DataFrame) -> dict:
    key = "WTA" if str(tour).upper() == "WTA" else "MEN"
    bundle = candidate[key]
    selected = str(bundle.get("selected_candidate", "accepted_baseline"))
    baseline = np.asarray([_clip(baseline_probability)], dtype=float)
    row = signed_features.copy().reset_index(drop=True)
    context_cols = [c for c in row.columns if c.startswith("ctx_")]
    components: dict[str, float] = {"accepted_baseline": float(baseline[0])}

    direct_model = bundle.get("direct_context_model") or {}
    direct = float(predict_symmetric_logistic(direct_model, row)[0]) if direct_model.get("feature_names") else float(baseline[0])
    if direct_model.get("feature_names"):
        components["direct_context"] = direct

    residual_model = bundle.get("residual_model") or {}
    residual = float(predict_offset_logistic(residual_model, baseline, row[context_cols])[0]) if residual_model.get("feature_names") else float(baseline[0])
    if residual_model.get("feature_names"):
        components["residual"] = residual

    uncertainty = float(uncertainty_score(row, [residual], [direct])[0])
    gamma = float((bundle.get("uncertainty_model") or {}).get("gamma", 0.0))
    residual_uncertainty = float(damp_probability_by_uncertainty([residual], [uncertainty], gamma=gamma)[0])
    components["residual_uncertainty"] = residual_uncertainty

    stack_model = bundle.get("stack_model") or {}
    weights = stack_model.get("weights") or {}
    if weights:
        stack_inputs = {}
        for name in weights:
            if name == "accepted_baseline": stack_inputs[name] = np.asarray([baseline[0]])
            elif name == "direct_context": stack_inputs[name] = np.asarray([direct])
            elif name == "residual_uncertainty": stack_inputs[name] = np.asarray([residual_uncertainty])
            elif name == "residual": stack_inputs[name] = np.asarray([residual])
            else: raise ValueError(f"Unknown ensemble component in production candidate: {name}")
        ensemble = float(predict_logit_stack(stack_model, stack_inputs)[0])
        components["ensemble"] = ensemble
    else:
        ensemble = float(baseline[0])

    selected_probability = {
        "accepted_baseline": float(baseline[0]), "direct_context": direct, "residual": residual,
        "residual_uncertainty": residual_uncertainty, "ensemble": ensemble,
    }.get(selected)
    if selected_probability is None:
        raise ValueError(f"Unsupported selected_candidate: {selected}")
    component_values = np.asarray(list(components.values()), dtype=float)
    return {
        "probability": float(selected_probability), "selected_candidate": selected, "model_version": str(candidate["version"]),
        "uncertainty_score": uncertainty, "component_probability_range": float(component_values.max() - component_values.min()),
        "component_probability_std": float(component_values.std(ddof=0)), "component_probabilities": components,
    }


def _fixture_year(fixture: dict) -> int:
    start_utc = pd.to_datetime(fixture.get("start_time_utc"), errors="coerce", utc=True)
    if pd.notna(start_utc):
        return int(start_utc.year)
    return int(pd.Timestamp.utcnow().year)


def _target_rows(fixture: dict) -> pd.DataFrame:
    match_id = f"live_{fixture.get('fixture_id') or 'unknown'}"
    start_utc = pd.to_datetime(fixture.get("start_time_utc"), errors="coerce", utc=True)
    match_date = start_utc.tz_convert("UTC").tz_localize(None) if pd.notna(start_utc) else pd.NaT
    fixture_surface = str(fixture.get("surface") or "").title().strip()
    fixture_environment = str(fixture.get("environment") or "").title().strip()
    fallback = {}
    if fixture_surface in {"Hard", "Clay", "Grass"}:
        fallback["surface_type"] = fixture_surface
    if fixture_environment in {"Indoor", "Outdoor"}:
        fallback["environment"] = fixture_environment
    for key in ("cpi", "ace_rate_pct", "rally_length", "relative_air_density", "altitude_m", "ball_type", "overall_speed_rating"):
        if fixture.get(key) is not None and not pd.isna(fixture.get(key)):
            fallback[key] = fixture.get(key)
    conditions = resolve_court_conditions(
        fixture.get("tournament") or "",
        _fixture_year(fixture),
        v5_fallback=fallback,
    )

    source_surface = str(conditions.get("surface_type") or "").title().strip()
    surface = source_surface if source_surface in {"Hard", "Clay", "Grass"} else (fixture_surface if fixture_surface in {"Hard", "Clay", "Grass"} else "Hard")
    environment = str(conditions.get("environment") or fixture_environment or "Unknown").title().strip()
    if environment not in {"Indoor", "Outdoor"}:
        environment = "Unknown"
    indoor = True if environment == "Indoor" else (False if environment == "Outdoor" else np.nan)

    common = {
        "match_id": match_id,
        "tour": "WTA" if str(fixture.get("tour") or "").upper() == "WTA" or "women" in str(fixture.get("tournament") or "").lower() else "MEN",
        "match_date": match_date,
        "scheduled_start_utc": None if pd.isna(start_utc) else start_utc.isoformat(),
        "tourney_id": fixture.get("tournament_id"), "tourney_name": fixture.get("tournament") or "", "match_num": np.nan,
        "round": fixture.get("round"), "surface": surface, "best_of": fixture.get("best_of", 3),
        "indoor": indoor, "indoor_outdoor": environment, "environment": environment,
        "court_speed_override": fixture.get("court_speed_override", np.nan),
        "external_cpi": conditions.get("cpi"),
        "external_ace_rate_pct": conditions.get("ace_rate_pct"),
        "external_rally_length": conditions.get("rally_length"),
        "external_relative_air_density": conditions.get("relative_air_density"),
        "external_altitude_m": conditions.get("altitude_m"),
        "external_ball_type": conditions.get("ball_type"),
        "external_overall_speed_rating": conditions.get("overall_speed_rating"),
        "court_conditions_source": "CourtSpeed" if any(conditions.get(x) == "CourtSpeed" for x in ("surface_source", "environment_source", "cpi_source", "ace_rate_source", "rally_source", "rad_source", "altitude_source", "ball_source", "overall_speed_source")) else "V5",
        "court_conditions_source_quality": conditions.get("source_freshness"),
        "court_conditions_target_year": conditions.get("target_year"),
        "court_conditions_refreshed_at": conditions.get("source_refreshed_at"),
        "cpi_source_year": conditions.get("cpi_source_year"),
        "ace_rate_pct_source_year": conditions.get("ace_rate_pct_source_year"),
        "rally_length_source_year": conditions.get("rally_length_source_year"),
        "relative_air_density_source_year": conditions.get("relative_air_density_source_year"),
        "ball_type_source_year": conditions.get("ball_type_source_year"),
        "surface_source": conditions.get("surface_source"),
        "environment_source": conditions.get("environment_source"),
        "cpi_source": conditions.get("cpi_source"),
        "ace_rate_source": conditions.get("ace_rate_source"),
        "rally_source": conditions.get("rally_source"),
        "rad_source": conditions.get("rad_source"),
        "altitude_source": conditions.get("altitude_source"),
        "ball_source": conditions.get("ball_source"),
        "overall_speed_source": conditions.get("overall_speed_source"),
        "result_file": "LIVE_TARGET", "source_quality": "live_pre_match_target", "match_games": np.nan, "match_sets": np.nan,
        "match_duration_minutes": np.nan,
    }
    blank_stats = {
        "stat_aces": np.nan, "stat_double_faults": np.nan, "stat_service_points": np.nan, "stat_first_serves_in": np.nan,
        "stat_first_serve_points_won": np.nan, "stat_second_serve_points_won": np.nan, "stat_break_points_saved": np.nan,
        "stat_break_points_faced": np.nan, "stat_return_points_total": np.nan, "stat_return_points_won": np.nan,
        "stat_break_points_opportunities": np.nan, "stat_break_points_converted": np.nan,
    }
    p1, p2 = str(fixture.get("player1") or ""), str(fixture.get("player2") or "")
    return pd.DataFrame([
        {**common, **blank_stats, "player_name": p1, "opponent_name": p2, "player_role": "target", "player_rank": fixture.get("player1_rank"), "opponent_rank": fixture.get("player2_rank")},
        {**common, **blank_stats, "player_name": p2, "opponent_name": p1, "player_role": "target", "player_rank": fixture.get("player2_rank"), "opponent_rank": fixture.get("player1_rank")},
    ])


def build_live_enriched_history(historical_player_rows: pd.DataFrame, fixtures: list[dict], *, tournament_registry: pd.DataFrame | None = None, weather_cache: pd.DataFrame | None = None, forecast_client=None) -> pd.DataFrame:
    targets = [_target_rows(fixture) for fixture in fixtures]
    target_frame = pd.concat(targets, ignore_index=True, sort=False) if targets else pd.DataFrame()
    history = historical_player_rows.copy() if historical_player_rows is not None else pd.DataFrame()
    combined = pd.concat([history, target_frame], ignore_index=True, sort=False)
    combined["match_date"] = pd.to_datetime(combined["match_date"], errors="coerce", utc=True).dt.tz_localize(None)
    enriched = enrich_player_history(combined, tournament_registry=tournament_registry)
    if weather_cache is not None:
        enriched = attach_weather_cache(enriched, weather_cache)
    enriched = attach_live_weather(enriched, client=forecast_client)
    return enriched


def build_live_matchup_features_from_enriched(enriched_history: pd.DataFrame, fixture: dict, *, baseline_probability: float, x_sr_p1: float, x_elo_p1: float) -> dict:
    target_id = f"live_{fixture.get('fixture_id') or 'unknown'}"
    live = enriched_history[enriched_history["match_id"].astype(str) == target_id].copy()
    if len(live) != 2: raise ValueError("Live context builder requires exactly two target player rows")
    p1, p2 = str(fixture.get("player1") or ""), str(fixture.get("player2") or "")
    row1 = live[live["player_name"].astype(str) == p1]; row2 = live[live["player_name"].astype(str) == p2]
    if len(row1) != 1 or len(row2) != 1: raise ValueError("Live target players could not be resolved in contextual history")
    row1, row2 = row1.iloc[0], row2.iloc[0]
    state1, state2 = build_player_state(row1), build_player_state(row2); state1["player_name"] = p1; state2["player_name"] = p2
    p1_is_a = p1.casefold() <= p2.casefold(); state_a, state_b = (state1, state2) if p1_is_a else (state2, state1)
    a_name, b_name = (p1, p2) if p1_is_a else (p2, p1); baseline_a = _clip(baseline_probability if p1_is_a else 1.0 - baseline_probability); sign = 1.0 if p1_is_a else -1.0
    target_context = row1
    def pick(*names):
        for name in names:
            if name in target_context.index and pd.notna(target_context.get(name)): return target_context.get(name)
        return np.nan

    environment = str(pick("environment", "indoor_outdoor") or "Unknown").title()
    indoor = environment == "Indoor"
    context = {
        "court_speed": pick("court_speed_override", "court_speed_blended", "court_speed"),
        "altitude_m": pick("external_altitude_m", "venue_altitude_m", "altitude_m"),
        "weather_temperature_c": np.nan if indoor else pick("weather_temperature_c"),
        "weather_humidity_pct": np.nan if indoor else pick("weather_humidity_pct"),
        "weather_wind_speed_kmh": np.nan if indoor else pick("weather_wind_speed_kmh"),
        "weather_wind_gust_kmh": np.nan if indoor else pick("weather_wind_gust_kmh"),
    }
    output = {
        "player_a": a_name, "player_b": b_name, "player1_is_a": bool(p1_is_a), "baseline_a_probability": baseline_a,
        "x_sr_a": sign * float(x_sr_p1), "x_elo_a": sign * float(x_elo_p1), "context_quality_a": float(state_a.get("context_quality", 0.0)),
        "context_quality_b": float(state_b.get("context_quality", 0.0)), "state_uncertainty_a": float(state_a.get("state_uncertainty", np.nan)),
        "state_uncertainty_b": float(state_b.get("state_uncertainty", np.nan)),
        "environment": environment,
        "weather_source_quality": "not_applicable_indoor" if indoor else str(target_context.get("weather_source_quality") or "missing"),
        "weather_forecast_hour": "" if indoor else str(target_context.get("weather_forecast_hour") or ""),
        "court_speed_source_quality": "user_override" if pd.notna(pick("court_speed_override")) else str(target_context.get("court_speed_source_quality") or target_context.get("court_speed_prior_level") or "missing"),
        "court_conditions_source": target_context.get("court_conditions_source"),
        "court_conditions_source_quality": target_context.get("court_conditions_source_quality"),
        "external_cpi": pick("external_cpi"),
        "external_ace_rate_pct": pick("external_ace_rate_pct"),
        "external_rally_length": pick("external_rally_length"),
        "external_relative_air_density": pick("external_relative_air_density"),
        "external_altitude_m": pick("external_altitude_m"),
        "external_ball_type": target_context.get("external_ball_type"),
        "external_overall_speed_rating": target_context.get("external_overall_speed_rating"),
        "effective_court_speed": context["court_speed"],
    }
    output.update({f"ctx_{k}": v for k, v in build_matchup_features(state_a, state_b, context).items()})
    return output


def build_live_matchup_features(historical_player_rows: pd.DataFrame, fixture: dict, *, baseline_probability: float, x_sr_p1: float, x_elo_p1: float, tournament_registry: pd.DataFrame | None = None, weather_cache: pd.DataFrame | None = None, forecast_client=None) -> dict:
    enriched = build_live_enriched_history(historical_player_rows, [fixture], tournament_registry=tournament_registry, weather_cache=weather_cache, forecast_client=forecast_client)
    return build_live_matchup_features_from_enriched(enriched, fixture, baseline_probability=baseline_probability, x_sr_p1=x_sr_p1, x_elo_p1=x_elo_p1)
