from __future__ import annotations

import pandas as pd


def _board(value: float) -> pd.DataFrame:
    return pd.DataFrame([{"Fixture ID": "fx1", "P1 V5 %": value}])


def test_active_board_defaults_to_production_and_adjusted_takes_precedence():
    from v5_active_board import get_active_board, set_active_board

    state = {}
    production = _board(0.60)
    board, mode = get_active_board(state, production)
    assert mode == "production"
    assert board.iloc[0]["P1 V5 %"] == 0.60

    set_active_board(state, _board(0.67), mode="adjusted", as_of="2026-09-14T12:00:00Z")
    board, mode = get_active_board(state, production)
    assert mode == "adjusted"
    assert board.iloc[0]["P1 V5 %"] == 0.67
    assert board.iloc[0]["Board Mode"] == "adjusted"
    assert board.iloc[0]["Board As Of"] == "2026-09-14T12:00:00Z"


def test_clear_adjusted_board_restores_production_without_mutating_source():
    from v5_active_board import clear_adjusted_board, get_active_board, set_active_board

    state = {}
    production = _board(0.60)
    original = production.copy(deep=True)
    set_active_board(state, _board(0.67), mode="adjusted")
    clear_adjusted_board(state)

    board, mode = get_active_board(state, production)
    assert mode == "production"
    assert board.iloc[0]["P1 V5 %"] == 0.60
    pd.testing.assert_frame_equal(production, original)
