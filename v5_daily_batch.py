"""Automated V5 full-context daily board and frozen prediction ledger."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import math
import re

import numpy as np
import pandas as pd

from build_v5_weather_cache import load_weather_cache
from v5_full_context_live import (
    build_live_enriched_history,
    build_live_matchup_features_from_enriched,
    load_production_candidate,
    predict_with_production_candidate,
)
from v5_live_market import canonical_name, add_model_pricing, signal_row
from v5_model_calibration import calibrated_match_probability, calibration_record
from v5_court_conditions_source import resolve_court_conditions
from v5_score_distribution import predict_score_distribution


BASE = Path(__file__).resolve().parent
MARKET_PATH = BASE / "v5_market_ready" / "market_board_input.csv"
OUTDIR = BASE / "v5_daily_ready"
LATEST_BOARD_PATH = OUTDIR / "latest_board.csv"
LATEST_SUMMARY_PATH = OUTDIR / "latest_summary.json"
FROZEN_LEDGER_PATH = OUTDIR / "frozen_predictions.csv"
CONTEXT_HISTORY_PATH = BASE / "context_warehouse" / "player_match_rows.parquet"
TOURNAMENT_REGISTRY_PATH = BASE / "context_registry" / "tournaments.csv"
PRODUCTION_CANDIDATE_PATH = BASE / "experiments" / "acceptance" / "production_candidate.json"
SCORE_PRODUCTION_CANDIDATE_PATH = BASE / "experiments" / "acceptance" / "score_production_candidate.json"

SIGNAL_ORDER = {"BET": 0, "LEAN": 1, "REVIEW": 2, "PASS": 3, "N/A": 4, "NO PRICE": 5}


def _line_token(value):
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return ""
    try:
        return f"{float(value):g}"
    except Exception:
        return str(value).strip().lower()


def freeze_key(row):
    fixture = str(row.get("fixture_id", "")).strip()
    group = str(row.get("market_group", "")).strip().lower()
    selection = canonical_name(row.get("selection"))
    line = _line_token(row.get("line"))
    return "|".join((fixture, group, selection, line))


def eligible_pre_match(feed, now=None):
    if feed.empty or "start_time_utc" not in feed.columns:
        return feed.iloc[0:0].copy()
    now = now or datetime.now(timezone.utc)
    now_ts = pd.Timestamp(now)
    if now_ts.tzinfo is None:
        now_ts = now_ts.tz_localize("UTC")
    else:
        now_ts = now_ts.tz_convert("UTC")
    starts = pd.to_datetime(feed["start_time_utc"], errors="coerce", utc=True)
    return feed.loc[starts.notna() & (starts > now_ts)].copy()


def merge_frozen(existing, fresh):
    if existing is None or existing.empty:
        return fresh.copy().reset_index(drop=True)
    if fresh is None or fresh.empty:
        return existing.copy().reset_index(drop=True)
    existing = existing.copy()
    fresh = fresh.copy()
    if "freeze_key" not in existing.columns:
        existing["freeze_key"] = existing.apply(freeze_key, axis=1)
    if "freeze_key" not in fresh.columns:
        fresh["freeze_key"] = fresh.apply(freeze_key, axis=1)
    seen = set(existing["freeze_key"].astype(str))
    add = fresh.loc[~fresh["freeze_key"].astype(str).isin(seen)].copy()
    return pd.concat([existing, add], ignore_index=True, sort=False)


def rank_board(board):
    if board is None or board.empty:
        return pd.DataFrame() if board is None else board.copy()
    out = board.copy()
    out["_signal_rank"] = out.get("signal", pd.Series(index=out.index, dtype=object)).map(SIGNAL_ORDER).fillna(9)
    out["_ev_rank"] = pd.to_numeric(out.get("expected_value"), errors="coerce").fillna(-999.0)
    out = out.sort_values(["_signal_rank", "_ev_rank"], ascending=[True, False], kind="stable")
    return out.drop(columns=["_signal_rank", "_ev_rank"]).reset_index(drop=True)


def infer_surface(tournament):
    t = str(tournament or "").lower()
    grass = ("wimbledon", "queen", "halle", "eastbourne", "nottingham", "s-hertogenbosch", "hertogenbosch", "newport")
    clay = ("roland garros", "french open", "rome", "madrid", "monte carlo", "barcelona", "munich", "hamburg", "bastad", "gstaad", "kitzbuhel", "bucharest", "marrakech", "geneva", "estoril", "rio", "buenos aires", "santiago", "augsburg", "como", "plovdiv")
    hard = ("us open", "australian open", "cincinnati", "canada", "montreal", "toronto", "indian wells", "miami", "washington", "atlanta", "acapulco", "delray beach", "doha", "dubai", "beijing", "tokyo", "shanghai", "vienna", "paris masters", "basel", "manacor", "mallorca", "porto", "zhangjiagang")

    def has_term(term):
        return re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", t) is not None

    if any(has_term(x) for x in grass):
        return "Grass", "Auto — tournament map"
    if any(has_term(x) for x in clay):
        return "Clay", "Auto — tournament map"
    if any(has_term(x) for x in hard):
        return "Hard", "Auto — tournament map"
    return "Hard", "Auto default — review"


def _event_surface_key(value):
    tokens = canonical_name(value).split()
    generic = {"atp", "wta", "men", "women", "singles", "challenger", "qualification", "qualifying", "qualifier"}
    return " ".join(token for token in tokens if token not in generic)


def _historical_event_surface(tournament, start_time_utc=None, context_history=None):
    if context_history is None or context_history.empty or "surface" not in context_history.columns:
        return None
    name_col = next((c for c in ("tourney_name", "tournament", "event_name") if c in context_history.columns), None)
    if name_col is None:
        return None

    target = _event_surface_key(tournament)
    if not target:
        return None
    names = context_history[name_col].fillna("").astype(str).map(_event_surface_key)
    exact = names.eq(target)
    if not exact.any():
        # Provider titles often add tour/country/category decorations. Allow only
        # a reasonably specific containment match; short generic event names stay fail-closed.
        exact = names.map(lambda value: bool(value) and min(len(value), len(target)) >= 7 and (value in target or target in value))
    history = context_history.loc[exact].copy()
    if history.empty:
        return None

    if start_time_utc is not None and "match_date" in history.columns:
        cutoff = pd.to_datetime(start_time_utc, errors="coerce", utc=True)
        dates = pd.to_datetime(history["match_date"], errors="coerce", utc=True)
        if pd.notna(cutoff):
            history = history.loc[dates.notna() & (dates < cutoff)].copy()
    if history.empty:
        return None

    surfaces = history["surface"].dropna().astype(str).str.title()
    surfaces = surfaces[surfaces.isin({"Hard", "Clay", "Grass"})]
    if surfaces.empty or surfaces.nunique() != 1:
        return None
    return str(surfaces.iloc[0])


def resolve_fixture_surface(tournament, *, start_time_utc=None, context_history=None):
    mapped_surface, mapped_source = infer_surface(tournament)
    historical_surface = _historical_event_surface(tournament, start_time_utc, context_history)
    fallback_surface = historical_surface
    if fallback_surface is None and mapped_source != "Auto default — review":
        fallback_surface = mapped_surface

    start = pd.to_datetime(start_time_utc, errors="coerce", utc=True)
    year = int(start.year) if pd.notna(start) else int(pd.Timestamp.now(tz="UTC").year)
    fallback = {"surface_type": fallback_surface} if fallback_surface is not None else {}
    try:
        resolved = resolve_court_conditions(tournament, year, v5_fallback=fallback)
    except Exception:
        resolved = {}
    surface = str(resolved.get("surface_type") or "").title()
    source = str(resolved.get("surface_source") or "")
    if surface in {"Hard", "Clay", "Grass"}:
        if source == "CourtSpeed":
            return surface, "CourtSpeed canonical conditions"
        if source == "V5" and historical_surface is not None:
            return surface, "V5 historical event surface"
        if source == "V5" and mapped_source != "Auto default — review":
            return surface, mapped_source

    if historical_surface is not None:
        return historical_surface, "V5 historical event surface"
    return mapped_surface, mapped_source


def infer_best_of(tournament, tour):
    """Men's Grand Slam main draws are Bo5; qualifying and all WTA are Bo3."""
    t = str(tournament or "").lower()
    category = str(tour or "").lower()
    is_men = category in {"men", "atp"} or "men" in category
    is_slam = any(name in t for name in ("australian open", "french open", "roland garros", "wimbledon", "us open"))
    is_qualifying = any(term in t for term in ("qualifying", "qualification", "qualifier"))
    return 5 if is_men and is_slam and not is_qualifying else 3


