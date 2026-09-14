from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from v5_courtspeed_fetch import PAGES, fetch_courtspeed_snapshot
from v5_court_conditions_source import normalize_event_name

BASE = Path(__file__).resolve().parent
SNAPSHOT = BASE / "data" / "court_conditions" / "courtspeed_snapshot.csv"
STATUS = BASE / "data" / "court_conditions" / "courtspeed_refresh_status.json"
MARKET_PATH = BASE / "v5_market_ready" / "market_board_input.csv"

KEYS = ["event_key", "year"]
FIELDS = [
    "event_name", "surface_type", "environment", "cpi", "ace_rate_pct",
    "rally_length", "relative_air_density", "altitude_m", "ball_type",
    "overall_speed_rating", "source_name", "source_updated_at", "source_refreshed_at",
]
OBSERVED_FIELDS = [
    "surface_type", "environment", "cpi", "ace_rate_pct", "rally_length",
    "relative_air_density", "altitude_m", "ball_type", "overall_speed_rating",
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
        fresh_values = values.where(mask)
        out[col] = fresh_values.combine_first(out[col])
    out = out.reset_index()
    validate_snapshot(out)
    ordered = KEYS + [c for c in FIELDS if c in out.columns] + [c for c in out.columns if c not in KEYS + FIELDS]
    return out[ordered].sort_values(KEYS, kind="stable").reset_index(drop=True)


def discover_target_events(
    market_path: str | Path = MARKET_PATH,
    *,
    now_utc: str | None = None,
    horizon_days: int = 21,
) -> list[str]:
    path = Path(market_path)
    if not path.exists():
        return []
    try:
        market = pd.read_csv(path, low_memory=False)
    except (OSError, pd.errors.EmptyDataError):
        return []
    if market.empty or "tournament" not in market.columns:
        return []
    work = market.copy()
    if "start_time_utc" in work.columns:
        starts = pd.to_datetime(work["start_time_utc"], errors="coerce", utc=True)
        now = pd.to_datetime(now_utc, errors="coerce", utc=True) if now_utc else pd.Timestamp.now(tz="UTC")
        if pd.notna(now):
            cutoff = now + pd.Timedelta(days=int(horizon_days))
            mask = starts.isna() | ((starts >= now) & (starts <= cutoff))
            work = work.loc[mask]
    keys = {normalize_event_name(name) for name in work["tournament"].dropna().astype(str)}
    return sorted(key for key in keys if key)


def count_updated_fields(existing: pd.DataFrame, fresh: pd.DataFrame) -> int:
    if fresh is None or fresh.empty:
        return 0
    old = existing.copy() if existing is not None else pd.DataFrame()
    old_idx = old.set_index(KEYS) if not old.empty and all(k in old.columns for k in KEYS) else pd.DataFrame()
    updates = 0
    for _, row in fresh.iterrows():
        key = (row.get("event_key"), row.get("year"))
        for field in OBSERVED_FIELDS:
            value = row.get(field)
            if value is None or pd.isna(value) or str(value).strip() == "":
                continue
            previous = None
            if not old_idx.empty and key in old_idx.index and field in old_idx.columns:
                prev = old_idx.loc[key, field]
                if isinstance(prev, pd.Series):
                    prev = prev.iloc[-1]
                previous = None if pd.isna(prev) else prev
            if previous is None or str(previous) != str(value):
                updates += 1
    return updates


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
    targets = discover_target_events(now_utc=started)
    try:
        fresh = fetch_courtspeed_snapshot()
        unresolved = sorted(set(fresh.attrs.get("unresolved_events", [])))
        endpoints = fresh.attrs.get("source_endpoints") or list(PAGES.values())
        validate_snapshot(fresh)
        fields_updated = count_updated_fields(existing, fresh)
        merged = merge_courtspeed_snapshot(existing, fresh)
        _atomic_csv(merged, SNAPSHOT)
        source_events = set(fresh["event_key"].dropna().astype(str))
        requested = targets or sorted(source_events)
        payload = {
            "state": "READY",
            "run_timestamp": started,
            "source": "CourtSpeed",
            "source_endpoints": list(endpoints),
            "target_events": requested,
            "events_requested": int(len(requested)),
            "events_matched": int(len(source_events.intersection(requested))) if targets else int(len(source_events)),
            "rows_fetched": int(len(fresh)),
            "rows_persisted": int(len(merged)),
            "fields_updated": int(fields_updated),
            "unresolved_events": unresolved,
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
            "source_endpoints": list(PAGES.values()),
            "target_events": targets,
            "events_requested": int(len(targets)),
            "events_matched": 0,
            "rows_fetched": 0,
            "rows_persisted": int(len(existing)),
            "fields_updated": 0,
            "unresolved_events": [],
            "last_known_good_retained": bool(before_bytes is not None),
            "error": f"{type(exc).__name__}: {exc}",
        }
    _write_status(payload)
    print(json.dumps(payload, indent=2))
    return payload


if __name__ == "__main__":
    refresh_court_conditions()
