from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import math

import numpy as np
import pandas as pd

from v5_core import american_from_prob
from v5_daily_batch import (
    _base_probs_from_ratings,
    _context_fixture,
    _load_full_context_assets,
    _logit_probability,
    _player_lookup,
    _resolve_player,
    _tour_to_v5,
    build_fixture_board,
    eligible_pre_match,
    infer_best_of,
    resolve_fixture_surface,
    rank_board,
)
from v5_full_context_live import build_live_enriched_history, build_live_matchup_features_from_enriched
from v5_live_market import canonical_name
from v5_model_calibration import calibrated_match_probability, calibration_record


LIVE_CONTEXT_DISPLAY_FIELDS = (
    "ctx_serve_dominance_diff", "ctx_return_dominance_diff", "ctx_return_strength_diff",
    "ctx_rest_log1p_diff", "ctx_games_7d_diff", "ctx_minutes_7d_diff", "ctx_matches_7d_diff",
    "ctx_travel_km_diff", "ctx_timezone_change_abs_diff",
    "ctx_court_speed_x_serve_dominance_diff", "ctx_court_speed_x_return_dominance_diff", "ctx_big_server_x_altitude",
    "ctx_state_uncertainty_diff", "ctx_context_quality_diff",
)
COURT_CONDITION_DISPLAY_FIELDS = (
    "environment", "external_cpi", "external_ace_rate_pct", "external_rally_length",
    "external_relative_air_density", "external_altitude_m", "external_ball_type",
    "external_overall_speed_rating", "effective_court_speed", "court_conditions_source",
    "court_conditions_source_quality",
)
_SIGNAL_PRIORITY = {"BET": 0, "LEAN": 1, "REVIEW": 2, "PASS": 3, "N/A": 4, "NO PRICE": 5}


def _prepare_with_overrides(fixture_rows, ratings_by_tour, summary, context_history=None):
    first = fixture_rows.iloc[0]
    tournament = first.get("tournament")
    tour_override = str(first.get("v5_tour_override") or "").upper().strip()
    tour = tour_override if tour_override in {"MEN", "WTA"} else _tour_to_v5(first.get("tour"), tournament)
    ratings = ratings_by_tour[tour]

    surface_override = str(first.get("v5_surface_override") or "").title().strip()
    if surface_override in {"Hard", "Clay", "Grass"}:
        surface, surface_source = surface_override, "User override"
    else:
        surface, surface_source = resolve_fixture_surface(
            tournament,
            start_time_utc=first.get("start_time_utc"),
            context_history=context_history,
        )

    bo = pd.to_numeric(pd.Series([first.get("v5_best_of_override")]), errors="coerce").iloc[0]
    best_of = int(bo) if pd.notna(bo) and int(bo) in (3, 5) else infer_best_of(tournament, tour)

    lookup = _player_lookup(ratings)
    p1 = _resolve_player(first.get("player1"), lookup)
    p2 = _resolve_player(first.get("player2"), lookup)
    if p1 is None or p2 is None:
        missing = [str(n) for n, resolved in ((first.get("player1"), p1), (first.get("player2"), p2)) if resolved is None]
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
        "first": first, "tournament": tournament, "tour": tour, "surface": surface,
        "surface_source": surface_source, "best_of": best_of, "p1": p1, "p2": p2,
        "p1_serve": p1_serve, "p2_serve": p2_serve, "rating_p1": a, "rating_p2": b,
        "p_elo": p_elo, "baseline_probability_p1": calibrated_p,
        "calibration": calibration_record(tour),
        "x_sr_p1": _logit_probability(p1_serve) - _logit_probability(p2_serve),
        "x_elo_p1": _logit_probability(p_elo),
    }


def _present_value(value):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    return value


def _interactive_context_fixture(prepared):
    fixture = _context_fixture(prepared)
    first = prepared["first"]
    environment = str(first.get("v5_environment_override") or "").title().strip()
    if environment in {"Indoor", "Outdoor"}:
        fixture["environment"] = environment

    numeric_overrides = {
        "court_speed_override": "v5_court_speed_override",
        "external_cpi_override": "v5_cpi_override",
        "external_ace_rate_pct_override": "v5_ace_rate_override",
        "external_rally_length_override": "v5_rally_length_override",
        "external_relative_air_density_override": "v5_rad_override",
        "external_altitude_m_override": "v5_altitude_override",
    }
    for target, source in numeric_overrides.items():
        value = pd.to_numeric(pd.Series([first.get(source)]), errors="coerce").iloc[0]
        if pd.notna(value):
            fixture[target] = float(value)

    ball = _present_value(first.get("v5_ball_type_override"))
    if ball is not None and str(ball).strip():
        fixture["external_ball_type_override"] = str(ball).strip()
    return fixture