def _tour_to_v5(category, tournament):
    text = f"{category or ''} {tournament or ''}".lower()
    return "WTA" if "wta" in text or "women" in text else "MEN"


def _player_lookup(ratings):
    return {canonical_name(x): x for x in ratings["player"].dropna().unique()}


def _resolve_player(name, lookup):
    target = canonical_name(name)
    if not target:
        return None
    exact = lookup.get(target)
    if exact is not None:
        return exact
    target_tokens = target.split()
    target_set = set(target_tokens)
    subset = []
    for key, actual in lookup.items():
        key_set = set(key.split())
        if target_set.issubset(key_set) or key_set.issubset(target_set):
            subset.append(actual)
    if len(set(subset)) == 1:
        return subset[0]
    if len(target_tokens) >= 2:
        first, surname = target_tokens[0], target_tokens[-1]
        ends = []
        for key, actual in lookup.items():
            toks = key.split()
            if len(toks) >= 2 and toks[0] == first and toks[-1] == surname:
                ends.append(actual)
        if len(set(ends)) == 1:
            return ends[0]
    return None


def _base_probs_from_ratings(df, p1, p2, surface, baseline):
    from v5_core import logistic, logit

    a = df[(df.player == p1) & (df.surface == surface)]
    b = df[(df.player == p2) & (df.surface == surface)]
    if a.empty or b.empty:
        raise ValueError("Player/surface not found in V5 ratings.")
    a = a.iloc[-1]
    b = b.iloc[-1]
    wa = min(1.0, (float(a.surface_points) + float(b.surface_points)) / 700.0)
    eta_a = logit(baseline[surface]) + float(a.serve_global) - float(b.return_global) + 0.55 * wa * (float(a.serve_surface) - float(b.return_surface))
    eta_b = logit(baseline[surface]) + float(b.serve_global) - float(a.return_global) + 0.55 * wa * (float(b.serve_surface) - float(a.return_surface))
    return logistic(eta_a), logistic(eta_b), a, b


