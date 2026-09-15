from __future__ import annotations

from io import StringIO
import re

import pandas as pd
import requests

BASE_URL = "https://courtspeed.com"
SOURCE_NAME = "CourtSpeed"

PAGES = {
    "cpi": f"{BASE_URL}/",
    "ace_rate_pct": f"{BASE_URL}/ace-rate/",
    "rally_length": f"{BASE_URL}/rally-length/",
    "weather": f"{BASE_URL}/weather-altitude/",
    "overall_speed_rating": f"{BASE_URL}/overall-speed-rating/",
    "ball_type": f"{BASE_URL}/balls/",
}
_KEYS = ["event_key", "event_name", "year", "surface_type", "environment", "source_name", "source_refreshed_at"]
_SOURCE_EVENT_LABELS = {
    "australian open aus open": ("australian_open", "Australian Open"), "indian wells": ("indian_wells", "Indian Wells"),
    "miami": ("miami", "Miami"), "monte carlo": ("monte_carlo", "Monte Carlo"), "madrid": ("madrid", "Madrid"),
    "rome": ("rome", "Rome"), "roland garros": ("roland_garros", "Roland Garros"), "wimbledon": ("wimbledon", "Wimbledon"),
    "canadian open canada": ("canadian_open", "Canadian Open"), "cincinnati": ("cincinnati", "Cincinnati"),
    "us open": ("us_open", "US Open"), "shanghai": ("shanghai", "Shanghai"), "paris": ("paris_masters", "Paris"),
    "atp finals": ("atp_finals", "ATP Finals"),
}


def _clean(value) -> str:
    text = re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()
    return re.sub(r"\s+", " ", text)


def _year_from_column(value) -> int | None:
    text = str(value).strip().replace("'", "’")
    m = re.fullmatch(r"’?(\d{2})", text)
    if m:
        return 2000 + int(m.group(1))
    m = re.fullmatch(r"(20\d{2})", text)
    return int(m.group(1)) if m else None


def _event_metadata(label: str) -> tuple[str | None, str, str, str]:
    text = re.sub(r"\s+", " ", str(label or "")).strip()
    clean = text.replace("◆", "").strip(); lower = clean.lower()
    surface = "Grass" if "grass" in lower else ("Clay" if "clay" in lower else "Hard")
    environment = "Indoor" if "indoor" in lower else "Outdoor"
    core = re.sub(r"\s+(hard|clay|grass)(?:\s*·\s*indoor)?\s*$", "", clean, flags=re.I).strip()
    key_name = _SOURCE_EVENT_LABELS.get(_clean(core))
    if key_name is None:
        return None, core, surface, environment
    return key_name[0], key_name[1], surface, environment


def _numeric(value) -> float | None:
    if value is None or pd.isna(value): return None
    text = str(value).strip().replace("%", "")
    if not text or text in {"–", "-", "COVID", "—"}: return None
    m = re.search(r"-?\d+(?:\.\d+)?", text)
    return float(m.group(0)) if m else None


def _ball(value) -> str | None:
    if value is None or pd.isna(value): return None
    text = str(value).strip().replace("*", "")
    if not text or text.upper() == "COVID" or text in {"–", "-", "—"}: return None
    return text


def _weather_parts(value) -> tuple[float | None, float | None]:
    if value is None or pd.isna(value): return None, None
    text = str(value).strip().replace(" ", "")
    if not text or text.upper() == "COVID" or text in {"–", "-", "—"}: return None, None
    text = text.replace("·indoor", "")
    m = re.fullmatch(r"(0\.\d{3}|1\.\d{3})(\d+)m", text)
    if m: return float(m.group(1)), float(m.group(2))
    m = re.fullmatch(r"(\d+(?:\.\d+)?)m", text)
    if m: return None, float(m.group(1))
    return None, None


def _first_table(html: str) -> pd.DataFrame:
    tables = pd.read_html(StringIO(html))
    if not tables: raise ValueError("CourtSpeed page contained no tables")
    table = tables[0].copy()
    if table.empty or len(table.columns) < 2: raise ValueError("CourtSpeed table is empty or malformed")
    return table


