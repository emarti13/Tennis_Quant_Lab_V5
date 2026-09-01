from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable


def _parse_dt(value) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def flatten_history(payload: dict) -> list[dict]:
    """Flatten OddsPapi historical-odds response without assigning market semantics."""
    fixture_id = payload.get("fixtureId")
    rows: list[dict] = []
    for bookmaker, book_data in (payload.get("bookmakers") or {}).items():
        for market_id, market_data in (book_data.get("markets") or {}).items():
            for outcome_id, outcome_data in (market_data.get("outcomes") or {}).items():
                for player_id, history in (outcome_data.get("players") or {}).items():
                    if isinstance(history, dict):
                        history = [history]
                    for quote in history or []:
                        created = quote.get("createdAt")
                        price = quote.get("price")
                        if created is None or price is None:
                            continue
                        rows.append({
                            "fixture_id": fixture_id,
                            "bookmaker": str(bookmaker),
                            "market_id": str(market_id),
                            "outcome_id": str(outcome_id),
                            "player_id": str(player_id),
                            "created_at": _parse_dt(created),
                            "price_decimal": float(price),
                            "limit": quote.get("limit"),
                            "active": quote.get("active"),
                            "exchange_meta": quote.get("exchangeMeta"),
                        })
    rows.sort(key=lambda r: (
        r["bookmaker"], r["market_id"], r["outcome_id"], r["player_id"], r["created_at"]
    ))
    return rows


def select_snapshot(
    rows: Iterable[dict],
    *,
    start_time,
    hours_before: float | None = None,
    closing: bool = False,
) -> list[dict]:
    """Select latest quote at/before a pre-match cutoff for each unique outcome."""
    start = _parse_dt(start_time)
    if closing:
        cutoff = start
        label = "close"
    else:
        if hours_before is None:
            raise ValueError("hours_before is required unless closing=True")
        cutoff = start - timedelta(hours=float(hours_before))
        label = f"t-{float(hours_before):g}h"

    best: dict[tuple, dict] = {}
    for row in rows:
        created = _parse_dt(row["created_at"])
        if created > cutoff or created >= start:
            continue
        key = (row["bookmaker"], row["market_id"], row["outcome_id"], row["player_id"])
        prior = best.get(key)
        if prior is None or created > _parse_dt(prior["created_at"]):
            chosen = dict(row)
            chosen["created_at"] = created
            chosen["snapshot_label"] = label
            chosen["cutoff_utc"] = cutoff
            best[key] = chosen
    return sorted(best.values(), key=lambda r: (
        r["bookmaker"], r["market_id"], r["outcome_id"], r["player_id"]
    ))


def build_standard_snapshots(payload: dict, start_time, hours=(24, 12, 6, 1)) -> list[dict]:
    rows = flatten_history(payload)
    out: list[dict] = []
    for h in hours:
        out.extend(select_snapshot(rows, start_time=start_time, hours_before=h))
    out.extend(select_snapshot(rows, start_time=start_time, closing=True))
    return out
