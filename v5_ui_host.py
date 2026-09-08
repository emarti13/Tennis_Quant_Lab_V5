from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from v5_interactive_production import run_interactive_production
from v5_live_market import current_market_rows, future_market_rows, market_feed_status
from v5_ui_all_markets import render_all_markets_page
from v5_ui_health import load_model_health, render_model_health_page
from v5_ui_match_detail import render_match_detail
from v5_ui_navigation import PAGE_ORDER
from v5_ui_performance import load_performance_report, render_performance_page
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


def _read_build_summary(base_dir: Path) -> dict[str, Any]:
    path = base_dir / "v5_build_summary.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _required(namespace: Mapping[str, Any], name: str):
    value = namespace.get(name)
    if value is None:
        raise RuntimeError(f"V5 UI host is missing required callback: {name}")
    return value


def _select_match(st_module, fixture_id: Any) -> None:
    st_module.session_state["v5_selected_fixture_id"] = str(fixture_id)
    st_module.session_state["v5_nav_target"] = "Match Detail"
    st_module.rerun()


def _fixture_slate_from_market_rows(frame: pd.DataFrame | None) -> pd.DataFrame:
    """Build a fixture-only slate without carrying stale sportsbook prices."""
    if frame is None or frame.empty or "fixture_id" not in frame.columns:
        return pd.DataFrame()
    rows = []
    for fixture_id, group in frame.groupby("fixture_id", sort=False):
        first = group.iloc[0]
        raw_tour = str(first.get("tour") or "")
        tour = "WTA" if "WTA" in raw_tour.upper() else "MEN"
        rows.append({
            "Fixture ID": fixture_id,
            "Start": first.get("start_time_utc"),
            "Tournament": first.get("tournament"),
            "Tour": tour,
            "Surface": "Hard",
            "Surface Source": "stale feed fixture only — review",
            "Player 1": first.get("player1"),
            "Player 2": first.get("player2"),
            "Best Of": 3,
        })
    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values(["Start", "Tournament", "Player 1"], na_position="last")
    return out.reset_index(drop=True)