def _logit_probability(p):
    p = min(max(float(p), 1e-8), 1.0 - 1e-8)
    return math.log(p / (1.0 - p))


def _confidence_for_market(row, p1, p2, p1_conf, p2_conf):
    if str(row.get("market_group", "")) == "total_games":
        return min(p1_conf, p2_conf)
    sel = canonical_name(row.get("selection"))
    if sel == canonical_name(p1):
        return p1_conf
    if sel == canonical_name(p2):
        return p2_conf
    return min(p1_conf, p2_conf)


def _requested_market_lines(fixture_rows, market_group):
    if "market_group" not in fixture_rows.columns or "line" not in fixture_rows.columns:
        return []
    values = pd.to_numeric(
        fixture_rows.loc[fixture_rows["market_group"] == market_group, "line"],
        errors="coerce",
    ).dropna()
    return sorted({float(x) for x in values})


def _prepare_fixture(fixture_rows, ratings_by_tour, summary, context_history=None):
    first = fixture_rows.iloc[0]
    tournament = first.get("tournament")
    tour = _tour_to_v5(first.get("tour"), tournament)
    ratings = ratings_by_tour[tour]
    surface, surface_source = resolve_fixture_surface(
        tournament,
        start_time_utc=first.get("start_time_utc"),
        context_history=context_history,
    )
    best_of = infer_best_of(tournament, tour)
    lookup = _player_lookup(ratings)
    p1 = _resolve_player(first.get("player1"), lookup)
    p2 = _resolve_player(first.get("player2"), lookup)
    if p1 is None or p2 is None:
        missing = []
        if p1 is None:
            missing.append(str(first.get("player1")))
        if p2 is None:
            missing.append(str(first.get("player2")))
        raise ValueError("Unmatched V5 player(s): " + ", ".join(missing))
    if p1 == p2:
        raise ValueError("Players resolved to the same V5 identity.")

    baseline = summary.get(tour, {}).get("baseline", {"Hard": 0.62, "Clay": 0.60, "Grass": 0.65})
    p1_serve, p2_serve, a, b = _base_probs_from_ratings(ratings, p1, p2, surface, baseline)
    elo_a = 0.35 * float(a.elo) + 0.65 * float(a.surface_elo)
    elo_b = 0.35 * float(b.elo) + 0.65 * float(b.surface_elo)
    p_elo = 1 / (1 + 10 ** ((elo_b - elo_a) / 400))
    calibrated_p = calibrated_match_probability(p1_serve, p2_serve, p_elo, tour)
    return {
        "first": first,
        "tournament": tournament,
        "tour": tour,
        "surface": surface,
        "surface_source": surface_source,
        "best_of": best_of,
        "p1": p1,
        "p2": p2,
        "p1_serve": p1_serve,
        "p2_serve": p2_serve,
        "rating_p1": a,
        "rating_p2": b,
        "p_elo": p_elo,
        "baseline_probability_p1": calibrated_p,
        "calibration": calibration_record(tour),
        "x_sr_p1": _logit_probability(p1_serve) - _logit_probability(p2_serve),
        "x_elo_p1": _logit_probability(p_elo),
    }


