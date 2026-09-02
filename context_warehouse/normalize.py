from __future__ import annotations

import hashlib
from typing import Any

import pandas as pd

from .schema import MATCH_COLUMNS, PLAYER_MATCH_COLUMNS, SCHEMA_VERSION


def _text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def _nullable_text(value: Any) -> str | None:
    text = _text(value)
    return text or None


def _value(row: pd.Series, *names: str) -> Any:
    for name in names:
        if name in row.index:
            return row.get(name)
    return None


def _stable_id(prefix: str, *parts: Any) -> str:
    payload = "|".join(_text(p).casefold() for p in parts)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]
    return f"{prefix}_{digest}"


def _normalize_date(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    raw = _text(value).replace(".0", "")
    parsed = pd.to_datetime(raw[:8], format="%Y%m%d", errors="coerce")
    if pd.isna(parsed):
        parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date().isoformat()


def _normalize_surface(value: Any) -> str | None:
    text = _text(value)
    return text.title() if text else None


def canonicalize_matches(
    frame: pd.DataFrame,
    tour: str,
    level: str,
    source_name: str,
) -> pd.DataFrame:
    rows = []
    for source_row_number, (_, row) in enumerate(frame.iterrows(), start=1):
        winner = _text(row.get("winner_name"))
        loser = _text(row.get("loser_name"))
        event_date = _normalize_date(row.get("tourney_date", row.get("event_date")))
        if not winner or not loser or not event_date:
            continue

        source_tourney_id = row.get("tourney_id")
        source_match_num = row.get("match_num")
        event_name = row.get("tourney_name", row.get("event_name"))
        event_id = _text(source_tourney_id) or _stable_id(
            "e", tour, level, event_name, event_date
        )
        match_id = _stable_id(
            "m",
            tour,
            level,
            event_id,
            source_match_num,
            event_date,
            winner,
            loser,
        )

        rows.append(
            {
                "match_id": match_id,
                "tour": _text(tour).upper(),
                "level": _text(level).upper(),
                "event_id": event_id,
                "event_name": event_name if not pd.isna(event_name) else None,
                "event_date": event_date,
                "round": row.get("round"),
                "surface": _normalize_surface(row.get("surface")),
                "indoor_outdoor": row.get("indoor_outdoor"),
                "best_of": row.get("best_of"),
                "match_minutes": row.get("minutes"),
                "winner_source_player_id": _nullable_text(row.get("winner_id")),
                "loser_source_player_id": _nullable_text(row.get("loser_id")),
                "winner_name": winner,
                "loser_name": loser,
                "winner_hand": row.get("winner_hand"),
                "loser_hand": row.get("loser_hand"),
                "winner_height_cm": _value(row, "winner_ht", "winner_height"),
                "loser_height_cm": _value(row, "loser_ht", "loser_height"),
                "winner_age": row.get("winner_age"),
                "loser_age": row.get("loser_age"),
                "winner_rank": row.get("winner_rank"),
                "loser_rank": row.get("loser_rank"),
                "winner_rank_points": row.get("winner_rank_points"),
                "loser_rank_points": row.get("loser_rank_points"),
                "winner_aces": _value(row, "w_ace", "winner_aces"),
                "loser_aces": _value(row, "l_ace", "loser_aces"),
                "winner_double_faults": _value(row, "w_df", "winner_double_faults"),
                "loser_double_faults": _value(row, "l_df", "loser_double_faults"),
                "winner_service_points": _value(row, "w_svpt", "winner_service_points"),
                "loser_service_points": _value(row, "l_svpt", "loser_service_points"),
                "winner_first_serve_in": _value(row, "w_1stIn", "winner_first_serve_in"),
                "loser_first_serve_in": _value(row, "l_1stIn", "loser_first_serve_in"),
                "winner_first_serve_points_won": _value(row, "w_1stWon", "winner_first_serve_points_won"),
                "loser_first_serve_points_won": _value(row, "l_1stWon", "loser_first_serve_points_won"),
                "winner_second_serve_points_won": _value(row, "w_2ndWon", "winner_second_serve_points_won"),
                "loser_second_serve_points_won": _value(row, "l_2ndWon", "loser_second_serve_points_won"),
                "winner_service_games": _value(row, "w_SvGms", "winner_service_games"),
                "loser_service_games": _value(row, "l_SvGms", "loser_service_games"),
                "winner_break_points_saved": _value(row, "w_bpSaved", "winner_break_points_saved"),
                "loser_break_points_saved": _value(row, "l_bpSaved", "loser_break_points_saved"),
                "winner_break_points_faced": _value(row, "w_bpFaced", "winner_break_points_faced"),
                "loser_break_points_faced": _value(row, "l_bpFaced", "loser_break_points_faced"),
                "score": row.get("score"),
                "source_name": source_name,
                "source_row_number": source_row_number,
                "source_tourney_id": source_tourney_id,
                "source_match_num": source_match_num,
                "ingest_schema_version": SCHEMA_VERSION,
            }
        )

    result = pd.DataFrame(rows, columns=MATCH_COLUMNS)
    if not result.empty:
        result = result.drop_duplicates(subset=["match_id"], keep="last").reset_index(drop=True)
    return result


def _player_id(name: str, source_player_id: Any = None) -> str:
    if source_player_id is not None and not pd.isna(source_player_id):
        return _stable_id("p", "source", source_player_id)
    return _stable_id("p", "name", name)


def _player_row(match: pd.Series, side: str) -> dict[str, Any]:
    other = "loser" if side == "winner" else "winner"
    player_name = _text(match.get(f"{side}_name"))
    opponent_name = _text(match.get(f"{other}_name"))
    source_player_id = match.get(f"{side}_source_player_id")
    opponent_source_player_id = match.get(f"{other}_source_player_id")

    return {
        "match_id": match.get("match_id"),
        "player_id": _player_id(player_name, source_player_id),
        "source_player_id": source_player_id,
        "player_name": player_name,
        "player_side": side,
        "opponent_id": _player_id(opponent_name, opponent_source_player_id),
        "opponent_source_player_id": opponent_source_player_id,
        "opponent_name": opponent_name,
        "is_winner": side == "winner",
        "tour": match.get("tour"),
        "level": match.get("level"),
        "event_id": match.get("event_id"),
        "event_name": match.get("event_name"),
        "event_date": match.get("event_date"),
        "round": match.get("round"),
        "surface": match.get("surface"),
        "best_of": match.get("best_of"),
        "match_minutes": match.get("match_minutes"),
        "hand": match.get(f"{side}_hand"),
        "height_cm": match.get(f"{side}_height_cm"),
        "age": match.get(f"{side}_age"),
        "rank": match.get(f"{side}_rank"),
        "rank_points": match.get(f"{side}_rank_points"),
        "opponent_rank": match.get(f"{other}_rank"),
        "opponent_rank_points": match.get(f"{other}_rank_points"),
        "aces": match.get(f"{side}_aces"),
        "double_faults": match.get(f"{side}_double_faults"),
        "service_points": match.get(f"{side}_service_points"),
        "first_serve_in": match.get(f"{side}_first_serve_in"),
        "first_serve_points_won": match.get(f"{side}_first_serve_points_won"),
        "second_serve_points_won": match.get(f"{side}_second_serve_points_won"),
        "service_games": match.get(f"{side}_service_games"),
        "break_points_saved": match.get(f"{side}_break_points_saved"),
        "break_points_faced": match.get(f"{side}_break_points_faced"),
        "source_name": match.get("source_name"),
        "source_row_number": match.get("source_row_number"),
        "ingest_schema_version": match.get("ingest_schema_version"),
    }


def build_player_match_rows(matches: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, match in matches.iterrows():
        rows.append(_player_row(match, "winner"))
        rows.append(_player_row(match, "loser"))
    return pd.DataFrame(rows, columns=PLAYER_MATCH_COLUMNS)
