from __future__ import annotations

import json
from pathlib import Path
import re
import pandas as pd

BASE = Path(__file__).resolve().parent
DEFAULT_SNAPSHOT_PATH = BASE / "data" / "court_conditions" / "courtspeed_snapshot.csv"
DEFAULT_STATUS_PATH = BASE / "data" / "court_conditions" / "courtspeed_refresh_status.json"

_EVENT_ALIASES = [
    ("australian_open", ("australian open", "aus open")),
    ("indian_wells", ("indian wells", "bnp paribas open")),
    ("miami", ("miami open", "miami")),
    ("monte_carlo", ("monte carlo", "monte-carlo")),
    ("madrid", ("madrid open", "mutua madrid", "madrid")),
    ("rome", ("italian open", "internazionali bnl", "rome")),
    ("roland_garros", ("roland garros", "french open")),
    ("wimbledon", ("wimbledon",)),
    ("canadian_open", ("canadian open", "national bank open", "rogers cup", "toronto", "montreal")),
    ("cincinnati", ("cincinnati", "western southern", "western & southern")),
    ("us_open", ("us open", "u.s. open", "united states open")),
    ("shanghai", ("shanghai",)),
    ("paris_masters", ("paris masters", "rolex paris masters", "paris")),
    ("atp_finals", ("atp finals", "nitto atp finals", "tour finals")),
]

_METRICS = (
    "surface_type",
    "environment",
    "cpi",
    "ace_rate_pct",
    "rally_length",
    "relative_air_density",
    "altitude_m",
    "ball_type",
    "overall_speed_rating",
)

_SOURCE_NAMES = {
    "surface_type": "surface_source",
    "environment": "environment_source",
    "cpi": "cpi_source",
    "ace_rate_pct": "ace_rate_source",
    "rally_length": "rally_source",
    "relative_air_density": "rad_source",
    "altitude_m": "altitude_source",
    "ball_type": "ball_source",
    "overall_speed_rating": "overall_speed_source",
}