def _context_fixture(prepared):
    first = prepared["first"]
    return {
        "fixture_id": first.get("fixture_id"),
        "start_time_utc": first.get("start_time_utc"),
        "tournament_id": first.get("tournament_id"),
        "tournament": prepared["tournament"],
        "tour": prepared["tour"],
        "surface": prepared["surface"],
        "best_of": prepared["best_of"],
        "round": first.get("round"),
        "player1": prepared["p1"],
        "player2": prepared["p2"],
        "player1_rank": prepared["rating_p1"].get("rank", np.nan),
        "player2_rank": prepared["rating_p2"].get("rank", np.nan),
    }


def _score_result_dict(score, final_probability_p1):
    return {
        "pA_win": float(final_probability_p1),
        "raw_pA_win": float(score.raw_match_win_probability_p1),
        "expected_margin": float(score.expected_margin),
        "expected_total": float(score.expected_total),
        "raw_expected_margin": float(score.expected_margin),
        "raw_expected_total": float(score.expected_total),
        "margin_sd": float(score.margin_sd),
        "total_sd": float(score.total_sd),
        "tiebreak_prob": float(score.tiebreak_probability),
        "score_probs": dict(score.set_score_probabilities),
        "spread": dict(score.spread_probability_p1),
        "spread_push": dict(score.spread_push_probability),
        "over": dict(score.over_probability),
        "total_push": dict(score.total_push_probability),
    }


