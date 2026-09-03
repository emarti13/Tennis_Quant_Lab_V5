from __future__ import annotations

from typing import Any

import pandas as pd

from v5_ui_theme import format_american_odds, format_edge, format_probability


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


def _display_value(value: Any, digits: int = 2) -> str:
    if value in (None, _UNAVAILABLE):
        return _UNAVAILABLE
    try:
        if pd.isna(value):
            return _UNAVAILABLE
    except (TypeError, ValueError):
        pass
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def render_match_detail(st_module, row: pd.Series | None, all_prices: pd.DataFrame | None) -> dict[str, Any] | None:
    if row is None or len(row) == 0:
        st_module.info("Select a match from Today to open its full analysis.")
        return None

    sections = match_detail_sections(row, all_prices)
    overview = sections["overview"]

    st_module.markdown('<div class="v5-eyebrow">Match analysis</div>', unsafe_allow_html=True)
    st_module.markdown(
        f'<div class="v5-title">{overview["player_1"]} vs {overview["player_2"]}</div>',
        unsafe_allow_html=True,
    )
    st_module.markdown(
        f'<div class="v5-subtitle">{overview["primary_market"]} · {overview["signal"]}</div>',
        unsafe_allow_html=True,
    )

    columns = st_module.columns(4)
    columns[0].metric("P1 win", format_probability(overview["p1_probability"]))
    columns[1].metric("P1 fair", format_american_odds(overview["p1_fair"]))
    columns[2].metric("Expected margin", _display_value(overview["expected_margin"], 1))
    columns[3].metric("Expected total", _display_value(overview["expected_total"], 1))

    st_module.markdown('<div class="v5-section-title">Overview</div>', unsafe_allow_html=True)
    overview_frame = pd.DataFrame(
        [
            {
                "Signal": overview["signal"],
                "Primary market": overview["primary_market"],
                "Market price": format_american_odds(overview["primary_market_odds"]),
                "Edge": format_edge(overview["primary_edge"]),
                "Agreement": _display_value(overview["agreement"]),
                "Model gap": _display_value(overview["model_gap"]),
            }
        ]
    )
    st_module.dataframe(overview_frame, use_container_width=True, hide_index=True)

    st_module.markdown('<div class="v5-section-title">Matchup context</div>', unsafe_allow_html=True)
    context = sections["context"]
    context_frame = pd.DataFrame(
        [
            {"Dimension": "Serve / return", "Value": _display_value(context["serve_return"])},
            {"Dimension": "Rest / workload", "Value": _display_value(context["rest_workload"])},
            {"Dimension": "Travel", "Value": _display_value(context["travel"])},
            {"Dimension": "Court", "Value": _display_value(context["court"])},
            {"Dimension": "Player state", "Value": _display_value(context["player_state"])},
        ]
    )
    st_module.dataframe(context_frame, use_container_width=True, hide_index=True)

    st_module.markdown('<div class="v5-section-title">Market board</div>', unsafe_allow_html=True)
    if sections["market_board"].empty:
        st_module.info("No all-book market rows are available for this fixture in the current snapshot.")
    else:
        st_module.dataframe(sections["market_board"], use_container_width=True, hide_index=True)

    st_module.markdown('<div class="v5-section-title">Model detail</div>', unsafe_allow_html=True)
    model = sections["model_detail"]
    model_frame = pd.DataFrame(
        [
            {"Item": "Winner model", "Value": _display_value(model["winner_model"])},
            {"Item": "Score model", "Value": _display_value(model["score_model"])},
            {"Item": "Agreement", "Value": _display_value(model["agreement"])},
            {"Item": "Model gap", "Value": _display_value(model["model_gap"])},
        ]
    )
    st_module.dataframe(model_frame, use_container_width=True, hide_index=True)

    with st_module.expander("Raw / audit data", expanded=False):
        st_module.dataframe(pd.DataFrame([sections["raw"].to_dict()]), use_container_width=True, hide_index=True)

    return sections
