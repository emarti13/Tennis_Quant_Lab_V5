"""Hourly weather for the match days at each tournament location, from Meteostat's free bulk files.

Usage:  python research_tests/weather/fetch_meteostat.py JOINED_PKL EVENTS_CSV OUT_DIR

(Open-Meteo's archive limits a day's requests by their size; Meteostat publishes static per-station
files.) For each location (rounded to 0.1 degree) with ATP matches in the odds join: the nearest station
within 60 km whose hourly record covers 2016-2025, its hourly file, reduced to the days with matches
there. Feels-like temperature: the NOAA heat index when the temperature is 27 C or more, else the
temperature. Writes OUT_DIR/<lat>_<lon>.csv (time UTC, app_temp, wind_kmh) and OUT_DIR/stations.csv.
"""
from __future__ import annotations

import gzip
import io
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import requests

BULK = "https://bulk.meteostat.net/v2"


def heat_index(t_c, rh):
    t = np.asarray(t_c, float) * 9 / 5 + 32
    rh = np.asarray(rh, float)
    hi = (-42.379 + 2.04901523 * t + 10.14333127 * rh - 0.22475541 * t * rh - 6.83783e-3 * t * t
          - 5.481717e-2 * rh * rh + 1.22874e-3 * t * t * rh + 8.5282e-4 * t * rh * rh - 1.99e-6 * t * t * rh * rh)
    out = np.where(np.asarray(t_c, float) >= 27, (hi - 32) * 5 / 9, np.asarray(t_c, float))
    return np.where(np.isnan(rh), np.asarray(t_c, float), out)


def km(lat1, lon1, lat2, lon2):
    p = math.pi / 180
    a = 0.5 - math.cos((lat2 - lat1) * p) / 2 + math.cos(lat1 * p) * math.cos(lat2 * p) * (1 - math.cos((lon2 - lon1) * p)) / 2
    return 12742 * math.asin(math.sqrt(a))


def main() -> int:
    joined_pkl, events_csv, out = sys.argv[1], sys.argv[2], Path(sys.argv[3])
    out.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    st = json.loads(gzip.decompress(s.get(f"{BULK}/stations/lite.json.gz", timeout=120).content))
    st = [x for x in st if (x.get("inventory", {}).get("hourly", {}).get("start") or "9999") <= "2016-01-01"
          and (x.get("inventory", {}).get("hourly", {}).get("end") or "0000") >= "2025-06-01"]
    j = pd.read_pickle(joined_pkl)
    j = j[(j["tour"] == "ATP") & j["odds_level"].isin(["ATP main", "Challenger"])]
    ev = pd.read_csv(events_csv).set_index("tournament")[["latitude", "longitude"]].round(1)
    j = j.join(ev, on="tournament").dropna(subset=["latitude"])
    j["utc"] = pd.to_datetime(j["match_date_formatted"], errors="coerce") - pd.Timedelta(hours=9)
    j = j[j["utc"].dt.year >= 2016]
    chosen = []
    for (lat, lon), g in j.groupby(["latitude", "longitude"]):
        f = out / f"{lat:.1f}_{lon:.1f}.csv"
        if f.exists():
            continue
        best = min(st, key=lambda x: km(lat, lon, x["location"]["latitude"], x["location"]["longitude"]))
        d = km(lat, lon, best["location"]["latitude"], best["location"]["longitude"])
        if d > 60:
            chosen.append({"lat": lat, "lon": lon, "station": None, "km": round(d, 1)})
            continue
        r = s.get(f"{BULK}/hourly/{best['id']}.csv.gz", timeout=300)
        if r.status_code != 200:
            chosen.append({"lat": lat, "lon": lon, "station": best["id"], "km": round(d, 1), "error": r.status_code})
            continue
        w = pd.read_csv(io.BytesIO(gzip.decompress(r.content)), header=None,
                        names=["date", "hour", "temp", "dwpt", "rhum", "prcp", "snow", "wdir", "wspd", "wpgt", "pres", "tsun", "coco"])
        days = set(g["utc"].dt.strftime("%Y-%m-%d"))
        w = w[w["date"].isin(days)]
        w["time"] = pd.to_datetime(w["date"]) + pd.to_timedelta(w["hour"], unit="h")
        pd.DataFrame({"time": w["time"], "app_temp": heat_index(w["temp"], w["rhum"]).round(1), "wind_kmh": w["wspd"]}).to_csv(f, index=False)
        chosen.append({"lat": lat, "lon": lon, "station": best["id"], "km": round(d, 1), "hours": len(w)})
        if len(chosen) % 25 == 0:
            print(f"{len(chosen)} locations", flush=True)
    st_path = out / "stations.csv"
    pd.concat([pd.read_csv(st_path)] if st_path.exists() else [] + [pd.DataFrame(chosen)], ignore_index=True).to_csv(st_path, index=False)
    print(f"done: {len(list(out.glob('*_*.csv')))} location files", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