def _score_model_bundle(score_candidate, *, tour, live_features, simulations):
    """Build the live score bundle from the chronologically validated score candidate.

    Historical score models are trained in deterministic player-A/player-B orientation.
    Live market pricing is player1/player2, so every signed score feature is flipped when
    player1 is B. Total predictions remain invariant because the score model uses absolute
    feature magnitudes for its total-games component.
    """
    if not score_candidate:
        raise ValueError("validated score candidate is required for production scoring")
    if score_candidate.get("market_prices_used") not in (False, None):
        raise ValueError("validated score candidate may not use market prices")
    key = "WTA" if str(tour).upper() == "WTA" else "MEN"
    tour_bundle = score_candidate.get(key)
    if not isinstance(tour_bundle, dict):
        raise ValueError(f"validated score candidate missing tour bundle: {key}")
    selected = str(tour_bundle.get("selected_candidate") or "")
    if selected not in {"conditioned_mechanistic", "gaussian_contextual", "gaussian_hybrid"}:
        raise ValueError(f"unsupported validated score candidate: {selected}")

    bundle = {"model_type": selected, "simulations": int(simulations), "seed": 42}
    if selected == "conditioned_mechanistic":
        return bundle

    model = tour_bundle.get("model") or {}
    feature_names = [str(name) for name in model.get("feature_names", [])]
    if not model or not feature_names:
        raise ValueError(f"validated score candidate {selected} is missing its fitted model")
    if live_features is None:
        raise ValueError(f"validated score candidate {selected} requires live context features")

    sign = 1.0 if bool(live_features.get("player1_is_a", True)) else -1.0
    score_features = {}
    for name in feature_names:
        if name == "mechanistic_margin_a":
            continue
        value = pd.to_numeric(pd.Series([live_features.get(name)]), errors="coerce").iloc[0]
        score_features[name] = np.nan if pd.isna(value) else sign * float(value)
    bundle["model"] = model
    bundle["score_features"] = score_features
    return bundle


