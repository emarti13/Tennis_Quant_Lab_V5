from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone


def canonical_name(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).strip().lower()
    if "," in text:
        parts = [p.strip() for p in text.split(",") if p.strip()]
        if len(parts) == 2:
            text = f"{parts[1]} {parts[0]}"
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def pair_key(a: str, b: str) -> tuple[str, str]:
    return tuple(sorted((canonical_name(a), canonical_name(b))))


def _date(value):
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip().replace("Z", "+00:00")
        if len(text) == 10:
            return datetime.fromisoformat(text).date()
        dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).date()


def match_fixture(fixture: dict, candidates, *, date_tolerance_days: int = 0):
    target_pair = pair_key(fixture.get("participant1Name"), fixture.get("participant2Name"))
    target_date = _date(fixture.get("startTime") or fixture.get("trueStartTime"))
    matched = []
    for row in candidates:
        winner = row.get("winner_name", row.get("winner"))
        loser = row.get("loser_name", row.get("loser"))
        if pair_key(winner, loser) != target_pair:
            continue
        row_date = _date(row.get("date", row.get("tourney_date")))
        if abs((row_date - target_date).days) <= date_tolerance_days:
            matched.append(row)
    return matched[0] if len(matched) == 1 else None
