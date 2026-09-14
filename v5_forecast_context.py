from __future__ import annotations

import numpy as np
import pandas as pd

from v5_daily_batch import _context_fixture, _prepare_fixture
from v5_full_context_live import build_live_enriched_history, build_live_matchup_features_from_enriched


LIVE_CONTEXT_FIELDS = (
    "ctx_serve_dominance_diff", "ctx_return_dominance_diff", "ctx_return_strength_diff",
    "ctx_rest_log1p_diff", "ctx_games_7d_diff", "ctx_minutes_7d_diff", "ctx_matches_7d_diff",
    "ctx_travel_km_diff", "ctx_timezone_change_abs_diff",
    "ctx_court_speed_x_serve_dominance_diff", "ctx_court_speed_x_return_dominance_diff", "ctx_big_server_x_altitude",
    "ctx_state_uncertainty_diff", "ctx_context_quality_diff",
)

COURT_CONDITION_FIELDS = (
    "environment",
    "surface_source",
    "environment_source",
    "cpi_source",
    "ace_rate_source",
    "rally_source",
    "rad_source",
    "altitude_source",
    "ball_source",
    "overall_speed_source",
    "external_cpi",
    "external_ace_rate_pct",
    "external_rally_length",
    "external_relative_air_density",
    "external_altitude_m",
    "external_ball_type",
    "external_overall_speed_rating",
    "effective_court_speed",
    "court_conditions_source",
    "court_conditions_source_quality",
)

STATE_FIELDS = (
    "state_confidence_p1", "state_confidence_p2",
    "form_logit_p1", "form_logit_p2",
    "form_percentile_p1", "form_percentile_p2",
    "day_vol_logit_p1", "day_vol_logit_p2",
    "vol_percentile_p1", "vol_percentile_p2",
    "volatility_label_p1", "volatility_label_p2",
    "state_confidence_label_p1", "state_confidence_label_p2",
)


def enrich_daily_board_context(
    board: pd.DataFrame,
    market_feed: pd.DataFrame,
    ratings_by_tour: dict,
    summary: dict,
    context_history: pd.DataFrame,
    *,
    tournament_registry=None,
    weather_cache=None,
) -> tuple[pd.DataFrame, list[dict]]:
    if board is None or board.empty:
        return pd.DataFrame() if board is None else board.copy(), []
    out = board.copy()
    errors: list[dict] = []
    prepared_rows = []
    for fixture_id in out["fixture_id"].dropna().astype(str).unique():
        group = market_feed[market_feed["fixture_id"].astype(str).eq(fixture_id)].copy()
        if group.empty:
            errors.append({"fixture_id": fixture_id, "stage": "context_display", "error": "market fixture missing"})
            continue
        try:
            prepared_rows.append((fixture_id, _prepare_fixture(group, ratings_by_tour, summary)))
        except Exception as exc:
            errors.append({"fixture_id": fixture_id, "stage": "context_display_prepare", "error": str(exc)})

    if not prepared_rows:
        return out, errors
    try:
        enriched = build_live_enriched_history(
            context_history,
            [_context_fixture(prepared) for _, prepared in prepared_rows],
            tournament_registry=tournament_registry,
            weather_cache=weather_cache,
        )
    except Exception as exc:
        errors.append({"fixture_id": "ALL", "stage": "context_display_enrichment", "error": str(exc)})
        return out, errors

    for fixture_id, prepared in prepared_rows:
        try:
            live = build_live_matchup_features_from_enriched(
                enriched,
                _context_fixture(prepared),
                baseline_probability=prepared["baseline_probability_p1"],
                x_sr_p1=prepared["x_sr_p1"],
                x_elo_p1=prepared["x_elo_p1"],
            )
            values = {field: live.get(field, np.nan) for field in LIVE_CONTEXT_FIELDS + COURT_CONDITION_FIELDS}
            a, b = prepared["rating_p1"], prepared["rating_p2"]
            values.update({
                "state_confidence_p1": float(a.get("state_confidence", 0.0)),
                "state_confidence_p2": float(b.get("state_confidence", 0.0)),
                "form_logit_p1": float(a.get("form_logit", 0.0)),
                "form_logit_p2": float(b.get("form_logit", 0.0)),
                "form_percentile_p1": float(a.get("form_percentile", 50.0)),
                "form_percentile_p2": float(b.get("form_percentile", 50.0)),
                "day_vol_logit_p1": float(a.get("day_vol_logit", 0.06)),
                "day_vol_logit_p2": float(b.get("day_vol_logit", 0.06)),
                "vol_percentile_p1": float(a.get("vol_percentile", 50.0)),
                "vol_percentile_p2": float(b.get("vol_percentile", 50.0)),
                "volatility_label_p1": str(a.get("volatility_label", "Average")),
                "volatility_label_p2": str(b.get("volatility_label", "Average")),
                "state_confidence_label_p1": str(a.get("state_confidence_label", "Unknown")),
                "state_confidence_label_p2": str(b.get("state_confidence_label", "Unknown")),
            })
            mask = out["fixture_id"].astype(str).eq(fixture_id)
            for key, value in values.items():
                out.loc[mask, key] = value
        except Exception as exc:
            errors.append({"fixture_id": fixture_id, "stage": "context_display_features", "error": str(exc)})
    return out, errors