def build_fixture_board(
    fixture_rows,
    ratings_by_tour,
    summary,
    sims=5000,
    frozen_at=None,
    *,
    prepared=None,
    enriched_context=None,
    production_candidate=None,
    score_candidate=None,
):
    if fixture_rows is None or fixture_rows.empty:
        return pd.DataFrame()
    prepared = prepared or _prepare_fixture(fixture_rows, ratings_by_tour, summary)
    p1 = prepared["p1"]
    p2 = prepared["p2"]
    calibrated_p = float(prepared["baseline_probability_p1"])
    final_p = calibrated_p
    selected_candidate = "accepted_baseline"
    model_version = "V5.1_OUTCOME_CALIBRATED_FALLBACK"
    context_fallback_reason = "full_context_assets_not_supplied"
    context_meta = {
        "uncertainty_score": np.nan,
        "component_probability_range": np.nan,
        "component_probability_std": np.nan,
    }
    live_features = None

    if production_candidate is not None and enriched_context is not None:
        try:
            fixture = _context_fixture(prepared)
            live_features = build_live_matchup_features_from_enriched(
                enriched_context,
                fixture,
                baseline_probability=calibrated_p,
                x_sr_p1=prepared["x_sr_p1"],
                x_elo_p1=prepared["x_elo_p1"],
            )
            candidate_out = predict_with_production_candidate(
                production_candidate,
                tour=prepared["tour"],
                baseline_probability=float(live_features["baseline_a_probability"]),
                signed_features=pd.DataFrame([live_features]),
            )
            final_a = float(candidate_out["probability"])
            final_p = final_a if bool(live_features["player1_is_a"]) else 1.0 - final_a
            selected_candidate = str(candidate_out["selected_candidate"])
            model_version = str(candidate_out["model_version"])
            context_fallback_reason = ""
            context_meta = candidate_out
        except Exception as exc:
            context_fallback_reason = f"{type(exc).__name__}:{exc}"

    score_bundle = _score_model_bundle(
        score_candidate,
        tour=prepared["tour"],
        live_features=live_features,
        simulations=sims,
    )
    score = predict_score_distribution(
        {
            "serve_probability_p1": prepared["p1_serve"],
            "serve_probability_p2": prepared["p2_serve"],
            "winner_probability_p1": final_p,
            "best_of": prepared["best_of"],
            "spread_lines": _requested_market_lines(fixture_rows, "game_spread"),
            "total_lines": _requested_market_lines(fixture_rows, "total_games"),
            "score_features": score_bundle.get("score_features", {}),
        },
        score_bundle,
    )
    result = _score_result_dict(score, final_p)

    component_range = context_meta.get("component_probability_range", np.nan)
    if pd.notna(component_range):
        component_range = float(component_range)
        disagreement = "HIGH" if component_range >= 0.12 else ("MODERATE" if component_range >= 0.07 else "LOW")
    else:
        disagreement = "UNKNOWN"
    p1_conf = float(prepared["rating_p1"].get("state_confidence", 0.0))
    p2_conf = float(prepared["rating_p2"].get("state_confidence", 0.0))

    priced = add_model_pricing(fixture_rows, result, p1, p2)
    frozen_at = frozen_at or datetime.now(timezone.utc).isoformat()
    signals = []
    confs = []
    for _, r in priced.iterrows():
        conf = _confidence_for_market(r, p1, p2, p1_conf, p2_conf)
        confs.append(conf)
        # Model disagreement remains diagnostic until market-policy validation proves a threshold.
        sig = signal_row(r, disagreement_level=None, state_confidence=conf)
        if prepared["surface_source"] == "Auto default — review" and sig in ("BET", "LEAN"):
            sig = "REVIEW"
        signals.append(sig)

    strength_meta = score.conditioning_metadata
    priced["signal"] = signals
    priced["state_confidence"] = confs
    priced["model_version"] = model_version
    priced["selected_model_candidate"] = selected_candidate
    priced["context_fallback_reason"] = context_fallback_reason
    priced["tour_v5"] = prepared["tour"]
    priced["surface"] = prepared["surface"]
    priced["surface_source"] = prepared["surface_source"]
    priced["best_of"] = prepared["best_of"]
    priced["resolved_player1"] = p1
    priced["resolved_player2"] = p2
    priced["simulations"] = int(sims)
    priced["serve_probability_p1"] = prepared["p1_serve"]
    priced["serve_probability_p2"] = prepared["p2_serve"]
    priced["score_serve_probability_p1"] = score.conditioned_serve_probability_p1
    priced["score_serve_probability_p2"] = score.conditioned_serve_probability_p2
    priced["elo_probability_p1"] = prepared["p_elo"]
    priced["accepted_baseline_probability_p1"] = calibrated_p
    priced["full_context_probability_p1"] = final_p
    priced["raw_sim_probability_p1"] = float(score.raw_match_win_probability_p1)
    priced["calibrated_probability_p1"] = final_p
    priced["strength_conditioning_target_p1"] = float(strength_meta.get("target_probability", final_p))
    priced["strength_conditioning_achieved_p1"] = float(strength_meta.get("achieved_probability", final_p))
    priced["original_serve_logit_difference"] = float(strength_meta.get("original_logit_difference", np.nan))
    priced["conditioned_serve_logit_difference"] = float(strength_meta.get("adjusted_logit_difference", np.nan))
    priced["strength_conditioning_search_sims"] = int(strength_meta.get("search_simulations", 0))
    priced["calibration_version"] = prepared["calibration"]["version"]
    priced["calibration_fit_year"] = prepared["calibration"]["fit_year"]
    priced["calibration_validation_year"] = prepared["calibration"]["validation_year"]
    priced["state_variation_used"] = False
    priced["model_disagreement"] = disagreement
    priced["model_gap"] = abs(final_p - prepared["p_elo"])
    priced["full_context_uncertainty"] = context_meta.get("uncertainty_score", np.nan)
    priced["component_probability_range"] = context_meta.get("component_probability_range", np.nan)
    priced["component_probability_std"] = context_meta.get("component_probability_std", np.nan)
    priced["context_quality_a"] = np.nan if live_features is None else live_features.get("context_quality_a", np.nan)
    priced["context_quality_b"] = np.nan if live_features is None else live_features.get("context_quality_b", np.nan)
    priced["weather_source_quality"] = "missing" if live_features is None else live_features.get("weather_source_quality", "missing")
    priced["court_speed_source_quality"] = "missing" if live_features is None else live_features.get("court_speed_source_quality", "missing")
    priced["score_model_version"] = str(score_candidate.get("version", "unknown"))
    priced["selected_score_candidate"] = score.model_type
    priced["expected_margin"] = float(score.expected_margin)
    priced["expected_total"] = float(score.expected_total)
    priced["raw_expected_margin"] = float(score.expected_margin)
    priced["raw_expected_total"] = float(score.expected_total)
    priced["frozen_at_utc"] = frozen_at
    priced["result_status"] = "OPEN"
    priced["settled_result"] = ""
    priced["profit_units"] = np.nan
    priced["freeze_key"] = priced.apply(freeze_key, axis=1)
    return priced


