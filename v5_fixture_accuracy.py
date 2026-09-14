from __future__ import annotations

import re

import numpy as np
import pandas as pd


_OUTPUT_COLUMNS = [
    "fixture_id", "tournament", "tour", "surface", "model_version",
    "selected_model_candidate", "selected_score_candidate",
    "player1", "player2", "p1_probability", "predicted_winner",
    "actual_winner", "actual_p1_win", "winner_correct", "brier_score",
    "expected_margin", "actual_margin", "margin_error", "abs_margin_error",
    "expected_total", "actual_total", "total_error", "abs_total_error",
    "result_score", "settled_at_utc",
]


def _number(value):
    try:
        if value is None or pd.isna(value):
            return np.nan
        return float(value)
    except (TypeError, ValueError):
        return np.nan


def _first_present(row: pd.Series, *columns):
    for column in columns:
        value = row.get(column)
        try:
            if value is None or pd.isna(value):
                continue
        except (TypeError, ValueError):
            pass
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def _name(value) -> str:
    text = str(value or "").lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _same_player(left, right) -> bool:
    a = _name(left)
    b = _name(right)
    if not a or not b:
        return False
    if a == b:
        return True
    a_tokens = a.split()
    b_tokens = b.split()
    return len(a_tokens) >= 2 and len(b_tokens) >= 2 and a_tokens[0] == b_tokens[0] and a_tokens[-1] == b_tokens[-1]


def fixture_accuracy_records(frozen: pd.DataFrame | None) -> pd.DataFrame:
    """Collapse settled frozen market rows to one match-forecast observation per fixture."""
    if frozen is None or frozen.empty or "fixture_id" not in frozen.columns:
        return pd.DataFrame(columns=_OUTPUT_COLUMNS)

    work = frozen.copy()
    status = work.get("result_status", pd.Series(index=work.index, dtype=object)).fillna("").astype(str).str.upper()
    work = work.loc[status.eq("SETTLED")].copy()
    work = work.loc[work["fixture_id"].notna() & work["fixture_id"].astype(str).str.strip().ne("")].copy()
    if work.empty:
        return pd.DataFrame(columns=_OUTPUT_COLUMNS)

    rows = []
    for fixture_id, group in work.groupby("fixture_id", sort=False, dropna=False):
        first = group.iloc[0]
        player1 = _first_present(first, "resolved_player1", "player1")
        player2 = _first_present(first, "resolved_player2", "player2")
        actual_winner = _first_present(first, "result_winner")
        p1_probability = _number(_first_present(first, "full_context_probability_p1", "match_probability_p1"))
        expected_margin = _number(_first_present(first, "expected_margin"))
        expected_total = _number(_first_present(first, "expected_total"))
        winner_games = _number(_first_present(first, "winner_games"))
        loser_games = _number(_first_present(first, "loser_games"))

        actual_p1_win = np.nan
        if _same_player(actual_winner, player1):
            actual_p1_win = 1.0
        elif _same_player(actual_winner, player2):
            actual_p1_win = 0.0

        predicted_winner = None
        winner_correct = pd.NA
        brier = np.nan
        if np.isfinite(p1_probability):
            predicted_winner = player1 if p1_probability >= 0.5 else player2
            if np.isfinite(actual_p1_win):
                winner_correct = bool((p1_probability >= 0.5) == bool(actual_p1_win))
                brier = float((p1_probability - actual_p1_win) ** 2)

        actual_margin = np.nan
        actual_total = np.nan
        if np.isfinite(winner_games) and np.isfinite(loser_games):
            game_difference = winner_games - loser_games
            actual_total = winner_games + loser_games
            if actual_p1_win == 1.0:
                actual_margin = game_difference
            elif actual_p1_win == 0.0:
                actual_margin = -game_difference

        margin_error = actual_margin - expected_margin if np.isfinite(actual_margin) and np.isfinite(expected_margin) else np.nan
        total_error = actual_total - expected_total if np.isfinite(actual_total) and np.isfinite(expected_total) else np.nan

        rows.append({
            "fixture_id": fixture_id,
            "tournament": _first_present(first, "tournament", "result_tournament"),
            "tour": _first_present(first, "tour_v5", "tour"),
            "surface": _first_present(first, "surface"),
            "model_version": _first_present(first, "model_version"),
            "selected_model_candidate": _first_present(first, "selected_model_candidate"),
            "selected_score_candidate": _first_present(first, "selected_score_candidate"),
            "player1": player1,
            "player2": player2,
            "p1_probability": p1_probability,
            "predicted_winner": predicted_winner,
            "actual_winner": actual_winner,
            "actual_p1_win": actual_p1_win,
            "winner_correct": winner_correct,
            "brier_score": brier,
            "expected_margin": expected_margin,
            "actual_margin": actual_margin,
            "margin_error": margin_error,
            "abs_margin_error": abs(margin_error) if np.isfinite(margin_error) else np.nan,
            "expected_total": expected_total,
            "actual_total": actual_total,
            "total_error": total_error,
            "abs_total_error": abs(total_error) if np.isfinite(total_error) else np.nan,
            "result_score": _first_present(first, "result_score"),
            "settled_at_utc": _first_present(first, "settled_at_utc"),
        })

    return pd.DataFrame(rows, columns=_OUTPUT_COLUMNS)


def fixture_accuracy_metrics(records: pd.DataFrame | None) -> dict:
    if records is None or records.empty:
        return {
            "settled_fixtures": 0,
            "winner_accuracy": np.nan,
            "brier_score": np.nan,
            "margin_mae": np.nan,
            "total_mae": np.nan,
        }

    correct = records.get("winner_correct", pd.Series(index=records.index, dtype=object)).dropna()
    brier = pd.to_numeric(records.get("brier_score"), errors="coerce").dropna()
    margin = pd.to_numeric(records.get("abs_margin_error"), errors="coerce").dropna()
    total = pd.to_numeric(records.get("abs_total_error"), errors="coerce").dropna()
    return {
        "settled_fixtures": int(len(records)),
        "winner_accuracy": np.nan if correct.empty else float(correct.astype(bool).mean()),
        "brier_score": np.nan if brier.empty else float(brier.mean()),
        "margin_mae": np.nan if margin.empty else float(margin.mean()),
        "total_mae": np.nan if total.empty else float(total.mean()),
    }
