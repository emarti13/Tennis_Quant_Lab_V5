from __future__ import annotations

from pathlib import Path
import json

import numpy as np
import pandas as pd

from v5_tournament_registry import TournamentRegistry
from v5_weather_features import OpenMeteoArchiveClient


WEATHER_MAP = {
    "weather_temperature_c": "temperature_c",
    "weather_humidity_pct": "humidity_pct",
    "weather_wind_speed_kmh": "wind_speed_kmh",
    "weather_wind_gust_kmh": "wind_gust_kmh",
    "weather_precipitation_mm": "precipitation_mm",
    "weather_dew_point_c": "dew_point_c",
    "weather_pressure_hpa": "pressure_hpa",
    "weather_source_quality": "source_quality",
}


def _event_code(row: pd.Series) -> str | None:
    raw = str(row.get("tourney_id") or "").strip()
    if raw:
        parts = raw.split("-", 1)
        if len(parts) == 2 and parts[1]:
            return f"{str(row.get('tour') or 'MEN').upper().replace('ATP','MEN')}:{parts[1]}"
    raw2 = row.get("canonical_event_id")
    if pd.notna(raw2) and str(raw2).strip():
        return str(raw2).strip()
    return None


def _resolve_context(registry: TournamentRegistry, row: pd.Series, year: int):
    event_id = _event_code(row)
    tour = str(row.get("tour") or "MEN")
    if event_id:
        ctx = registry.resolve_event(event_id, tour, year)
        if ctx.canonical_event_id:
            return ctx
    return registry.resolve(str(row.get("tourney_name") or row.get("tournament") or ""), tour, year)


def attach_weather_cache(player_rows: pd.DataFrame, weather_cache: pd.DataFrame) -> pd.DataFrame:
    """Join event/date cached weather onto already venue-resolved player rows without guessing."""
    if player_rows is None or player_rows.empty:
        return player_rows.copy() if player_rows is not None else pd.DataFrame()
    out = player_rows.copy()
    if weather_cache is None or weather_cache.empty:
        for col in WEATHER_MAP:
            if col not in out.columns:
                out[col] = np.nan
        return out
    cache = weather_cache.copy()
    out["_weather_join_date"] = pd.to_datetime(out["match_date"], errors="coerce").dt.tz_localize(None).dt.normalize()
    cache["_weather_join_date"] = pd.to_datetime(cache["match_date"], errors="coerce").dt.tz_localize(None).dt.normalize()
    cache = cache.rename(columns={"canonical_event_id": "venue_event_id"})
    keep = ["venue_event_id", "_weather_join_date", *WEATHER_MAP.keys()]
    cache = cache[keep].drop_duplicates(["venue_event_id", "_weather_join_date"], keep="last")
    for col in WEATHER_MAP:
        if col in out.columns:
            out = out.drop(columns=[col])
    out = out.merge(cache, on=["venue_event_id", "_weather_join_date"], how="left", validate="many_to_one")
    return out.drop(columns=["_weather_join_date"])


def load_weather_cache(base_dir: str | Path = ".") -> pd.DataFrame:
    path = Path(base_dir) / "context_weather" / "weather_by_event_date.parquet"
    return pd.read_parquet(path) if path.exists() else pd.DataFrame()


def build_weather_cache(base_dir: str | Path = ".", *, client=None, years=(2025, 2026)) -> dict:
    """Fetch one historical weather range per resolved tournament-year and persist match-day rows."""
    base = Path(base_dir)
    match_path = base / "context_warehouse" / "matches.parquet"
    registry_path = base / "context_registry" / "tournaments.csv"
    if not match_path.exists():
        raise FileNotFoundError(f"Missing {match_path}")

    matches = pd.read_parquet(match_path).copy()
    if "match_date" not in matches.columns:
        raise ValueError("matches.parquet requires match_date")
    matches["match_date"] = pd.to_datetime(matches["match_date"], errors="coerce")
    matches = matches[matches["match_date"].notna()].copy()
    if years is not None:
        target = {int(y) for y in years}
        matches = matches[matches["match_date"].dt.year.isin(target)].copy()

    registry = TournamentRegistry.from_csv(registry_path)
    client = client or OpenMeteoArchiveClient(base / "context_cache" / "weather")
    groups: dict[tuple, dict] = {}
    unresolved = 0

    for _, row in matches.iterrows():
        date = pd.Timestamp(row["match_date"])
        year = int(date.year)
        ctx = _resolve_context(registry, row, year)
        if ctx.canonical_event_id is None or ctx.latitude is None or ctx.longitude is None:
            unresolved += 1
            continue
        key = (ctx.canonical_event_id, year)
        item = groups.setdefault(key, {
            "context": ctx,
            "dates": set(),
            "tour": str(row.get("tour") or ""),
            "tourney_name": str(row.get("tourney_name") or ""),
        })
        item["dates"].add(date.strftime("%Y-%m-%d"))

    output_rows: list[dict] = []
    request_errors: list[dict] = []
    for (event_id, year), item in sorted(groups.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        dates = sorted(item["dates"])
        ctx = item["context"]
        if not dates:
            continue
        try:
            weather = client.get_range(
                ctx.latitude,
                ctx.longitude,
                dates[0],
                dates[-1],
                timezone=ctx.timezone,
            )
        except Exception as exc:
            request_errors.append({"event_id": event_id, "year": year, "error": type(exc).__name__})
            weather = {}
        for day in dates:
            values = weather.get(day)
            if not values:
                continue
            row = {
                "canonical_event_id": event_id,
                "year": year,
                "tour": item["tour"],
                "tourney_name": item["tourney_name"],
                "match_date": pd.Timestamp(day),
                "venue_latitude": float(ctx.latitude),
                "venue_longitude": float(ctx.longitude),
                "venue_timezone": ctx.timezone,
            }
            for target, source in WEATHER_MAP.items():
                row[target] = values.get(source, np.nan)
            output_rows.append(row)

    columns = [
        "canonical_event_id", "year", "tour", "tourney_name", "match_date",
        "venue_latitude", "venue_longitude", "venue_timezone", *WEATHER_MAP.keys(),
    ]
    out = pd.DataFrame(output_rows, columns=columns)
    if not out.empty:
        out = out.sort_values(["year", "canonical_event_id", "match_date"]).drop_duplicates(
            ["canonical_event_id", "match_date"], keep="last"
        ).reset_index(drop=True)

    out_dir = base / "context_weather"
    out_dir.mkdir(parents=True, exist_ok=True)
    out.to_parquet(out_dir / "weather_by_event_date.parquet", index=False)
    report = {
        "requested_years": None if years is None else sorted(int(y) for y in years),
        "requested_event_years": int(len(groups)),
        "weather_rows": int(len(out)),
        "unresolved_matches": int(unresolved),
        "request_errors": request_errors,
    }
    (out_dir / "weather_cache_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> int:
    print(json.dumps(build_weather_cache("."), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