def _best_market(frame: pd.DataFrame):
    if frame is None or frame.empty:
        return None
    work = frame.copy()
    work["_sig"] = work["signal"].astype(str).str.upper().map(_SIGNAL_PRIORITY).fillna(9)
    work["_ev"] = pd.to_numeric(work.get("expected_value"), errors="coerce").fillna(float("-inf"))
    return work.sort_values(["_sig", "_ev"], ascending=[True, False], kind="stable").iloc[0]


def _context_summary(first: pd.Series, fields):
    parts = []
    for label, field in fields:
        value = pd.to_numeric(pd.Series([first.get(field)]), errors="coerce").iloc[0]
        if pd.notna(value):
            parts.append(f"{label} {float(value):+.3f}")
    return " · ".join(parts) if parts else "Unavailable"


def _first_present(*values):
    for value in values:
        if value is None:
            continue
        try:
            if pd.isna(value):
                continue
        except Exception:
            pass
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def production_board_to_today(board: pd.DataFrame) -> pd.DataFrame:
    if board is None or board.empty:
        return pd.DataFrame()
    rows = []
    for fixture_id, group in board.groupby("fixture_id", sort=False, dropna=False):
        first = group.iloc[0]
        tournament = _first_present(first.get("tournament"), "")
        p1 = str(_first_present(first.get("resolved_player1"), first.get("player1"), "Player 1"))
        p2 = str(_first_present(first.get("resolved_player2"), first.get("player2"), "Player 2"))
        tour = _first_present(first.get("tour_v5"))
        if tour is None:
            tour = _tour_to_v5(_first_present(first.get("tour"), ""), tournament)
        best_of = _first_present(first.get("best_of"))
        if best_of is None:
            best_of = infer_best_of(tournament, tour)
        p1p = pd.to_numeric(pd.Series([first.get("full_context_probability_p1")]), errors="coerce").iloc[0]
        p1p = None if pd.isna(p1p) else float(p1p)
        p2p = None if p1p is None else 1.0 - p1p
        disagreement = str(first.get("model_disagreement") or "UNKNOWN").upper()
        row = {
            "Status": "OK", "Fixture ID": fixture_id, "Tournament": tournament,
            "Start": first.get("start_time_utc"), "Tour": tour, "Surface": first.get("surface"),
            "Surface Source": first.get("surface_source"), "Best Of": best_of,
            "Environment": first.get("environment"), "Court Speed": first.get("effective_court_speed"),
            "CPI": first.get("external_cpi"), "Ace Rate %": first.get("external_ace_rate_pct"),
            "Rally Length": first.get("external_rally_length"), "Relative Air Density": first.get("external_relative_air_density"),
            "Altitude m": first.get("external_altitude_m"), "Ball Type": first.get("external_ball_type"),
            "Overall Speed Rating": first.get("external_overall_speed_rating"),
            "Court Conditions Source": first.get("court_conditions_source"),
            "Player 1": p1, "Player 2": p2, "P1 V5 %": p1p, "P2 V5 %": p2p,
            "P1 Fair": None if p1p is None else american_from_prob(p1p),
            "P2 Fair": None if p2p is None else american_from_prob(p2p),
            "Expected Margin": first.get("expected_margin"), "Expected Total": first.get("expected_total"),
            "Agreement": {"LOW":"HIGH", "MODERATE":"MODERATE", "HIGH":"LOW"}.get(disagreement, "UNKNOWN"),
            "Model Disagreement": disagreement, "Model Gap": first.get("model_gap"),
            "Winner Model": first.get("selected_model_candidate"), "Score Model": first.get("selected_score_candidate"),
            "P1 State Conf": first.get("state_confidence_p1"), "P2 State Conf": first.get("state_confidence_p2"),
            "P1 Form": first.get("form_logit_p1"), "P2 Form": first.get("form_logit_p2"),
            "P1 Form Percentile": first.get("form_percentile_p1"), "P2 Form Percentile": first.get("form_percentile_p2"),
            "P1 Volatility": first.get("day_vol_logit_p1"), "P2 Volatility": first.get("day_vol_logit_p2"),
            "P1 Volatility Percentile": first.get("vol_percentile_p1"), "P2 Volatility Percentile": first.get("vol_percentile_p2"),
            "P1 Volatility Label": first.get("volatility_label_p1"), "P2 Volatility Label": first.get("volatility_label_p2"),
            "P1 State Conf Label": first.get("state_confidence_label_p1"), "P2 State Conf Label": first.get("state_confidence_label_p2"),
            "Surface Elo P1 %": first.get("elo_probability_p1"),
            "Matchup Context": _context_summary(first, (("Serve Δ","ctx_serve_dominance_diff"),("Return Δ","ctx_return_dominance_diff"),("Return strength Δ","ctx_return_strength_diff"))),
            "Workload Context": _context_summary(first, (("Rest Δ","ctx_rest_log1p_diff"),("Games 7d Δ","ctx_games_7d_diff"),("Minutes 7d Δ","ctx_minutes_7d_diff"))),
            "Travel Context": _context_summary(first, (("Travel km Δ","ctx_travel_km_diff"),("TZ Δ","ctx_timezone_change_abs_diff"))),
            "Court Context": _context_summary(first, (("Speed×serve Δ","ctx_court_speed_x_serve_dominance_diff"),("Speed×return Δ","ctx_court_speed_x_return_dominance_diff"),("Altitude serve Δ","ctx_big_server_x_altitude"))),
            "Player State": _context_summary(first, (("Uncertainty Δ","ctx_state_uncertainty_diff"),("Quality Δ","ctx_context_quality_diff"))),
            "Context Quality A": first.get("context_quality_a"), "Context Quality B": first.get("context_quality_b"),
            "Weather Source": first.get("weather_source_quality"), "Court Speed Source": first.get("court_speed_source_quality"),
            "Note": first.get("context_fallback_reason") or "",
        }
        for field in LIVE_CONTEXT_DISPLAY_FIELDS:
            row[field] = first.get(field)

        def selected_rows(market, selection):
            x = group[group["market_group"].astype(str).str.lower().eq(market)]
            return x[x["selection"].map(canonical_name).eq(canonical_name(selection))]

        for prefix, player in (("P1", p1), ("P2", p2)):
            ml = _best_market(selected_rows("moneyline", player))
            if ml is not None:
                row[f"{prefix} ML"] = ml.get("best_american_odds"); row[f"{prefix} ML EV"] = ml.get("expected_value"); row[f"{prefix} ML Signal"] = ml.get("signal")
            sp = _best_market(selected_rows("game_spread", player))
            if sp is not None:
                row[f"{prefix} Spread"] = sp.get("line"); row[f"{prefix} Spread Odds"] = sp.get("best_american_odds"); row[f"{prefix} Spread EV"] = sp.get("expected_value"); row[f"{prefix} Spread Signal"] = sp.get("signal")

        totals = group[group["market_group"].astype(str).str.lower().eq("total_games")]
        chosen = _best_market(totals)
        if chosen is not None:
            line = pd.to_numeric(pd.Series([chosen.get("line")]), errors="coerce").iloc[0]
            row["Total"] = line
            same = totals[pd.to_numeric(totals["line"], errors="coerce").eq(line)]
            for label, selection in (("Over","over"),("Under","under")):
                candidate = _best_market(same[same["selection"].astype(str).str.lower().eq(selection)])
                if candidate is not None:
                    row[f"{label} Odds"] = candidate.get("best_american_odds"); row[f"{label} EV"] = candidate.get("expected_value"); row[f"{label} Signal"] = candidate.get("signal")
        rows.append(row)
    return pd.DataFrame(rows)


