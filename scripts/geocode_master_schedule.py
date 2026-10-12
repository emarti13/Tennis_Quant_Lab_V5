"""Fill the master schedule's location cache from Open-Meteo's free geocoding API.

Usage:
    python scripts/geocode_master_schedule.py \
        --sheet context_registry/master_schedule/master_schedule_2026.csv

Looks up each distinct (city, state, country) once and stores the geocoder's candidate
results in context_registry/master_schedule/geocode_cache.csv. Cities already in the
cache are not looked up again, so reruns need no network. Choosing a result happens in
v5_tournament_identity.enrich_locations (country must match; state too when given), so
the cache keeps every candidate and the choice can be re-made without new requests.
Requires geocoding-api.open-meteo.com in the environment's allowed domains.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from v5_tournament_identity import country_iso2, load_countries, load_master_schedule, location_key  # noqa: E402

API = "https://geocoding-api.open-meteo.com/v1/search"
KEEP = ("id", "name", "latitude", "longitude", "elevation", "timezone", "country_code",
        "admin1", "admin2", "population", "feature_code")
CACHE_COLUMNS = ["location_key", "city", "state", "country_iso2", "query", "fetched_utc", "results_json"]


def fetch(city: str, attempts: int = 5) -> list[dict]:
    last = None
    for i in range(attempts):
        try:
            r = requests.get(API, params={"name": city, "count": 20, "language": "en", "format": "json"}, timeout=8)
            r.raise_for_status()
            return [{k: x.get(k) for k in KEEP} for x in r.json().get("results", []) or []]
        except (requests.RequestException, ValueError) as exc:
            last = exc
            time.sleep(0.5 + i)
    raise RuntimeError(f"Geocoding failed for {city!r}: {last}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet", required=True)
    ap.add_argument("--cache", default="context_registry/master_schedule/geocode_cache.csv")
    ap.add_argument("--pause", type=float, default=0.3, help="Seconds between requests (be polite to a free API).")
    ap.add_argument("--aliases", default="context_registry/master_schedule/location_aliases.csv",
                    help="city,country_iso2 -> query name for cities the geocoder spells differently.")
    args = ap.parse_args()

    editions, _ = load_master_schedule(args.sheet)
    countries = load_countries()
    cache_path = Path(args.cache)
    cache = pd.read_csv(cache_path, dtype=str, keep_default_na=False) if cache_path.exists() else pd.DataFrame(columns=CACHE_COLUMNS)
    aliases = pd.read_csv(args.aliases, dtype=str, keep_default_na=False) if Path(args.aliases).exists() else pd.DataFrame(columns=["city", "country_iso2", "query"])
    alias = {(r["city"], r["country_iso2"]): r["query"] for _, r in aliases.iterrows()}
    # Look up again: locations never cached, cached with no results, or whose alias changed.
    alias_changed = pd.Series([alias.get((c, i), c) != q for c, i, q in zip(cache["city"], cache["country_iso2"], cache["query"])],
                              index=cache.index, dtype=bool)
    stale = cache[(cache["results_json"] == "[]") | alias_changed]
    cache = cache.drop(stale.index)
    known = set(cache["location_key"])

    wanted = {location_key(e["city"], e["state"], country_iso2(e, countries)) for _, e in editions.iterrows()}
    unused = ~cache["location_key"].isin(wanted)
    if unused.any():  # e.g. a city whose State was corrected in the sheet
        print(f"Dropping {int(unused.sum())} cached locations no longer in the sheet.")
        cache = cache[~unused]
        known = set(cache["location_key"])

    todo = {}
    for _, e in editions.iterrows():
        iso2 = country_iso2(e, countries)
        key = location_key(e["city"], e["state"], iso2)
        if key not in known:
            todo[key] = (e["city"], e["state"], iso2)

    def save(cache: pd.DataFrame, rows: list[dict]) -> pd.DataFrame:
        if rows:
            cache = pd.concat([cache, pd.DataFrame(rows)], ignore_index=True)
            cache = cache.sort_values("location_key").reset_index(drop=True)
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache.to_csv(cache_path, index=False, encoding="utf-8")
        return cache

    rows, failed, added = [], [], 0
    for n, (key, (city, state, iso2)) in enumerate(sorted(todo.items()), 1):
        try:
            query = alias.get((city, iso2), city)
            results = fetch(query)
        except RuntimeError as exc:
            failed.append(city)  # left out of the cache, so the next run retries it
            print(f"  skipped {city!r}: {exc}", flush=True)
            continue
        rows.append({"location_key": key, "city": city, "state": state, "country_iso2": iso2, "query": query,
                     "fetched_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     "results_json": json.dumps(results, ensure_ascii=False)})
        if len(rows) >= 10:  # save progress so a long run is never lost
            added += len(rows)
            cache, rows = save(cache, rows), []
            print(f"  {n}/{len(todo)} looked up", flush=True)
        time.sleep(args.pause)
    added += len(rows)
    cache = save(cache, rows)
    if unused.any() and not rows:
        cache.to_csv(cache_path, index=False, encoding="utf-8")
    if failed:
        print(f"Not looked up this run (retry later): {', '.join(failed)}")
    print(f"Cache {cache_path}: {len(cache)} locations ({added} new).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