def build_daily_outputs(
    feed,
    ratings_by_tour,
    summary,
    existing_ledger=None,
    now=None,
    sims=5000,
    *,
    context_history=None,
    production_candidate=None,
    score_candidate=None,
    tournament_registry=None,
    weather_cache=None,
):
    eligible = eligible_pre_match(feed, now=now)
    errors = []
    frozen_at = (now or datetime.now(timezone.utc)).isoformat()
    prepared_rows = []
    for fixture_id, group in eligible.groupby("fixture_id", sort=False):
        try:
            prepared_rows.append((fixture_id, group, _prepare_fixture(
                group, ratings_by_tour, summary, context_history=context_history
            )))
        except Exception as exc:
            first = group.iloc[0]
            errors.append({
                "fixture_id": str(fixture_id),
                "player1": first.get("player1"),
                "player2": first.get("player2"),
                "tournament": first.get("tournament"),
                "stage": "prepare_fixture",
                "error": str(exc),
            })

    enriched_context = None
    if prepared_rows and context_history is not None and production_candidate is not None:
        try:
            enriched_context = build_live_enriched_history(
                context_history,
                [_context_fixture(prepared) for _, _, prepared in prepared_rows],
                tournament_registry=tournament_registry,
                weather_cache=weather_cache,
            )
        except Exception as exc:
            errors.append({"fixture_id": "ALL", "stage": "build_live_context", "error": str(exc)})

    frames = []
    for fixture_id, group, prepared in prepared_rows:
        try:
            frames.append(build_fixture_board(
                group,
                ratings_by_tour,
                summary,
                sims=sims,
                frozen_at=frozen_at,
                prepared=prepared,
                enriched_context=enriched_context,
                production_candidate=production_candidate,
                score_candidate=score_candidate,
            ))
        except Exception as exc:
            first = group.iloc[0]
            errors.append({
                "fixture_id": str(fixture_id),
                "player1": first.get("player1"),
                "player2": first.get("player2"),
                "tournament": first.get("tournament"),
                "stage": "price_fixture",
                "error": str(exc),
            })
    board = pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()
    board = rank_board(board)
    fresh = pd.DataFrame() if board.empty else board[pd.to_numeric(board["model_probability"], errors="coerce").notna()].copy()
    ledger = merge_frozen(existing_ledger, fresh)
    return board, ledger, errors


def _load_summary(path=BASE / "v5_build_summary.json"):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _load_ratings():
    return {
        "MEN": pd.read_csv(BASE / "v5_men_ratings.csv", low_memory=False),
        "WTA": pd.read_csv(BASE / "v5_wta_ratings.csv", low_memory=False),
    }


def _load_score_candidate(path=SCORE_PRODUCTION_CANDIDATE_PATH):
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Validated score candidate missing: {p}")
    data = json.loads(p.read_text(encoding="utf-8"))
    if data.get("market_prices_used") not in (False, None) or "MEN" not in data or "WTA" not in data:
        raise ValueError("Invalid validated score candidate contract")
    return data


def _load_full_context_assets():
    if not CONTEXT_HISTORY_PATH.exists():
        raise FileNotFoundError(f"Full-context warehouse missing: {CONTEXT_HISTORY_PATH}")
    if not PRODUCTION_CANDIDATE_PATH.exists():
        raise FileNotFoundError(f"Validated full-context candidate missing: {PRODUCTION_CANDIDATE_PATH}")
    history = pd.read_parquet(CONTEXT_HISTORY_PATH)
    registry = pd.read_csv(TOURNAMENT_REGISTRY_PATH, low_memory=False) if TOURNAMENT_REGISTRY_PATH.exists() else pd.DataFrame()
    weather = load_weather_cache(BASE)
    candidate = load_production_candidate(PRODUCTION_CANDIDATE_PATH)
    score_candidate = _load_score_candidate(SCORE_PRODUCTION_CANDIDATE_PATH)
    return history, registry, weather, candidate, score_candidate


