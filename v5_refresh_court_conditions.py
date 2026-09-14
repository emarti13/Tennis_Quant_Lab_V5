from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from v5_courtspeed_fetch import fetch_courtspeed_snapshot

BASE = Path(__file__).resolve().parent
SNAPSHOT = BASE / "data" / "court_conditions" / "courtspeed_snapshot.csv"
STATUS = BASE / "data" / "court_conditions" / "courtspeed_refresh_status.json"

KEYS = ["event_key", "year"]
FIELDS = [
    "event_name", "surface_type", "environment", "cpi", "ace_rate_pct",
    "rally_length", "relative_air_density", "altitude_m", "ball_type",
    "overall_speed_rating", "source_name", "source_updated_at", "source_refreshed_at",
]


def validate_snapshot(df: pd.DataFrame) -> None:
    if df is None or df.empty:
        raise ValueError("CourtSpeed snapshot is empty")
    missing = [c for c in KEYS if c not in df.columns]
    if missing:
        raise ValueError(f"CourtSpeed snapshot missing keys: {missing}")
    if df["event_key"].astype(str).str.strip().eq("").any():
        raise ValueError("CourtSpeed snapshot contains blank event_key")
    if pd.to_numeric(df["year"], errors="coerce").isna().any():
        raise ValueError("CourtSpeed snapshot contains invalid year")
    if df.duplicated(KEYS).any():
        raise ValueError("CourtSpeed snapshot contains duplicate event/year rows")
    if "surface_type" in df.columns:
        bad = df["surface_type"].dropna().astype(str)
        bad = bad[~bad.isin(["Hard", "Clay", "Grass"])]
        if not bad.empty:
            raise ValueError("CourtSpeed snapshot contains invalid surface_type")
    if "environment" in df.columns:
        bad = df["environment"].dropna().astype(str)
        bad = bad[~bad.isin(["Indoor", "Outdoor", "Unknown"])]
        if not bad.empty:
            raise ValueError("CourtSpeed snapshot contains invalid environment")


def merge_courtspeed_snapshot(existing: pd.DataFrame, fresh: pd.DataFrame) -> pd.DataFrame:
    if existing is None or existing.empty:
        out = fresh.copy()
        validate_snapshot(out)
        return out.sort_values(KEYS).reset_index(drop=True)
    if fresh is None or fresh.empty:
        return existing.copy().sort_values(KEYS).reset_index(drop=True)
    old = existing.copy().set_index(KEYS)
    new = fresh.copy().set_index(KEYS)
    all_index = old.index.union(new.index)
    out = old.reindex(all_index)
    for col in new.columns:
        if col not in out.columns:
            out[col] = pd.NA
        values = new[col].reindex(all_index)
        mask = values.notna() & values.astype(str).str.strip().ne("")
        out.loc[mask, col] = values[mask]
    out = out.reset_index()
    validate_snapshot(out)
    ordered = KEYS + [c for c in FIELDS if c in out.columns] + [c for c in out.columns if c not in KEYS + FIELDS]
    return out[ordered].sort_values(KEYS, kind="stable").reset_index(drop=True)


def _atomic_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    df.to_csv(tmp, index=False)
    tmp.replace(path)


def _write_status(payload: dict) -> None:
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATUS.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    tmp.replace(STATUS)


def refresh_court_conditions() -> dict:
    started = pd.Timestamp.now(tz="UTC").isoformat()
    existing = pd.read_csv(SNAPSHOT, low_memory=False) if SNAPSHOT.exists() else pd.DataFrame()
    before_bytes = SNAPSHOT.read_bytes() if SNAPSHOT.exists() else None
    try:
        fresh = fetch_courtspeed_snapshot()
        validate_snapshot(fresh)
        merged = merge_courtspeed_snapshot(existing, fresh)
        _atomic_csv(merged, SNAPSHOT)
        payload = {
            "state": "READY",
            "run_timestamp": started,
            "source": "CourtSpeed",
            "events_requested": int(fresh["event_key"].nunique()),
            "events_matched": int(fresh["event_key"].nunique()),
            "rows_fetched": int(len(fresh)),
            "rows_persisted": int(len(merged)),
            "last_known_good_retained": False,
            "error": None,
        }
    except Exception as exc:
        if before_bytes is not None and SNAPSHOT.exists() and SNAPSHOT.read_bytes() != before_bytes:
            SNAPSHOT.write_bytes(before_bytes)
        payload = {
            "state": "STALE_LKG" if not existing.empty else "FALLBACK_V5",
            "run_timestamp": started,
            "source": "CourtSpeed",
            "events_requested": 0,
            "events_matched": 0,
            "rows_fetched": 0,
            "rows_persisted": int(len(existing)),
            "last_known_good_retained": bool(before_bytes is not None),
            "error": f"{type(exc).__name__}: {exc}",
        }
    _write_status(payload)
    print(json.dumps(payload, indent=2))
    return payload


if __name__ == "__main__":
    refresh_court_conditions()
