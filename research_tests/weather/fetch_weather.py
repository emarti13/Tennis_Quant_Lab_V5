"""Hourly historical weather at each tournament location, 2016-2025 (Open-Meteo archive, free).

Usage:  python research_tests/weather/fetch_weather.py EVENTS_CSV OUT_DIR

One request per location (rounded to 0.1 degree): apparent temperature, temperature, relative
humidity and 10 m wind speed, hourly in UTC. Writes OUT_DIR/<lat>_<lon>.csv.gz. Resumable.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd
import requests

URL = "https://archive-api.open-meteo.com/v1/archive"
VARS = "apparent_temperature,temperature_2m,relative_humidity_2m,wind_speed_10m"


def main() -> int:
    ev, out = pd.read_csv(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    locs = ev.dropna(subset=["latitude"])[["latitude", "longitude"]].round(1).drop_duplicates()
    s = requests.Session()
    for i, (lat, lon) in enumerate(locs.itertuples(index=False)):
        f = out / f"{lat:.1f}_{lon:.1f}.csv.gz"
        if f.exists():
            continue
        for attempt in range(6):
            try:
                r = s.get(URL, params={"latitude": lat, "longitude": lon, "start_date": "2016-01-01", "end_date": "2025-12-31",
                                       "hourly": VARS, "timezone": "UTC"}, timeout=120)
                if r.status_code == 200:
                    h = r.json()["hourly"]
                    pd.DataFrame(h).to_csv(f, index=False)
                    break
                time.sleep(float(r.headers.get("retry-after") or 2 ** attempt) + 1)
            except (requests.RequestException, ValueError, KeyError):
                time.sleep(2 ** attempt)
        if (i + 1) % 25 == 0:
            print(f"{i + 1}/{len(locs)}", flush=True)
        time.sleep(1.0)
    print(f"done: {len(list(out.glob('*.csv.gz')))} of {len(locs)} locations", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