def main(sims=5000):
    if not MARKET_PATH.exists():
        raise FileNotFoundError(MARKET_PATH)
    feed = pd.read_csv(MARKET_PATH, low_memory=False)
    summary = _load_summary()
    ratings = _load_ratings()
    context_history, tournament_registry, weather_cache, production_candidate, score_candidate = _load_full_context_assets()
    existing = pd.read_csv(FROZEN_LEDGER_PATH, low_memory=False) if FROZEN_LEDGER_PATH.exists() else pd.DataFrame()
    old_count = len(existing)
    now = datetime.now(timezone.utc)
    board, ledger, errors = build_daily_outputs(
        feed,
        ratings,
        summary,
        existing_ledger=existing,
        now=now,
        sims=sims,
        context_history=context_history,
        production_candidate=production_candidate,
        score_candidate=score_candidate,
        tournament_registry=tournament_registry,
        weather_cache=weather_cache,
    )
    OUTDIR.mkdir(parents=True, exist_ok=True)
    board.to_csv(LATEST_BOARD_PATH, index=False)
    ledger.to_csv(FROZEN_LEDGER_PATH, index=False)
    snapshot = None
    if "snapshot_utc" in feed.columns and not feed["snapshot_utc"].dropna().empty:
        snapshot = str(feed["snapshot_utc"].dropna().iloc[0])
    signal_counts = board["signal"].value_counts(dropna=False).to_dict() if not board.empty and "signal" in board.columns else {}
    candidate_counts = board["selected_model_candidate"].value_counts(dropna=False).to_dict() if not board.empty and "selected_model_candidate" in board.columns else {}
    score_candidate_counts = board["selected_score_candidate"].value_counts(dropna=False).to_dict() if not board.empty and "selected_score_candidate" in board.columns else {}
    fallback_rows = int(board["context_fallback_reason"].astype(str).ne("").sum()) if not board.empty and "context_fallback_reason" in board.columns else 0
    payload = {
        "status": "SUCCESS" if not errors and fallback_rows == 0 else "PARTIAL",
        "built_at_utc": now.isoformat(),
        "market_snapshot_utc": snapshot,
        "simulations_per_fixture": int(sims),
        "market_rows_input": int(len(feed)),
        "eligible_pre_match_fixtures": int(eligible_pre_match(feed, now=now)["fixture_id"].nunique()) if not feed.empty else 0,
        "priced_rows": int(pd.to_numeric(board.get("model_probability"), errors="coerce").notna().sum()) if not board.empty else 0,
        "board_rows": int(len(board)),
        "frozen_ledger_rows": int(len(ledger)),
        "new_frozen_rows": int(len(ledger) - old_count),
        "signal_counts": {str(k): int(v) for k, v in signal_counts.items()},
        "selected_candidate_counts": {str(k): int(v) for k, v in candidate_counts.items()},
        "selected_score_candidate_counts": {str(k): int(v) for k, v in score_candidate_counts.items()},
        "context_fallback_rows": fallback_rows,
        "errors": errors,
        "model_version": str(production_candidate["version"]),
        "score_model_version": str(score_candidate["version"]),
        "probability_source": "chronologically validated independent full-context candidate; sportsbook inputs joined only after probability freeze",
        "score_model": "chronologically validated dedicated score-distribution candidate driven only by frozen tennis probability/context",
        "market_prices_used_in_model": False,
        "state_variation_used": False,
    }
    LATEST_SUMMARY_PATH.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(json.dumps(payload, indent=2, default=str))
    return payload


if __name__ == "__main__":
    main()
