from __future__ import annotations

import hashlib
from typing import Any

import pandas as pd

from .schema import MATCH_COLUMNS, PLAYER_MATCH_COLUMNS, SCHEMA_VERSION


def _text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


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
                "winner_name": winner,
                "loser_name": loser,
                "winner_rank": row.get("winner_rank"),
                "loser_rank": row.get("loser_rank"),
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


def _player_id(name: str) -> str:
    return _stable_id("p", name)


def build_player_match_rows(matches: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, match in matches.iterrows():
        winner_name = _text(match.get("winner_name"))
        loser_name = _text(match.get("loser_name"))
        winner_id = _player_id(winner_name)
        loser_id = _player_id(loser_name)

        common = {
            "match_id": match.get("match_id"),
            "tour": match.get("tour"),
            "level": match.get("level"),
            "event_id": match.get("event_id"),
            "event_name": match.get("event_name"),
            "event_date": match.get("event_date"),
            "round": match.get("round"),
            "surface": match.get("surface"),
            "best_of": match.get("best_of"),
            "source_name": match.get("source_name"),
            "source_row_number": match.get("source_row_number"),
            "ingest_schema_version": match.get("ingest_schema_version"),
        }

        rows.append(
            {
                **common,
                "player_id": winner_id,
                "player_name": winner_name,
                "player_side": "winner",
                "opponent_id": loser_id,
                "opponent_name": loser_name,
                "is_winner": True,
                "rank": match.get("winner_rank"),
                "opponent_rank": match.get("loser_rank"),
            }
        )
        rows.append(
            {
                **common,
                "player_id": loser_id,
                "player_name": loser_name,
                "player_side": "loser",
                "opponent_id": winner_id,
                "opponent_name": winner_name,
                "is_winner": False,
                "rank": match.get("loser_rank"),
                "opponent_rank": match.get("winner_rank"),
            }
        )

    return pd.DataFrame(rows, columns=PLAYER_MATCH_COLUMNS)
