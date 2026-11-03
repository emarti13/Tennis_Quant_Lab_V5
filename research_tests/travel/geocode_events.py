"""Location and time zone for each tournament name in the odds join (for the travel and weather tests).

Usage:  python research_tests/travel/geocode_events.py JOINED_PKL OUT_CSV

Cleans the name ("X challenger", "X WTA", "X 2" -> "X"), maps the events that are not city names
(Slams and a few others), and asks Open-Meteo's free geocoder for the most populated match. Writes
tournament, query, latitude, longitude, timezone, country_code. Resumable.
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

import pandas as pd
import requests

ALIASES = {"US Open": "New York", "French Open": "Paris", "Wimbledon": "London", "Australian Open": "Melbourne",
           "Hertogenbosch": "'s-Hertogenbosch", "Monte Carlo": "Monaco", "Indian Wells": "Indian Wells",
           "Laver Cup": "London", "Davis Cup": "Madrid", "United Cup": "Sydney", "ATP Cup": "Sydney",
           "Masters Cup ATP": "Turin", "Masters Cup WTA": "Riyadh", "Next Gen ATP Finals": "Jeddah",
           "Olympics": "Paris", "Queens": "London", "Queen's Club": "London", "Eastbourne": "Eastbourne",
           "Nur-Sultan": "Astana", "St. Petersburg": "Saint Petersburg", "Cagliari": "Cagliari",
           "Marrakech": "Marrakesh", "Great Ocean Road Open": "Melbourne", "Livesport Prague Open": "Prague",
           "Melbourne Summer Set": "Melbourne", "Alphen a/d Rijn": "Alphen aan den Rijn", "Luedenscheid": "Lüdenscheid",
           "Kachreti": "Tbilisi", "Las Franquesas del Valles": "Les Franqueses del Vallès", "St. Remy": "Saint-Rémy-de-Provence",
           "St. Tropez": "Saint-Tropez", "Sophia Antipolis": "Valbonne", "Salvador De Bahia": "Salvador",
           "Eckental": "Eckental", "Roseto Degli Abruzzi": "Roseto degli Abruzzi"}


def clean(name: str) -> str:
    s = str(name)
    m = re.search(r"\(([^)]+)\)", s)
    if m:
        s = m.group(1).replace("Melb.", "Melbourne").replace("Japan Open", "Tokyo")
    s = re.sub(r"^Olympics\s*-\s*", "", s)
    s = re.sub(r"\s+(chall\.|ITF)$", "", s, flags=re.I)
    s = re.sub(r"\s+(challenger|WTA|ATP)$", "", s, flags=re.I)
    s = re.sub(r"\s+\d+$", "", s)
    s = re.sub(r"\s+(challenger|WTA|ATP)$", "", s, flags=re.I)
    return ALIASES.get(s.strip(), ALIASES.get(str(name), s.strip()))


def main() -> int:
    joined_pkl, out = sys.argv[1], Path(sys.argv[2])
    j = pd.read_pickle(joined_pkl)
    names = sorted(j.loc[j["tour"].isin(["ATP", "WTA"]), "tournament"].dropna().unique())
    have = pd.read_csv(out) if out.exists() else pd.DataFrame(columns=["tournament"])
    have = have[have["timezone"].notna()] if "timezone" in have else have          # retry the misses
    done = set(have["tournament"])
    s, rows = requests.Session(), []
    for n in names:
        if n in done:
            continue
        q = clean(n)
        res = None
        for attempt in range(4):
            try:
                r = s.get("https://geocoding-api.open-meteo.com/v1/search", params={"name": q, "count": 5}, timeout=30)
                if r.status_code == 200:
                    res = r.json().get("results") or []
                    break
            except requests.RequestException:
                pass
            time.sleep(2 ** attempt)
        best = max(res, key=lambda x: x.get("population") or 0) if res else None
        rows.append({"tournament": n, "query": q, "latitude": best and best["latitude"], "longitude": best and best["longitude"],
                     "timezone": best and best.get("timezone"), "country_code": best and best.get("country_code")})
        time.sleep(0.15)
    pd.concat([have, pd.DataFrame(rows)], ignore_index=True).to_csv(out, index=False)
    d = pd.read_csv(out)
    print(f"{d['timezone'].notna().sum()} of {len(d)} tournaments located")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
