from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_MAX_AGE_HOURS = 36.0


def _parse_utc(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def history_status(
    path: str | Path = "v5_refresh_last.json",
    *,
    now: datetime | None = None,
    max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
) -> dict[str, Any]:
    path = Path(path)
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if not path.exists():
        return {
            "state": "MISSING",
            "usable": False,
            "age_hours": None,
            "last_successful_utc": None,
            "status": None,
            "error": "refresh status file missing",
        }

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "state": "INVALID",
            "usable": False,
            "age_hours": None,
            "last_successful_utc": None,
            "status": None,
            "error": str(exc),
        }

    status = str(payload.get("status") or "").upper()
    last_success = _parse_utc(payload.get("last_successful_utc"))
    if last_success is None and status == "SUCCESS":
        last_success = _parse_utc(payload.get("finished_utc"))

    age_hours = None
    if last_success is not None:
        age_hours = max((now - last_success).total_seconds() / 3600.0, 0.0)

    usable = age_hours is not None and age_hours <= float(max_age_hours)
    if not usable:
        state = "STALE" if last_success is not None else "MISSING"
    elif status == "SUCCESS":
        state = "FRESH"
    else:
        state = "DEGRADED"

    return {
        "state": state,
        "usable": bool(usable),
        "age_hours": age_hours,
        "last_successful_utc": last_success.isoformat() if last_success else None,
        "status": status or None,
        "error": payload.get("error"),
        "max_age_hours": float(max_age_hours),
    }
