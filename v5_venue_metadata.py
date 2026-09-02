from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import json
import re

import numpy as np
import pandas as pd
import requests

from v5_tournament_registry import normalize_event_name

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"

CITY_OVERRIDES = {
    "australian open": "Melbourne",
    "roland garros": "Paris",
    "french open": "Paris",
    "wimbledon": "London",
    "us open": "New York",
    "u s open": "New York",
}


def stable_event_id(tour: str, tourney_id, tourney_name: str) -> str:
    tour_key = str(tour or "MEN").upper().replace("ATP", "MEN")
    raw_id = "" if tourney_id is None or pd.isna(tourney_id) else str(tourney_id).strip()
    match = re.match(r"^(?:19|20)\d{2}[-_:](.+)$", raw_id)
    if match and match.group(1).strip():
        return f"{tour_key}:{match.group(1).strip()}"
    if raw_id:
        clean_id = re.sub(r"\s+", "", raw_id)
        return f"{tour_key}:{clean_id}"
    name = normalize_event_name(tourney_name or "")
    slug = re.sub(r"\s+", "-", name)
    return f"{tour_key}:{slug}" if slug else f"{tour_key}:unknown"


def location_query(tourney_name: str) -> str:
    normalized = normalize_event_name(tourney_name or "")
    return CITY_OVERRIDES.get(normalized, str(tourney_name or "").strip())


def choose_geocode_candidate(query: str, candidates: list[dict], dominance_ratio: float = 5.0):
    q = normalize_event_name(query or "")
    exact = [c for c in (candidates or []) if normalize_event_name(c.get("name") or "") == q]
    if len(exact) == 1:
        return exact[0], "exact_unique"
    if len(exact) > 1:
        ranked = sorted(exact, key=lambda c: float(c.get("population") or 0), reverse=True)
        top_pop = float(ranked[0].get("population") or 0)
        second_pop = float(ranked[1].get("population") or 0)
        if top_pop > 0 and (second_pop <= 0 or top_pop >= dominance_ratio * second_pop):
            return ranked[0], "exact_population_dominant"
        return None, "ambiguous"
    return None, "no_exact_match"


class OpenMeteoGeocoder:
    def __init__(self, cache_dir: str | Path = "context_cache/venues", session=None):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.session = session or requests.Session()

    def search(self, query: str) -> list[dict]:
        clean = str(query or "").strip()
        if not clean:
            return []
        key = sha256(clean.casefold().encode("utf-8")).hexdigest()[:24]
        path = self.cache_dir / f"{key}.json"
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            return payload.get("results") or []
        response = self.session.get(
            GEOCODING_URL,
            params={"name": clean, "count": 8, "language": "en", "format": "json"},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload.get("results") or []


def _mode_nonempty(series: pd.Series):
    values = [v for v in series.tolist() if v is not None and not pd.isna(v) and str(v).strip()]
    if not values:
        return None
    counts = pd.Series(values).value_counts()
    return counts.index[0]


def _year_bounds(group: pd.DataFrame) -> tuple[int | None, int | None]:
    dates = pd.to_datetime(group.get("match_date"), errors="coerce")
    years = dates.dt.year.dropna().astype(int)
    if years.empty:
        return None, None
    return int(years.min()), int(years.max())


def _contiguous_year_segments(group: pd.DataFrame) -> list[pd.DataFrame]:
    dates = pd.to_datetime(group.get("match_date"), errors="coerce")
    working = group.copy()
    working["_year"] = dates.dt.year
    valid_years = sorted(int(y) for y in working["_year"].dropna().unique())
    if not valid_years:
        return [working.drop(columns=["_year"])]
    runs, current = [], [valid_years[0]]
    for year in valid_years[1:]:
        if year == current[-1] + 1:
            current.append(year)
        else:
            runs.append(current)
            current = [year]
    runs.append(current)
    return [working[working["_year"].isin(run)].drop(columns=["_year"]) for run in runs]


def build_registry_from_events(events: pd.DataFrame, geocoder=None) -> tuple[pd.DataFrame, dict]:
    """Build conservative, year-aware venue registry rows from observed event metadata.

    A stable tournament code may map to different cities in different years. Location-name
    groups are therefore segmented into contiguous year ranges; this prevents alternating or
    moved events from being assigned one permanent geography. Ambiguous geocodes remain
    explicitly unresolved.
    """
    if events is None or events.empty:
        return pd.DataFrame(), {"events": 0, "resolved_events": 0, "unresolved_events": 0}
    geocoder = geocoder or OpenMeteoGeocoder()
    df = events.copy()
    if "tourney_id" not in df.columns:
        df["tourney_id"] = np.nan
    df["stable_event_id"] = [
        stable_event_id(tour, tid, name)
        for tour, tid, name in zip(df.get("tour", "MEN"), df["tourney_id"], df.get("tourney_name", ""))
    ]
    df["location_query"] = [location_query(name) for name in df.get("tourney_name", "")]

    rows = []
    unresolved = []
    for (event_id, query), location_group in df.groupby(["stable_event_id", "location_query"], sort=True, dropna=False):
        for group in _contiguous_year_segments(location_group):
            name = str(_mode_nonempty(group.get("tourney_name", pd.Series(dtype=object))) or query or "")
            query_text = str(query or "").strip()
            candidates = geocoder.search(query_text)
            chosen, quality = choose_geocode_candidate(query_text, candidates)
            start_year, end_year = _year_bounds(group)
            tour = str(_mode_nonempty(group.get("tour", pd.Series(dtype=object))) or "BOTH").upper().replace("ATP", "MEN")
            surface = _mode_nonempty(group.get("surface", pd.Series(dtype=object)))
            indoor = _mode_nonempty(group.get("indoor", pd.Series(dtype=object)))

            if chosen is None:
                unresolved.append({
                    "canonical_event_id": event_id, "tourney_name": name, "query": query_text,
                    "start_year": start_year, "end_year": end_year, "reason": quality,
                })
                continue
            rows.append({
                "canonical_event_id": event_id,
                "canonical_name": name or query_text,
                "aliases": name,
                "tour": tour,
                "start_year": start_year,
                "end_year": end_year,
                "city": chosen.get("name"),
                "country": chosen.get("country"),
                "country_code": chosen.get("country_code"),
                "latitude": chosen.get("latitude"),
                "longitude": chosen.get("longitude"),
                "timezone": chosen.get("timezone"),
                "altitude_m": chosen.get("elevation"),
                "surface": surface,
                "indoor": indoor,
                "source_quality": quality,
                "geocode_query": query_text,
            })

    registry = pd.DataFrame(rows)
    report = {
        "events": int(df["stable_event_id"].nunique()),
        "resolved_events": int(len(registry)),
        "unresolved_events": int(len(unresolved)),
        "unresolved": unresolved,
    }
    return registry, report
