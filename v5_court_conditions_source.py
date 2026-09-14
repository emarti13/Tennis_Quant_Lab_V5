from __future__ import annotations

from pathlib import Path
import re
import pandas as pd

BASE = Path(__file__).resolve().parent
DEFAULT_SNAPSHOT_PATH = BASE / "data" / "court_conditions" / "courtspeed_snapshot.csv"

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
        return pd.DataFrame(columns=["event_key", "event_name", "year", *_METRICS, "source_name", "source_updated_at"])
    df = pd.read_csv(p)
    if "year" in df.columns:
        df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
    return df


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
                break

    first = rows.iloc[0]
    base["source_name"] = _py_value(first.get("source_name"))
    base["source_updated_at"] = _py_value(first.get("source_updated_at"))
    if best_source_years:
        base["source_quality"] = "exact" if all(y == int(year) for y in best_source_years) else "prior_fallback"
    return base