def run_interactive_production(market_feed, edited, ratings_by_tour, summary, sims=5000, base_dir="."):
    valid = edited[edited["Player 1"].notna() & edited["Player 2"].notna()].copy()
    valid_ids = set(valid["Fixture ID"].astype(str))
    feed = market_feed[market_feed["fixture_id"].astype(str).isin(valid_ids)].copy()
    override = valid.copy(); override.index = override["Fixture ID"].astype(str)
    override_fields = (
        ("v5_tour_override", "Tour"), ("v5_surface_override", "Surface"), ("v5_best_of_override", "Best Of"),
        ("v5_environment_override", "Environment"), ("v5_court_speed_override", "Court Speed"),
        ("v5_cpi_override", "CPI"), ("v5_ace_rate_override", "Ace Rate %"),
        ("v5_rally_length_override", "Rally Length"), ("v5_rad_override", "Relative Air Density"),
        ("v5_altitude_override", "Altitude m"), ("v5_ball_type_override", "Ball Type"),
    )
    for target, source in override_fields:
        if source in override.columns:
            feed[target] = feed["fixture_id"].astype(str).map(override[source].to_dict())
    feed = eligible_pre_match(feed, now=datetime.now(timezone.utc))

    context_path = Path(base_dir) / "context_warehouse" / "player_match_rows.parquet"
    if not context_path.exists():
        return pd.DataFrame(), [{
            "fixture_id": "*",
            "stage": "context_unavailable",
            "error": "Persisted context warehouse is unavailable. Streamlit never rebuilds TennisMyLife context over the network; wait for the scheduled backend refresh.",
        }]
    context_history, tournament_registry, weather_cache, production_candidate, score_candidate = _load_full_context_assets()

    prepared_rows, errors = [], []
    for fixture_id, group in feed.groupby("fixture_id", sort=False):
        try:
            prepared_rows.append((fixture_id, group, _prepare_with_overrides(
                group, ratings_by_tour, summary, context_history=context_history
            )))
        except Exception as exc:
            errors.append({"fixture_id": str(fixture_id), "stage":"prepare_fixture", "error":str(exc)})

    enriched = build_live_enriched_history(
        context_history, [_interactive_context_fixture(p) for _, _, p in prepared_rows],
        tournament_registry=tournament_registry, weather_cache=weather_cache,
    ) if prepared_rows else None

    frames = []
    for fixture_id, group, prepared in prepared_rows:
        try:
            priced = build_fixture_board(
                group, ratings_by_tour, summary, sims=sims, prepared=prepared,
                enriched_context=enriched, production_candidate=production_candidate, score_candidate=score_candidate,
            )
            live = build_live_matchup_features_from_enriched(
                enriched, _interactive_context_fixture(prepared), baseline_probability=prepared["baseline_probability_p1"],
                x_sr_p1=prepared["x_sr_p1"], x_elo_p1=prepared["x_elo_p1"],
            )
            for field in LIVE_CONTEXT_DISPLAY_FIELDS + COURT_CONDITION_DISPLAY_FIELDS:
                priced[field] = live.get(field, np.nan)
            a, b = prepared["rating_p1"], prepared["rating_p2"]
            diagnostics = {
                "state_confidence_p1":float(a.get("state_confidence",0.0)), "state_confidence_p2":float(b.get("state_confidence",0.0)),
                "form_logit_p1":float(a.get("form_logit",0.0)), "form_logit_p2":float(b.get("form_logit",0.0)),
                "form_percentile_p1":float(a.get("form_percentile",50.0)), "form_percentile_p2":float(b.get("form_percentile",50.0)),
                "day_vol_logit_p1":float(a.get("day_vol_logit",0.06)), "day_vol_logit_p2":float(b.get("day_vol_logit",0.06)),
                "vol_percentile_p1":float(a.get("vol_percentile",50.0)), "vol_percentile_p2":float(b.get("vol_percentile",50.0)),
                "volatility_label_p1":str(a.get("volatility_label","Average")), "volatility_label_p2":str(b.get("volatility_label","Average")),
                "state_confidence_label_p1":str(a.get("state_confidence_label","Unknown")), "state_confidence_label_p2":str(b.get("state_confidence_label","Unknown")),
            }
            for key, value in diagnostics.items(): priced[key] = value
            frames.append(priced)
        except Exception as exc:
            errors.append({"fixture_id": str(fixture_id), "stage":"price_fixture", "error":str(exc)})
    production = rank_board(pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame())
    return production_board_to_today(production), errors
