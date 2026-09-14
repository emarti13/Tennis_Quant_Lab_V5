from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from v5_active_board import clear_adjusted_board, get_active_board, set_active_board
from v5_interactive_production import run_interactive_production
from v5_ui_production import load_canonical_today_board, load_repricing_status, runtime_production_state


EDITABLE_CONTEXT_COLUMNS = [
    "Tour",
    "Surface",
    "Best Of",
    "Environment",
    "Court Speed",
    "CPI",
    "Ace Rate %",
    "Rally Length",
    "Relative Air Density",
    "Altitude m",
    "Ball Type",
]

DISPLAY_PRIORITY = [
    "Status", "Fixture ID", "Tournament", "Start", "Tour", "Surface", "Surface Source",
    "Environment", "Court Speed", "CPI", "Ace Rate %", "Rally Length",
    "Relative Air Density", "Altitude m", "Ball Type", "Court Conditions Source",
    "Player 1", "Player 2", "Best Of",
    "P1 V5 %", "P1 Fair", "P2 V5 %", "P2 Fair",
    "Expected Margin", "Expected Total", "Agreement", "Model Disagreement", "Model Gap",
    "P1 State Conf", "P2 State Conf", "P1 Form", "P2 Form", "P1 Volatility", "P2 Volatility",
    "P1 ML", "P1 ML EV", "P1 ML Signal", "P2 ML", "P2 ML EV", "P2 ML Signal",
    "P1 Spread", "P1 Spread Odds", "P1 Spread EV", "P1 Spread Signal",
    "P2 Spread Odds", "P2 Spread EV", "P2 Spread Signal",
    "Total", "Over Odds", "Over EV", "Over Signal", "Under Odds", "Under EV", "Under Signal",
    "Best Signal", "Note",
]


def _required(namespace: Mapping[str, Any], name: str):
    value = namespace.get(name)
    if value is None:
        raise RuntimeError(f"Daily Board is missing required callback: {name}")
    return value


def _load_summary(base_dir: Path) -> dict:
    path = base_dir / "v5_build_summary.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _editor_source(base_dir: Path, namespace: Mapping[str, Any]) -> pd.DataFrame:
    canonical = load_canonical_today_board(base_dir)
    if canonical is not None and not canonical.empty:
        return canonical.copy(deep=True)
    slate_builder = namespace.get("_oddspapi_daily_slate")
    if slate_builder is not None:
        slate = slate_builder()
        if slate is not None and not slate.empty:
            return slate.copy(deep=True)
    return pd.DataFrame()


