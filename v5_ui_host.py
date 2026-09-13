from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from v5_live_market import current_market_rows, market_feed_status
from v5_ui_all_markets import render_all_markets_page
from v5_ui_health import load_model_health, render_model_health_page
from v5_ui_match_detail import render_match_detail
from v5_ui_navigation import PAGE_ORDER
from v5_ui_performance import load_performance_report, render_performance_page
from v5_ui_production import load_canonical_today_board, load_repricing_status, production_ui_state
from v5_ui_theme import apply_v5_theme
from v5_ui_today import prepare_today_board, render_today_results


def navigation_pages() -> list[str]:
    return list(PAGE_ORDER)


def market_snapshot(market_feed: pd.DataFrame | None) -> str:
    if market_feed is None or market_feed.empty or "snapshot_utc" not in market_feed.columns:
        return "Unknown"
    values = market_feed["snapshot_utc"].dropna()
    return "Unknown" if values.empty else str(values.iloc[0])


def resolve_selected_match(board: pd.DataFrame | None, fixture_id: Any) -> pd.Series | None:
    if board is None or board.empty or fixture_id is None:
        return None
    if "Fixture ID" in board.columns:
        match = board[board["Fixture ID"].astype(str) == str(fixture_id)]
        if not match.empty:
            return match.iloc[0].copy()
    return None


def _required(namespace: Mapping[str, Any], name: str):
    value = namespace.get(name)
    if value is None:
        raise RuntimeError(f"V5 UI host is missing required callback: {name}")
    return value


def _select_match(st_module, fixture_id: Any) -> None:
    st_module.session_state["v5_selected_fixture_id"] = str(fixture_id)
    st_module.session_state["v5_nav_target"] = "Match Detail"
    st_module.rerun()


def _effective_production_state(feed_status: dict, repricing_status: dict) -> str:
    if feed_status.get("state") == "missing":
        return "MISSING"
    if not feed_status.get("fresh"):
        return "STALE_PRICES"
    if feed_status.get("state") == "no_future_fixtures":
        return "NO_FUTURE_FIXTURES"
    return production_ui_state(repricing_status)


def _render_today_page(st_module, namespace: Mapping[str, Any], base_dir: Path) -> None:
    load_market_board = _required(namespace, "load_market_board")
    try:
        market_source = load_market_board(include_stale=True)
    except TypeError:
        market_source = load_market_board()

    feed_status = market_feed_status(market_source)
    market_feed = current_market_rows(market_source)
    snapshot = market_snapshot(market_source)
    repricing_status = load_repricing_status(base_dir)
    production_state = _effective_production_state(feed_status, repricing_status)

    st_module.markdown('<div class="v5-eyebrow">Tennis Quant Lab V5</div>', unsafe_allow_html=True)
    st_module.markdown('<div class="v5-title">Today</div>', unsafe_allow_html=True)
    st_module.markdown(
        '<div class="v5-subtitle">Decision-first slate view. Daily model forecasts are frozen independently; live prices are repriced automatically.</div>',
        unsafe_allow_html=True,
    )

    if production_state == "MISSING":
        st_module.info(
            "Production artifacts are not available yet. The scheduled pipeline will restore them automatically; no missing or stale input is treated as actionable."
        )
        return

    if production_state == "STALE_PRICES":
        age = feed_status.get("age_hours")
        age_text = "unknown age" if age is None else f"{age:.1f} hours old"
        st_module.warning(
            f"OddsPapi prices are stale ({age_text}; snapshot {snapshot}). BET/LEAN generation is blocked until the automatic live refresh succeeds."
        )
        return

    if production_state == "NO_FUTURE_FIXTURES":
        st_module.info(
            "The market feed is current but contains no future eligible fixtures. Today will populate automatically when the next slate is published."
        )
        return

    if production_state in {"STALE_FORECAST", "MISSING_FORECAST"}:
        st_module.warning(
            "Fresh prices are available, but the canonical daily model forecast is not ready. Recommendations are blocked rather than using an old forecast."
        )
        return

    canonical_board = load_canonical_today_board(base_dir)
    if canonical_board is None or canonical_board.empty:
        st_module.info(
            "The current production cycle has not produced modeled cards yet. The scheduled pipeline will populate Today automatically."
        )
        return

    st_module.caption(
        f"Production state: READY · Market snapshot: {snapshot} · {canonical_board['Fixture ID'].astype(str).nunique() if 'Fixture ID' in canonical_board.columns else len(canonical_board)} modeled fixtures"
    )
    prepared = render_today_results(
        st_module,
        canonical_board,
        market_feed,
        snapshot,
        on_select=lambda fixture: _select_match(st_module, fixture),
    )
    st_module.session_state["v5_today_prepared"] = prepared


def _canonical_prepared_board(base_dir: Path) -> pd.DataFrame:
    canonical = load_canonical_today_board(base_dir)
    if canonical is None or canonical.empty:
        return pd.DataFrame()
    return prepare_today_board(canonical)


def _render_match_detail_page(st_module, namespace: Mapping[str, Any], base_dir: Path) -> None:
    load_all_book_prices = _required(namespace, "load_all_book_prices")
    board = st_module.session_state.get("v5_today_prepared")
    if board is None or board.empty:
        board = _canonical_prepared_board(base_dir)
    selected = st_module.session_state.get("v5_selected_fixture_id")
    row = resolve_selected_match(board, selected)
    if row is None and board is not None and not board.empty:
        labels = [f"{r.get('Player 1')} vs {r.get('Player 2')}" for _, r in board.iterrows()]
        index_by_label = {label: i for i, label in enumerate(labels)}
        label = st_module.selectbox("Choose a modeled match", options=labels, key="v5_detail_match_picker")
        if label in index_by_label:
            row = board.iloc[index_by_label[label]].copy()
            st_module.session_state["v5_selected_fixture_id"] = str(row.get("Fixture ID"))
    render_match_detail(st_module, row, load_all_book_prices())


def run_v5_ui_app(st_module, base_dir: str | Path, namespace: Mapping[str, Any]) -> None:
    base_dir = Path(base_dir)
    apply_v5_theme(st_module)
    nav_target = st_module.session_state.pop("v5_nav_target", None)
    if nav_target in navigation_pages():
        st_module.session_state["v5_page"] = nav_target
    page = st_module.sidebar.radio(
        "V5", navigation_pages(), index=0, key="v5_page",
        help="Today is the decision surface; deeper analysis remains one interaction away.",
    )
    if page == "Today":
        _render_today_page(st_module, namespace, base_dir)
    elif page == "Match Detail":
        _render_match_detail_page(st_module, namespace, base_dir)
    elif page == "All Markets":
        board = st_module.session_state.get("v5_today_prepared")
        if board is None or board.empty:
            board = _canonical_prepared_board(base_dir)
        render_all_markets_page(st_module, board)
    elif page == "Performance":
        render_performance_page(st_module, load_performance_report(base_dir))
    elif page == "Model Health":
        render_model_health_page(st_module, load_model_health(base_dir))
    else:
        _required(namespace, "matchup_lab")()
