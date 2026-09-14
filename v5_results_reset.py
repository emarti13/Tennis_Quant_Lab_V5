from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


DEFAULT_RESET_PATH = Path(__file__).resolve().parent / "v5_daily_ready" / "results_reset.json"


def load_reset_timestamp(path: str | Path = DEFAULT_RESET_PATH):
    path = Path(path)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    value = payload.get("reset_at_utc") if isinstance(payload, dict) else None
    if not value:
        return None
    ts = pd.to_datetime(value, errors="coerce", utc=True)
    return None if pd.isna(ts) else pd.Timestamp(ts)


def filter_since_reset(frame: pd.DataFrame | None, reset_at, *, timestamp_columns):
    if frame is None or frame.empty or reset_at is None:
        return pd.DataFrame(columns=list(frame.columns) if frame is not None else []) if frame is None else frame.copy()
    reset = pd.Timestamp(reset_at)
    if reset.tzinfo is None:
        reset = reset.tz_localize("UTC")
    else:
        reset = reset.tz_convert("UTC")
    for column in timestamp_columns:
        if column not in frame.columns:
            continue
        ts = pd.to_datetime(frame[column], errors="coerce", utc=True)
        return frame.loc[ts.notna() & (ts >= reset)].copy().reset_index(drop=True)
    return frame.iloc[0:0].copy().reset_index(drop=True)
