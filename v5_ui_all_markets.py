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