def _clean_text(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()
    return re.sub(r"\s+", " ", text)


def normalize_event_name(name: str) -> str:
    text = _clean_text(name)
    if not text:
        return ""
    for key, aliases in _EVENT_ALIASES:
        if any(_clean_text(alias) in text for alias in aliases):
            return key
    return re.sub(r"\s+", "_", text)


def load_condition_snapshot(path: str | Path | None = None) -> pd.DataFrame:
    p = Path(path) if path is not None else DEFAULT_SNAPSHOT_PATH
    if not p.exists():
        return pd.DataFrame(columns=["event_key", "event_name", "year", *_METRICS, "source_name", "source_updated_at", "source_refreshed_at"])
    df = pd.read_csv(p)
    if "year" in df.columns:
        df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
    return df


def load_refresh_status(path: str | Path | None = None) -> dict:
    p = Path(path) if path is not None else DEFAULT_STATUS_PATH
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _py_value(value):
    if pd.isna(value):
        return None
    if isinstance(value, str):
        value = value.strip()
        return value or None
    try:
        return value.item()
    except Exception:
        return value


def lookup_court_conditions(tournament: str, year: int, snapshot: pd.DataFrame | None = None) -> dict:
    event_key = normalize_event_name(tournament)
    base = {
        "event_key": None,
        "event_name": None,
        "target_year": int(year),
        "source_name": None,
        "source_updated_at": None,
        "source_refreshed_at": None,
        "source_quality": "missing",
    }
    for metric in _METRICS:
        base[metric] = None
        base[f"{metric}_source_year"] = None

    if not event_key:
        return base
    df = snapshot.copy() if snapshot is not None else load_condition_snapshot()
    if df is None or df.empty or "event_key" not in df.columns:
        return base
    rows = df[df["event_key"].astype(str).eq(event_key)].copy()
    if rows.empty:
        return base

    rows["year"] = pd.to_numeric(rows["year"], errors="coerce")
    rows = rows[rows["year"].notna() & (rows["year"] <= int(year))].sort_values("year", ascending=False)
    base["event_key"] = event_key
    base["event_name"] = _py_value(df[df["event_key"].astype(str).eq(event_key)].iloc[-1].get("event_name"))
    if rows.empty:
        return base

    best_source_years = []
    refreshed_values = []
    for metric in _METRICS:
        if metric not in rows.columns:
            continue
        for _, row in rows.iterrows():
            value = _py_value(row.get(metric))
            if value is not None:
                base[metric] = value
                sy = int(row["year"])
                base[f"{metric}_source_year"] = sy
                best_source_years.append(sy)
                rv = _py_value(row.get("source_refreshed_at"))
                if rv:
                    refreshed_values.append(rv)
                break

    first = rows.iloc[0]
    base["source_name"] = _py_value(first.get("source_name"))
    base["source_updated_at"] = _py_value(first.get("source_updated_at"))
    base["source_refreshed_at"] = max(refreshed_values) if refreshed_values else _py_value(first.get("source_refreshed_at"))
    if best_source_years:
        base["source_quality"] = "exact" if all(y == int(year) for y in best_source_years) else "prior_fallback"
    return base


def _status_is_fresh(status: dict, now_utc: str | None, max_source_age_hours: int) -> tuple[bool, str]:
    state = str((status or {}).get("state") or "").upper()
    run_timestamp = (status or {}).get("run_timestamp")
    if not run_timestamp:
        return False, "FALLBACK_V5"
    ts = pd.to_datetime(run_timestamp, errors="coerce", utc=True)
    now = pd.to_datetime(now_utc, errors="coerce", utc=True) if now_utc else pd.Timestamp.now(tz="UTC")
    if pd.isna(ts) or pd.isna(now):
        return False, "FALLBACK_V5"
    age_hours = (now - ts).total_seconds() / 3600.0
    if age_hours <= max_source_age_hours and state in {"READY", "STALE_LKG"}:
        return True, state
    return False, "FALLBACK_V5"


def resolve_court_conditions(
    tournament: str,
    year: int,
    *,
    v5_fallback: dict | None = None,
    now_utc: str | None = None,
    max_source_age_hours: int = 72,
    snapshot: pd.DataFrame | None = None,
    refresh_status: dict | None = None,
) -> dict:
    court = lookup_court_conditions(tournament, year, snapshot=snapshot)
    status = refresh_status if refresh_status is not None else load_refresh_status()
    fresh, freshness = _status_is_fresh(status, now_utc, max_source_age_hours)
    fallback = dict(v5_fallback or {})
    out = {
        "event_key": court.get("event_key"),
        "event_name": court.get("event_name"),
        "target_year": int(year),
        "source_refreshed_at": (status or {}).get("run_timestamp") or court.get("source_refreshed_at"),
        "source_freshness": freshness,
    }
    any_court = False
    any_v5 = False
    for metric in _METRICS:
        source_field = _SOURCE_NAMES[metric]
        court_value = court.get(metric) if fresh else None
        if court_value is not None:
            out[metric] = court_value
            out[source_field] = "CourtSpeed"
            out[f"{metric}_source_year"] = court.get(f"{metric}_source_year")
            out[f"{metric}_fallback"] = False
            any_court = True
            continue
        v5_value = fallback.get(metric)
        if v5_value is not None:
            out[metric] = v5_value
            out[source_field] = "V5"
            out[f"{metric}_source_year"] = int(year)
            out[f"{metric}_fallback"] = True
            any_v5 = True
        else:
            out[metric] = None
            out[source_field] = "missing"
            out[f"{metric}_source_year"] = None
            out[f"{metric}_fallback"] = True
    if any_v5:
        out["source_freshness"] = "FALLBACK_V5"
    elif any_court:
        out["source_freshness"] = freshness
    else:
        out["source_freshness"] = "MISSING"
    return out