def _slate_editor(st_module, slate: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    precision = st_module.selectbox(
        "Simulation precision",
        ["Fast — 2,000 per match", "Standard — 5,000 per match", "High — 10,000 per match"],
        index=1,
        help="This controls simulation count only; it does not change V5 policy thresholds.",
        key="v5_ui_precision",
    )
    sims = {
        "Fast — 2,000 per match": 2000,
        "Standard — 5,000 per match": 5000,
        "High — 10,000 per match": 10000,
    }[precision]
    editable = slate.copy()
    for name, default in (("Tour", "MEN"), ("Surface", "Hard"), ("Best Of", 3)):
        if name not in editable.columns:
            editable[name] = default
    preferred = [
        "Fixture ID", "Tournament", "Start", "Surface Source", "Tour", "Surface", "Best Of",
        "Player 1", "Player 2", "P1 ML", "P2 ML", "P1 Spread", "P1 Spread Odds",
        "P2 Spread", "P2 Spread Odds", "Total", "Over Odds", "Under Odds",
    ]
    cols = [c for c in preferred if c in editable.columns]
    if hasattr(st_module, "data_editor"):
        disabled = [c for c in ("Fixture ID", "Tournament", "Start", "Surface Source", "Player 1", "Player 2", "P1 ML", "P2 ML") if c in cols]
        edited = st_module.data_editor(
            editable[cols], num_rows="fixed", hide_index=True, use_container_width=True,
            key="v5_today_slate_editor", disabled=disabled,
        )
    else:
        edited = editable[cols].copy()
    return edited, sims


def _unmatched_players(namespace: Mapping[str, Any], edited: pd.DataFrame) -> list[str]:
    load_ratings = _required(namespace, "load_ratings")
    player_lookup = _required(namespace, "_player_lookup")
    resolve_player = _required(namespace, "_resolve_player")
    ratings_by_tour = {"MEN": load_ratings("MEN"), "WTA": load_ratings("WTA")}
    unmatched: set[str] = set()
    for _, row in edited.iterrows():
        tour = str(row.get("Tour", "MEN")).upper().strip()
        ratings = ratings_by_tour.get(tour)
        if ratings is None:
            continue
        lookup = player_lookup(ratings)
        for side in ("Player 1", "Player 2"):
            name = row.get(side)
            if name and resolve_player(name, lookup) is None:
                unmatched.add(str(name))
    return sorted(unmatched)


def _run_daily_board(st_module, namespace: Mapping[str, Any], base_dir: Path, market_feed: pd.DataFrame, edited: pd.DataFrame, sims: int) -> pd.DataFrame:
    load_ratings = _required(namespace, "load_ratings")
    ratings_by_tour = {"MEN": load_ratings("MEN"), "WTA": load_ratings("WTA")}
    summary = _read_build_summary(base_dir)
    status = st_module.empty() if hasattr(st_module, "empty") else None
    if status is not None:
        status.write("Building the full-context production board…")
    try:
        board, errors = run_interactive_production(
            market_feed, edited, ratings_by_tour, summary, sims=sims, base_dir=base_dir
        )
    finally:
        if status is not None:
            status.empty()
    if errors and hasattr(st_module, "warning"):
        st_module.warning(
            f"{len(errors)} fixture/context issue(s) were flagged by the production engine. Affected rows are not silently guessed."
        )
        if hasattr(st_module, "dataframe"):
            st_module.dataframe(pd.DataFrame(errors), use_container_width=True, hide_index=True)
    return board


def _render_today_page(st_module, namespace: Mapping[str, Any], base_dir: Path) -> None:
    load_market_board = _required(namespace, "load_market_board")
    load_all_book_prices = _required(namespace, "load_all_book_prices")
    daily_slate = _required(namespace, "_oddspapi_daily_slate")

    try:
        market_source = load_market_board(include_stale=True)
    except TypeError:
        market_source = load_market_board()
    feed_status = market_feed_status(market_source)
    market_feed = current_market_rows(market_source)
    all_prices = load_all_book_prices() if feed_status["fresh"] else pd.DataFrame()
    slate = daily_slate() if feed_status["fresh"] else _fixture_slate_from_market_rows(future_market_rows(market_source))
    snapshot = market_snapshot(market_source)

    st_module.markdown('<div class="v5-eyebrow">Tennis Quant Lab V5</div>', unsafe_allow_html=True)
    st_module.markdown('<div class="v5-title">Today</div>', unsafe_allow_html=True)
    st_module.markdown(
        '<div class="v5-subtitle">Decision-first slate view. V5 model outputs stay independent; market prices are joined after modeling.</div>',
        unsafe_allow_html=True,
    )

    if feed_status["state"] == "missing":
        st_module.info("The repository market-feed file is missing or empty. The scheduled OddsPapi workflow must create a valid feed before market recommendations can run.")
        return

    if not feed_status["fresh"]:
        age = feed_status.get("age_hours")
        age_text = "unknown age" if age is None else f"{age:.1f} hours old"
        st_module.warning(
            f"OddsPapi prices are stale ({age_text}; snapshot {snapshot}). Stale prices are blocked from BET/LEAN generation. "
            "The automatic live-feed workflow will replace them; fixture information remains visible when future fixtures exist."
        )
        if slate is None or slate.empty:
            st_module.info("The stale repository snapshot contains no future fixtures. This is a stale-feed condition, not a missing repository file.")
            return

    elif feed_status["state"] == "no_future_fixtures" or slate is None or slate.empty:
        st_module.info("The repository feed is fresh but currently contains no future fixtures. Today will populate automatically when the next eligible fixture set is published.")
        return

    with st_module.expander("Slate setup / advanced", expanded=not feed_status["fresh"]):
        freshness = "fresh" if feed_status["fresh"] else "fixture-only; prices disabled"
        st_module.caption(f"Market snapshot: {snapshot} · {len(slate)} fixtures available · {freshness}")
        st_module.markdown("#### Current market slate")
        preview_cols = [c for c in (
            "Start", "Tournament", "Tour", "Surface", "Surface Source", "Player 1", "Player 2",
            "P1 ML", "P2 ML", "P1 Spread", "P1 Spread Odds", "Total", "Over Odds", "Under Odds"
        ) if c in slate.columns]
        if hasattr(st_module, "dataframe"):
            st_module.dataframe(slate[preview_cols], use_container_width=True, hide_index=True)
        default_surface = pd.Series(False, index=slate.index)
        if "Surface Source" in slate.columns:
            default_surface = slate["Surface Source"].astype(str).str.contains("review", case=False, na=False)
        if bool(default_surface.any()):
            st_module.warning(f"Surface inference: {int(default_surface.sum())} fixture(s) use an auto-default surface and should be reviewed before simulation.")
        else:
            st_module.caption("Surface inference: current fixture surfaces were resolved by the tournament map or edited input.")

        edited, sims = _slate_editor(st_module, slate)
        unmatched = _unmatched_players(namespace, edited)
        if unmatched:
            st_module.warning(f"{len(unmatched)} OddsPapi player names could not be matched to the V5 ratings database. Those rows will be flagged rather than guessed.")
            st_module.write(unmatched)
        else:
            st_module.caption("Player-name diagnostic: all current slate names resolve to the V5 ratings database.")

        if feed_status["fresh"]:
            if st_module.button("Run entire daily board", type="primary", key="v5_run_today_board", use_container_width=True):
                board = _run_daily_board(st_module, namespace, base_dir, market_feed, edited, sims)
                st_module.session_state["v5_daily_results"] = board
        else:
            st_module.warning("Run is disabled until fresh prices arrive. The app will never price or rank recommendations from stale sportsbook data.")

        st_module.caption("All-book prices are loaded and available in Match Detail." if all_prices is not None and not all_prices.empty else "All-book comparison is unavailable until a fresh market snapshot is present.")

    if not feed_status["fresh"]:
        return

    board = st_module.session_state.get("v5_daily_results")
    if board is None or board.empty:
        st_module.info("Run the current slate to populate Today with full-context production match cards.")
        return
    prepared = render_today_results(st_module, board, market_feed, snapshot, on_select=lambda fixture: _select_match(st_module, fixture))
    st_module.session_state["v5_today_prepared"] = prepared


def _render_match_detail_page(st_module, namespace: Mapping[str, Any]) -> None:
    load_all_book_prices = _required(namespace, "load_all_book_prices")
    board = st_module.session_state.get("v5_today_prepared")
    if board is None or board.empty:
        raw = st_module.session_state.get("v5_daily_results")
        board = prepare_today_board(raw) if raw is not None and not raw.empty else pd.DataFrame()
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
        _render_match_detail_page(st_module, namespace)
    elif page == "All Markets":
        board = st_module.session_state.get("v5_today_prepared")
        if board is None or board.empty:
            raw = st_module.session_state.get("v5_daily_results")
            board = prepare_today_board(raw) if raw is not None and not raw.empty else pd.DataFrame()
        render_all_markets_page(st_module, board)
    elif page == "Performance":
        render_performance_page(st_module, load_performance_report(base_dir))
    elif page == "Model Health":
        render_model_health_page(st_module, load_model_health(base_dir))
    else:
        _required(namespace, "matchup_lab")()