def _ensure_editor_columns(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy(deep=True)
    for col in EDITABLE_CONTEXT_COLUMNS:
        if col not in out.columns:
            out[col] = np.nan
    if "Environment" in out.columns:
        out["Environment"] = out["Environment"].replace({np.nan: "Outdoor"}).fillna("Outdoor")
    return out


def _best_signal(row: pd.Series) -> str:
    order = {"BET": 0, "LEAN": 1, "REVIEW": 2, "PASS": 3, "N/A": 4, "NO PRICE": 5}
    signals = []
    for col in row.index:
        if str(col).endswith("Signal"):
            value = str(row.get(col) or "").upper().strip()
            if value:
                signals.append(value)
    return min(signals, key=lambda x: order.get(x, 9)) if signals else ""


def _with_best_signal(board: pd.DataFrame) -> pd.DataFrame:
    out = board.copy(deep=True)
    if out.empty:
        return out
    if "Best Signal" not in out.columns:
        out["Best Signal"] = out.apply(_best_signal, axis=1)
    return out


def _market_runtime(namespace: Mapping[str, Any], base_dir: Path) -> dict:
    load_market_board = _required(namespace, "load_market_board")
    try:
        market_source = load_market_board(include_stale=True)
    except TypeError:
        market_source = load_market_board()
    return runtime_production_state(market_source, load_repricing_status(base_dir))


def render_daily_board(st_module, base_dir: str | Path, namespace: Mapping[str, Any]) -> pd.DataFrame:
    base_dir = Path(base_dir)
    production = load_canonical_today_board(base_dir)
    active, active_mode = get_active_board(st_module.session_state, production)
    runtime = _market_runtime(namespace, base_dir)
    production_state = runtime["state"]
    feed_status = runtime["feed_status"]

    st_module.markdown('<div class="v5-eyebrow">Tennis Quant Lab V5</div>', unsafe_allow_html=True)
    st_module.markdown('<div class="v5-title">Daily Board</div>', unsafe_allow_html=True)
    st_module.markdown(
        '<div class="v5-subtitle">Full-slate analytical workspace. Inspect production output, adjust match context, and run session-only scenarios without rewriting the frozen production forecast.</div>',
        unsafe_allow_html=True,
    )
    st_module.caption(
        "Active board: Adjusted Scenario" if active_mode == "adjusted" else "Active board: Production Forecast"
    )

    if active_mode == "production":
        if production_state == "STALE_PRICES":
            age = feed_status.get("age_hours")
            age_text = "unknown age" if age is None else f"{age:.1f} hours old"
            snapshot = feed_status.get("snapshot_utc") or "unknown"
            st_module.warning(
                f"OddsPapi prices are stale ({age_text}; snapshot {snapshot}). The board below is the last frozen production output and is not currently actionable. Decision Feed is blocked until the next live refresh."
            )
        elif production_state == "MISSING":
            st_module.warning(
                "Live market production artifacts are missing. The last frozen board may remain visible for inspection, but it is not currently actionable."
            )
        elif production_state == "NO_FUTURE_FIXTURES":
            st_module.info(
                "The live market feed is current but contains no future eligible fixtures. Any frozen rows below are retained only for inspection."
            )
        elif production_state in {"STALE_FORECAST", "MISSING_FORECAST"}:
            st_module.warning(
                "Live prices are current, but the canonical daily forecast is not ready. The displayed frozen board is not currently actionable."
            )

    if active_mode == "adjusted":
        if st_module.button("Return to Production Forecast", key="v5_reset_adjusted_board"):
            clear_adjusted_board(st_module.session_state)
            st_module.rerun()

    editor_source = _editor_source(base_dir, namespace)
    if editor_source.empty:
        st_module.warning(
            "No current production/slate rows are available to edit. The board will populate automatically when the production artifacts or current market slate are available."
        )
        return active

    editor_source = _ensure_editor_columns(editor_source)
    fixed_front = [c for c in ["Fixture ID", "Tournament", "Start", "Player 1", "Player 2"] if c in editor_source.columns]
    editor_cols = fixed_front + [c for c in EDITABLE_CONTEXT_COLUMNS if c in editor_source.columns]
    editor = st_module.data_editor(
        editor_source[editor_cols],
        num_rows="fixed",
        hide_index=True,
        use_container_width=True,
        key="v5_full_daily_board_editor",
        disabled=fixed_front,
        column_config={
            "Tour": st_module.column_config.SelectboxColumn(options=["MEN", "WTA"]),
            "Surface": st_module.column_config.SelectboxColumn(options=["Hard", "Clay", "Grass"]),
            "Best Of": st_module.column_config.SelectboxColumn(options=[3, 5]),
            "Environment": st_module.column_config.SelectboxColumn(options=["Outdoor", "Indoor"]),
        },
    )

    precision = st_module.selectbox(
        "Adjusted scenario precision",
        ["Fast — 2,000 per match", "Standard — 5,000 per match", "High — 10,000 per match"],
        index=1,
        key="v5_daily_board_precision",
    )
    sims = {
        "Fast — 2,000 per match": 2000,
        "Standard — 5,000 per match": 5000,
        "High — 10,000 per match": 10000,
    }[precision]

    if st_module.button("RUN ADJUSTED DAILY BOARD", type="primary", key="v5_run_adjusted_daily_board"):
        load_market_board = _required(namespace, "load_market_board")
        load_ratings = _required(namespace, "load_ratings")
        market_feed = load_market_board()
        ratings_by_tour = {"MEN": load_ratings("MEN"), "WTA": load_ratings("WTA")}
        summary = _load_summary(base_dir)
        with st_module.spinner("Running adjusted slate through the production model path..."):
            adjusted, errors = run_interactive_production(
                market_feed,
                editor,
                ratings_by_tour,
                summary,
                sims=sims,
                base_dir=base_dir,
            )
        if errors:
            st_module.warning(f"{len(errors)} fixture/context issue(s) were flagged. Successful rows are not silently guessed.")
            st_module.dataframe(pd.DataFrame(errors), use_container_width=True, hide_index=True)
        if adjusted is not None and not adjusted.empty:
            adjusted = _with_best_signal(adjusted)
            set_active_board(st_module.session_state, adjusted, mode="adjusted")
            st_module.success("Adjusted Scenario is now the active board and is feeding Decision Feed.")
            st_module.rerun()

    active, active_mode = get_active_board(st_module.session_state, production)
    active = _with_best_signal(active)
    if active is None or active.empty:
        st_module.info("No modeled board is available yet.")
        return pd.DataFrame()

    st_module.markdown("### Active Daily Board Results")
    if active_mode == "adjusted":
        st_module.caption("Adjusted Scenario — session only")
    elif production_state == "READY":
        st_module.caption("Production Forecast — LIVE/ACTIONABLE frozen canonical output")
    else:
        st_module.caption(f"Production Forecast — {production_state.replace('_', ' ')} — last frozen output, not actionable")
    cols = [c for c in DISPLAY_PRIORITY if c in active.columns]
    extra = [c for c in active.columns if c not in cols and c not in {"Board Mode", "Board As Of"}]
    st_module.dataframe(active[cols + extra], use_container_width=True, hide_index=True)

    if "Best Signal" in active.columns:
        counts = active["Best Signal"].astype(str).str.upper().value_counts().to_dict()
        st_module.caption(
            " · ".join(f"{label}: {counts.get(label, 0)}" for label in ("BET", "LEAN", "REVIEW", "PASS"))
        )

    st_module.download_button(
        "Download Active Daily Board",
        active.to_csv(index=False).encode("utf-8"),
        file_name="v5_active_daily_board.csv",
        mime="text/csv",
        key="v5_download_active_daily_board",
    )
    return active
