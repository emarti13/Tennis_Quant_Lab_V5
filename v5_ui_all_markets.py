from __future__ import annotations

from typing import Any

import pandas as pd


_DEFAULT_COLUMN_ORDER = [
    "Fixture ID",
    "Start",
    "Tournament",
    "Tour",
    "Best Of",
    "Player 1",
    "Player 2",
    "Best Signal",
    "Primary Market",
    "Primary Market Family",
    "P1 V5 %",
    "P1 Fair",
    "P2 V5 %",
    "P2 Fair",
    "Primary Market Odds",
    "Primary Edge",
    "Expected Margin",
    "Expected Total",
]


def _filter_equals(frame: pd.DataFrame, column: str, value: Any) -> pd.DataFrame:
    if value in (None, "", "All") or column not in frame.columns:
        return frame
    if isinstance(value, str):
        return frame[frame[column].astype(str).str.upper() == value.upper()]
    return frame[frame[column] == value]


def filter_all_markets(
    board: pd.DataFrame | None,
    *,
    tour: str | None = None,
    tournament: str | None = None,
    market_family: str | None = None,
    signal: str | None = None,
    best_of: int | None = None,
    search: str | None = None,
) -> pd.DataFrame:
    if board is None or board.empty:
        return pd.DataFrame(columns=list(board.columns) if board is not None else [])

    out = board.copy()
    out = _filter_equals(out, "Tour", tour)
    out = _filter_equals(out, "Tournament", tournament)
    out = _filter_equals(out, "Primary Market Family", market_family)
    out = _filter_equals(out, "Best Signal", signal)
    out = _filter_equals(out, "Best Of", best_of)

    query = str(search or "").strip().lower()
    if query:
        search_cols = [c for c in ("Player 1", "Player 2", "Tournament", "Primary Market") if c in out.columns]
        if search_cols:
            mask = pd.Series(False, index=out.index)
            for col in search_cols:
                mask = mask | out[col].astype(str).str.lower().str.contains(query, regex=False, na=False)
            out = out[mask]

    return out.reset_index(drop=True)


def default_columns(frame: pd.DataFrame | None) -> list[str]:
    if frame is None:
        return []
    return [column for column in _DEFAULT_COLUMN_ORDER if column in frame.columns]


def _options(frame: pd.DataFrame, column: str) -> list[Any]:
    if column not in frame.columns:
        return ["All"]
    values = [v for v in frame[column].dropna().tolist() if str(v).strip()]
    return ["All"] + sorted(set(values), key=lambda value: str(value))


def render_all_markets_page(st_module, board: pd.DataFrame | None) -> None:
    st_module.markdown("## All Markets")
    st_module.caption("Analyst view of the existing V5 board. Filters never recalculate probabilities, EV, or signals.")

    if board is None or board.empty:
        st_module.info("No modeled market board is available yet. Run or load the Today board first.")
        return

    controls = st_module.columns(3)
    search = controls[0].text_input("Search players / tournament", key="v5_market_search")
    tour = controls[1].selectbox("Tour", options=_options(board, "Tour"), key="v5_market_tour")
    signal = controls[2].selectbox("Signal", options=_options(board, "Best Signal"), key="v5_market_signal")

    controls2 = st_module.columns(3)
    tournament = controls2[0].selectbox("Tournament", options=_options(board, "Tournament"), key="v5_market_tournament")
    family = controls2[1].selectbox("Market family", options=_options(board, "Primary Market Family"), key="v5_market_family")
    best_of_choice = controls2[2].selectbox("Format", options=_options(board, "Best Of"), key="v5_market_bestof")
    best_of = None if best_of_choice == "All" else best_of_choice

    filtered = filter_all_markets(
        board,
        tour=tour,
        tournament=tournament,
        market_family=family,
        signal=signal,
        best_of=best_of,
        search=search,
    )

    st_module.caption(f"{len(filtered)} of {len(board)} modeled matches shown")
    if filtered.empty:
        st_module.info("No markets match the current filters.")
        return

    show_advanced = st_module.checkbox("Show advanced columns", value=False, key="v5_market_advanced")
    columns = list(filtered.columns) if show_advanced else default_columns(filtered)
    st_module.dataframe(filtered[columns], use_container_width=True, hide_index=True)
