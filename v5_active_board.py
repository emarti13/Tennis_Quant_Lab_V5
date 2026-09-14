from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, MutableMapping

import pandas as pd

_ACTIVE_BOARD_KEY = "v5_active_board"
_ACTIVE_MODE_KEY = "v5_active_board_mode"
_ACTIVE_AS_OF_KEY = "v5_active_board_as_of"


def normalize_active_board(board: pd.DataFrame | None, mode: str, as_of: Any = None) -> pd.DataFrame:
    if board is None:
        return pd.DataFrame()
    out = board.copy(deep=True)
    if out.empty:
        return out
    normalized_mode = "adjusted" if str(mode).lower() == "adjusted" else "production"
    timestamp = as_of
    if timestamp is None:
        timestamp = datetime.now(timezone.utc).isoformat()
    out["Board Mode"] = normalized_mode
    out["Board As Of"] = str(timestamp)
    return out


def set_active_board(session_state: MutableMapping[str, Any], board: pd.DataFrame, mode: str, as_of: Any = None) -> None:
    normalized = normalize_active_board(board, mode=mode, as_of=as_of)
    session_state[_ACTIVE_BOARD_KEY] = normalized.copy(deep=True)
    session_state[_ACTIVE_MODE_KEY] = "adjusted" if str(mode).lower() == "adjusted" else "production"
    session_state[_ACTIVE_AS_OF_KEY] = None if normalized.empty else str(normalized["Board As Of"].iloc[0])


def get_active_board(session_state: MutableMapping[str, Any], production_board: pd.DataFrame | None) -> tuple[pd.DataFrame, str]:
    adjusted = session_state.get(_ACTIVE_BOARD_KEY)
    mode = str(session_state.get(_ACTIVE_MODE_KEY) or "")
    if isinstance(adjusted, pd.DataFrame) and not adjusted.empty and mode == "adjusted":
        return adjusted.copy(deep=True), "adjusted"
    return normalize_active_board(production_board, mode="production"), "production"


def clear_adjusted_board(session_state: MutableMapping[str, Any]) -> None:
    for key in (_ACTIVE_BOARD_KEY, _ACTIVE_MODE_KEY, _ACTIVE_AS_OF_KEY):
        session_state.pop(key, None)