def _empty_metric_frame(metric: str) -> pd.DataFrame:
    values = ["relative_air_density", "altitude_m"] if metric == "weather" else [metric]
    return pd.DataFrame(columns=_KEYS + values)


def parse_metric_table(html: str, *, metric: str, fetched_at_utc: str) -> pd.DataFrame:
    table = _first_table(html); tournament_col = table.columns[0]
    rows: list[dict] = []; unresolved: set[str] = set()
    for _, source_row in table.iterrows():
        raw_label = str(source_row.get(tournament_col) or "").strip()
        event_key, event_name, surface, environment = _event_metadata(raw_label)
        if not event_key:
            if raw_label: unresolved.add(raw_label)
            continue
        for col in table.columns[1:]:
            year = _year_from_column(col)
            if year is None: continue
            raw = source_row.get(col)
            row = {"event_key": event_key, "event_name": event_name, "year": year, "surface_type": surface,
                   "environment": environment, "source_name": SOURCE_NAME, "source_refreshed_at": fetched_at_utc}
            if metric == "weather":
                rad, altitude = _weather_parts(raw); row["relative_air_density"] = rad; row["altitude_m"] = altitude
            elif metric == "ball_type": row["ball_type"] = _ball(raw)
            elif metric == "overall_speed_rating": row["overall_speed_rating"] = _ball(raw)
            else: row[metric] = _numeric(raw)
            rows.append(row)
    out = pd.DataFrame(rows) if rows else _empty_metric_frame(metric)
    out.attrs["unresolved_events"] = sorted(unresolved)
    return out


def _source_updated_at(html: str) -> str | None:
    m = re.search(r"Updated\s+(\d{1,2}\s+[A-Za-z]{3}\s+20\d{2})", html, flags=re.I)
    if not m: return None
    parsed = pd.to_datetime(m.group(1), errors="coerce")
    return None if pd.isna(parsed) else parsed.date().isoformat()


def parse_courtspeed_pages(pages: dict[str, str], *, fetched_at_utc: str) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []; source_dates: list[str] = []; unresolved: set[str] = set()
    for metric, html in pages.items():
        frame = parse_metric_table(html, metric=metric, fetched_at_utc=fetched_at_utc)
        unresolved.update(frame.attrs.get("unresolved_events", [])); frames.append(frame)
        date = _source_updated_at(html)
        if date: source_dates.append(date)
    if not frames:
        out = pd.DataFrame(columns=_KEYS); out.attrs["unresolved_events"] = []; return out
    merged = frames[0].copy()
    for frame in frames[1:]:
        value_cols = [c for c in frame.columns if c not in _KEYS]
        merged = merged.merge(frame[_KEYS + value_cols], on=_KEYS, how="outer")
    if "source_updated_at" not in merged.columns: merged["source_updated_at"] = max(source_dates) if source_dates else None
    else: merged["source_updated_at"] = max(source_dates) if source_dates else merged["source_updated_at"]
    if not merged.empty: merged = merged.sort_values(["event_key", "year"], kind="stable").reset_index(drop=True)
    merged.attrs["unresolved_events"] = sorted(unresolved)
    return merged


def fetch_courtspeed_snapshot(*, timeout_seconds: int = 20, session=None) -> pd.DataFrame:
    client = session or requests.Session(); fetched_at = pd.Timestamp.now(tz="UTC").isoformat(); pages: dict[str, str] = {}
    headers = {"User-Agent": "TennisQuantLabV5/1.0 (+scheduled court-conditions refresh)"}
    for metric, url in PAGES.items():
        response = client.get(url, timeout=timeout_seconds, headers=headers); response.raise_for_status(); pages[metric] = response.text
    out = parse_courtspeed_pages(pages, fetched_at_utc=fetched_at); out.attrs["source_endpoints"] = list(PAGES.values()); return out
