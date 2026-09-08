from __future__ import annotations

from datetime import date
from typing import Iterable

import pandas as pd

from v5_production_artifacts import stable_market_key


MARKET_DEPENDENT_COLUMNS = {
    "market_group",
    "selection",
    "line",
    "best_bookmaker",
    "best_decimal_odds",
    "best_american_odds",
    "best_book_no_vig_prob",
    "consensus_no_vig_prob",
    "books_in_consensus",
    "market_hold_at_best_book",
    "main_line",
    "model_probability",
    "model_win_probability",
    "model_push_probability",
    "model_loss_probability",
    "model_fair_american",
    "edge_vs_consensus",
    "expected_value",
    "signal",
    "freeze_key",
    "settled_result",
    "profit_units",
    "result_status",
}


def forecast_rows_from_board(board: pd.DataFrame, forecast_date: str | None = None) -> pd.DataFrame:
    if board is None or board.empty:
        return pd.DataFrame()
    if "fixture_id" not in board.columns:
        raise ValueError("daily board is missing fixture_id")
    forecast_date = forecast_date or date.today().isoformat()
    keep = [c for c in board.columns if c not in MARKET_DEPENDENT_COLUMNS]
    out = board[keep].copy()
    out.insert(1 if "fixture_id" in out.columns else 0, "forecast_date", forecast_date)
    out = out.drop_duplicates(subset=["fixture_id", "forecast_date"], keep="first")
    return out.reset_index(drop=True)


def market_probability_rows_from_board(board: pd.DataFrame, forecast_date: str | None = None) -> pd.DataFrame:
    """Freeze sportsbook-independent probabilities for the market keys evaluated by the heavy run."""
    if board is None or board.empty:
        return pd.DataFrame()
    required = ["fixture_id", "market_group", "selection", "model_probability"]
    missing = [c for c in required if c not in board.columns]
    if missing:
        raise ValueError(f"daily board is missing market probability columns: {missing}")
    forecast_date = forecast_date or date.today().isoformat()
    out = pd.DataFrame({
        "fixture_id": board["fixture_id"].astype(str),
        "forecast_date": forecast_date,
        "market_group": board["market_group"],
        "selection": board["selection"],
        "line": board["line"] if "line" in board.columns else None,
        "model_probability": pd.to_numeric(board["model_probability"], errors="coerce"),
        "model_win_probability": pd.to_numeric(board.get("model_win_probability"), errors="coerce"),
        "model_push_probability": pd.to_numeric(board.get("model_push_probability"), errors="coerce"),
        "model_loss_probability": pd.to_numeric(board.get("model_loss_probability"), errors="coerce"),
        "model_fair_american": pd.to_numeric(board.get("model_fair_american"), errors="coerce"),
        "model_version": board.get("model_version"),
        "selected_model_candidate": board.get("selected_model_candidate"),
        "score_model_version": board.get("score_model_version"),
        "selected_score_candidate": board.get("selected_score_candidate"),
        "generated_at_utc": board.get("frozen_at_utc"),
    })
    out["market_key"] = [
        stable_market_key(r.fixture_id, r.market_group, r.selection, r.line)
        for r in out.itertuples(index=False)
    ]
    out = out[pd.to_numeric(out["model_probability"], errors="coerce").notna()].copy()
    return out.drop_duplicates(subset=["forecast_date", "market_key"], keep="first").reset_index(drop=True)
