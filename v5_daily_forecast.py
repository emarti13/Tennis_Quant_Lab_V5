from __future__ import annotations

from datetime import date

import pandas as pd

from v5_production_artifacts import stable_market_key


PRICE_DEPENDENT_COLUMNS = {
    "snapshot_utc",
    "best_bookmaker",
    "best_decimal_odds",
    "best_american_odds",
    "best_book_no_vig_prob",
    "consensus_no_vig_prob",
    "books_in_consensus",
    "market_hold_at_best_book",
    "main_line",
    "edge_vs_consensus",
    "expected_value",
    "signal",
    "freeze_key",
    "settled_result",
    "profit_units",
    "result_status",
}

FIXTURE_FORECAST_EXCLUDE = PRICE_DEPENDENT_COLUMNS | {
    "market_group",
    "selection",
    "line",
    "model_probability",
    "model_win_probability",
    "model_push_probability",
    "model_loss_probability",
    "model_fair_american",
    "state_confidence",
}


def forecast_rows_from_board(board: pd.DataFrame, forecast_date: str | None = None) -> pd.DataFrame:
    if board is None or board.empty:
        return pd.DataFrame()
    if "fixture_id" not in board.columns:
        raise ValueError("daily board is missing fixture_id")
    forecast_date = forecast_date or date.today().isoformat()
    keep = [c for c in board.columns if c not in FIXTURE_FORECAST_EXCLUDE]
    out = board[keep].copy()
    out.insert(1 if "fixture_id" in out.columns else 0, "forecast_date", forecast_date)
    out = out.drop_duplicates(subset=["fixture_id", "forecast_date"], keep="first")
    return out.reset_index(drop=True)


def market_probability_rows_from_board(board: pd.DataFrame, forecast_date: str | None = None) -> pd.DataFrame:
    """Freeze tennis-only market probabilities plus the context that produced them.

    The set of market keys is line-specific, but no sportsbook price, consensus,
    edge, EV or recommendation signal is retained here. That allows later price
    refreshes to reprice the exact same forecast without rerunning the model.
    """
    if board is None or board.empty:
        return pd.DataFrame()
    required = [
        "fixture_id", "market_group", "selection", "model_probability",
        "model_win_probability", "model_push_probability", "model_loss_probability",
    ]
    missing = [c for c in required if c not in board.columns]
    if missing:
        raise ValueError(f"daily board is missing market probability columns: {missing}")
    forecast_date = forecast_date or date.today().isoformat()
    keep = [c for c in board.columns if c not in PRICE_DEPENDENT_COLUMNS]
    out = board[keep].copy()
    if "forecast_date" in out.columns:
        out["forecast_date"] = forecast_date
    else:
        out.insert(1, "forecast_date", forecast_date)
    out["market_key"] = [
        stable_market_key(r.fixture_id, r.market_group, r.selection, getattr(r, "line", None))
        for r in out.itertuples(index=False)
    ]
    out = out[pd.to_numeric(out["model_probability"], errors="coerce").notna()].copy()
    return out.drop_duplicates(subset=["forecast_date", "market_key"], keep="first").reset_index(drop=True)
