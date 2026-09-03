from __future__ import annotations

from typing import Any

import pandas as pd


_UNAVAILABLE = "Unavailable"


def _first_present(row: pd.Series, names: tuple[str, ...], default: Any = _UNAVAILABLE) -> Any:
    for name in names:
        if name not in row.index:
            continue
        value = row.get(name)
        try:
            if pd.isna(value):
                continue
        except (TypeError, ValueError):
            pass
        if str(value).strip() == "":
            continue
        return value
    return default


def _fixture_prices(all_prices: pd.DataFrame | None, fixture_id: Any) -> pd.DataFrame:
    if all_prices is None or all_prices.empty or fixture_id is None:
        return pd.DataFrame(columns=list(all_prices.columns) if all_prices is not None else [])
    for column in ("fixture_id", "Fixture ID", "fixtureId", "id"):
        if column in all_prices.columns:
            return all_prices[all_prices[column].astype(str) == str(fixture_id)].copy().reset_index(drop=True)
    return pd.DataFrame(columns=list(all_prices.columns))


def match_detail_sections(row: pd.Series, all_prices: pd.DataFrame | None) -> dict[str, Any]:
    """Build display-only Match Detail sections without changing model values."""
    fixture_id = _first_present(row, ("Fixture ID", "fixture_id", "fixtureId"), default=None)

    overview = {
        "fixture_id": fixture_id,
        "player_1": _first_present(row, ("Player 1", "player1", "player_1")),
        "player_2": _first_present(row, ("Player 2", "player2", "player_2")),
        "p1_probability": _first_present(row, ("P1 V5 %", "p1_probability"), default=None),
        "p2_probability": _first_present(row, ("P2 V5 %", "p2_probability"), default=None),
        "p1_fair": _first_present(row, ("P1 Fair", "p1_fair"), default=None),
        "p2_fair": _first_present(row, ("P2 Fair", "p2_fair"), default=None),
        "expected_margin": _first_present(row, ("Expected Margin", "expected_margin"), default=None),
        "expected_total": _first_present(row, ("Expected Total", "expected_total"), default=None),
        "signal": _first_present(row, ("Best Signal", "Signal", "signal")),
        "primary_market": _first_present(row, ("Primary Market", "primary_market")),
        "primary_edge": _first_present(row, ("Primary Edge", "edge"), default=None),
        "primary_market_odds": _first_present(row, ("Primary Market Odds", "market_odds"), default=None),
        "agreement": _first_present(row, ("Agreement", "agreement"), default=None),
        "model_gap": _first_present(row, ("Model Gap", "model_gap"), default=None),
        "best_of": _first_present(row, ("Best Of", "best_of"), default=None),
    }

    context = {
        "serve_return": _first_present(
            row,
            (
                "Matchup Context",
                "ctx_serve_dominance_diff",
                "ctx_return_dominance_diff",
                "ctx_return_strength_diff",
            ),
        ),
        "rest_workload": _first_present(
            row,
            (
                "Workload Context",
                "ctx_rest_log1p_diff",
                "ctx_games_7d_diff",
                "ctx_minutes_7d_diff",
                "ctx_matches_7d_diff",
            ),
        ),
        "travel": _first_present(
            row,
            ("Travel Context", "ctx_travel_km_diff", "ctx_timezone_change_abs_diff"),
        ),
        "court": _first_present(
            row,
            (
                "Court Context",
                "ctx_court_speed_x_serve_dominance_diff",
                "ctx_court_speed_x_return_dominance_diff",
                "ctx_big_server_x_altitude",
            ),
        ),
        "player_state": _first_present(
            row,
            ("Player State", "ctx_state_uncertainty_diff", "ctx_context_quality_diff"),
        ),
    }

    model_detail = {
        "winner_model": _first_present(row, ("Winner Model", "winner_model", "winner_candidate")),
        "score_model": _first_present(row, ("Score Model", "score_model", "score_candidate")),
        "agreement": overview["agreement"],
        "model_gap": overview["model_gap"],
        "expected_margin": overview["expected_margin"],
        "expected_total": overview["expected_total"],
    }

    return {
        "overview": overview,
        "context": context,
        "market_board": _fixture_prices(all_prices, fixture_id),
        "model_detail": model_detail,
        "raw": row.copy(),
    }
