"""Fill the market price store (v5_market_history) from OddsPapi /historical-odds.

Usage:
  python scripts/pull_market_history.py [--max-minutes 22] [--discover-from YYYY-MM-DD]
  python scripts/pull_market_history.py --stored-chunks 1-30      # no API calls

Each run (spec docs/superpowers/specs/2026-10-16-market-data-layer-design.md §2.2, §5):
1. Discovery: one /fixtures call per 9-day window (these do count against the request
   quota) adds finished fixtures and their true start times to oddspapi_registry/fixtures.csv.
   Daily: the last 9 days. `--discover-from` widens it once (the September gap). Skipped
   when it would leave fewer than 50 requests for live pricing.
2. Daily: fixtures that started in the last 8 days and have no finished pull (one
   without a reported true start waits up to 3 days for it).
3. Backfill, with the time left: older fixtures with no stored history, oldest first,
   because OddsPapi drops history after 4-9 months.
/historical-odds is free but allows one call per 5 s and at most 3 books per call.

`--stored-chunks` derives price points from the January-August backfill already in git
(oddspapi_history/chunks; Pinnacle, BetRivers, DraftKings) without calling the API.

Writes market_history/price_points/YYYY-MM.csv and market_history/pull_log.csv
(append-only), market_history/run_status.json, and raw payloads to market_history/raw/
(not committed; the workflow uploads them to a monthly GitHub release).
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
os.chdir(BASE)
from oddspapi_fixture_registry import FixtureRegistry  # noqa: E402
from pull_oddspapi_quota_aware import RESEARCH_PROTECTED_RESERVE, quota_state, relevant_fixture  # noqa: E402
from v5_fixture_resolution import FixtureResolver  # noqa: E402
from v5_market_history import (  # noqa: E402
    DEFAULT_BOOKS, STORE_DIR, append_points, append_pull_log, load_pull_log, pending_fixtures, price_points,
)

API = "https://api.oddspapi.io/v4"
SPORT_ID = 12
META = BASE / "oddspapi_markets_tennis.json"
REGISTRY = BASE / "oddspapi_registry" / "fixtures.csv"
RUN_STATUS = STORE_DIR / "run_status.json"
STORED_BOOKS = "pinnacle,betrivers,draftkings"
WINDOW_DAYS = 9
DAILY_DAYS = 8
DISCOVERY_DAYS = 9   # one /fixtures call covers the whole daily window
BACKFILL_SINCE = "2026-01-01"
COOLDOWN = 5.1
FLUSH_EVERY = 25


class Api:
    def __init__(self, key: str):
        self.key, self.session = key, requests.Session()

    def get(self, endpoint: str, retries: int = 4, **params):
        """(status, body). Honours the per-endpoint cooldown (HTTP 429 retryMs)."""
        for _ in range(retries):
            r = self.session.get(f"{API}/{endpoint}", params={**params, "apiKey": self.key}, timeout=60)
            try:
                body = r.json()
            except ValueError:
                body = {"text": r.text[:300]}
            if r.status_code != 429:
                return r.status_code, body
            wait = ((body.get("error") or {}) if isinstance(body, dict) else {}).get("retryMs") or 5000
            time.sleep(wait / 1000 + 0.5)
        return r.status_code, body


def _quota(api: Api) -> dict | None:
    status, body = api.get("account")
    try:
        return quota_state(body) if status == 200 else None
    except RuntimeError:
        return None


def discover(api: Api, start: datetime, end: datetime, quota: dict | None) -> dict:
    windows = []
    cursor = start
    while cursor < end:
        windows.append((cursor, min(cursor + timedelta(days=WINDOW_DAYS), end)))
        cursor = windows[-1][1]
    if quota is None or quota["remaining"] - len(windows) < RESEARCH_PROTECTED_RESERVE:
        return {"skipped": "quota unknown or too low to protect live pricing", "windows": len(windows)}
    seen = []
    for a, b in windows:
        status, body = api.get("fixtures", sportId=SPORT_ID, statusId=2, **{
            "from": a.strftime("%Y-%m-%dT%H:%M:%SZ"), "to": b.strftime("%Y-%m-%dT%H:%M:%SZ"), "language": "en"})
        if status == 200 and isinstance(body, list):
            seen += [fx for fx in body if relevant_fixture(fx)]
        time.sleep(2.1)
    result = FixtureRegistry(REGISTRY).upsert(seen, source="history_discovery") if seen else {"inserted": 0, "updated": 0}
    return {"windows": len(windows), "relevant_seen": len(seen), **result}


def _resolver():
    try:
        return FixtureResolver.from_repo(BASE)
    except Exception as exc:  # identity is recorded per row; a broken table must not stop collection
        print(f"identity tables unavailable: {exc!r}")
        return None


def _identity(resolver, fid: str) -> dict:
    if resolver is None:
        return {"resolution": "RESOLVER_UNAVAILABLE"}
    try:
        return resolver.identify(fid)
    except Exception as exc:
        return {"resolution": f"ERROR:{type(exc).__name__}"}


def pull(args) -> dict:
    key = os.environ.get("ODDSPAPI_KEY")
    if not key:
        raise SystemExit("ODDSPAPI_KEY is not set")
    if not META.exists():
        raise SystemExit(f"{META.name} is missing: the workflow restores it from the Actions cache")
    meta = json.loads(META.read_text(encoding="utf-8"))
    api, now, books = Api(key), datetime.now(timezone.utc), ",".join(args.books)
    started = time.time()
    quota_before = _quota(api)
    disc_from = datetime.fromisoformat(args.discover_from).replace(tzinfo=timezone.utc) if args.discover_from \
        else now - timedelta(days=DISCOVERY_DAYS)
    discovery = discover(api, disc_from, now, quota_before) if not args.no_discovery else {"skipped": "--no-discovery"}

    registry = pd.read_csv(REGISTRY, dtype=str, keep_default_na=False)
    log = load_pull_log(BASE)
    daily = pending_fixtures(registry, log, now=now, since=now - timedelta(days=DAILY_DAYS), books=books,
                             relevant=relevant_fixture)
    backfill = pending_fixtures(registry, log, now=now, since=args.backfill_since, books=books,
                                relevant=relevant_fixture, skip_stored=True)
    backfill = backfill[~backfill["fixture_id"].isin(daily["fixture_id"])]
    queue = [("daily", r) for r in daily.to_dict("records")] + [("backfill", r) for r in backfill.to_dict("records")]

    resolver = _resolver()
    raw_dir = STORE_DIR / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / f"{now:%Y-%m-%d_%H%M}.jsonl.gz"
    counts, entries, points = {}, [], []
    with gzip.open(raw_path, "at", encoding="utf-8") as raw:
        for mode, fx in queue:
            if time.time() - started > args.max_minutes * 60:
                break
            stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
            status, body = api.get("historical-odds", fixtureId=fx["fixture_id"], bookmakers=books)
            entry = {"fixture_id": fx["fixture_id"], "start_time_utc": fx["start_time_utc"], "books": books,
                     "mode": mode, "http_status": status, "pulled_utc": stamp, "quotes": 0, "point_rows": 0, "detail": ""}
            if status == 200:
                raw.write(json.dumps({"fixture_id": fx["fixture_id"], "pulled_utc": stamp, "books": books,
                                      "historical_odds": body}, separators=(",", ":")) + "\n")
                pts = price_points(body, fx, meta, identity=_identity(resolver, fx["fixture_id"]), pulled_utc=stamp)
                points.append(pts)
                entry.update(status="ok", quotes=int(pts["quotes"].sum()) if len(pts) else 0, point_rows=len(pts))
            elif status == 404:
                entry["status"] = "not_found"
            else:
                entry.update(status="rate_limited" if status == 429 else "error", detail=json.dumps(body)[:200])
            entries.append(entry)
            counts[(mode, entry["status"])] = counts.get((mode, entry["status"]), 0) + 1
            if len(entries) >= FLUSH_EVERY:
                _flush(points, entries)
            time.sleep(COOLDOWN)
    _flush(points, entries)
    return {"quota_before": quota_before, "quota_after": _quota(api), "discovery": discovery,
            "queued": {"daily": len(daily), "backfill": len(backfill)},
            "done": {f"{m}:{s}": n for (m, s), n in sorted(counts.items())},
            "raw_file": raw_path.name, "minutes": round((time.time() - started) / 60, 1)}


def _flush(points: list, entries: list) -> None:
    if points:
        append_points(pd.concat(points, ignore_index=True), BASE)
    append_pull_log(entries, BASE)
    points.clear()
    entries.clear()


def from_stored(spec: str) -> dict:
    """Price points from the January-August backfill files (no API calls)."""
    if not META.exists():
        raise SystemExit(f"{META.name} is missing")
    meta = json.loads(META.read_text(encoding="utf-8"))
    lo, _, hi = spec.partition("-")
    wanted = range(int(lo), int(hi or lo) + 1)
    registry = pd.read_csv(REGISTRY, dtype=str, keep_default_na=False).set_index("fixture_id", drop=False)
    log = load_pull_log(BASE)
    done = set(log.loc[(log["books"] == STORED_BOOKS) & log["status"].isin({"ok", "not_found"}), "fixture_id"])
    resolver = _resolver()
    n = rows = missing = 0
    entries, points = [], []
    for i in wanted:
        path = BASE / "oddspapi_history" / "chunks" / f"history_chunk_{i:04d}.jsonl.gz"
        if not path.exists():
            continue
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            for line in fh:
                rec = json.loads(line)
                fid = (rec.get("fixture") or {}).get("fixtureId")
                if not fid or fid in done:
                    continue
                if fid not in registry.index:
                    missing += 1
                    continue
                fx = registry.loc[fid].to_dict()
                stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
                pts = price_points(rec.get("historical_odds"), fx, meta, identity=_identity(resolver, fid),
                                   source="oddspapi_backfill_2026", pulled_utc=stamp)
                points.append(pts)
                entries.append({"fixture_id": fid, "start_time_utc": fx["start_time_utc"], "books": STORED_BOOKS,
                                "mode": "stored", "status": "ok", "http_status": "", "quotes": int(pts["quotes"].sum()) if len(pts) else 0,
                                "point_rows": len(pts), "pulled_utc": stamp, "detail": path.name})
                done.add(fid)
                n += 1
                rows += len(pts)
                if len(entries) >= 500:
                    _flush(points, entries)
        _flush(points, entries)
        print(f"{path.name}: fixtures so far {n}, rows {rows}", flush=True)
    return {"stored_chunks": spec, "fixtures": n, "point_rows": rows, "not_in_registry": missing}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-minutes", type=float, default=22)
    ap.add_argument("--books", nargs="+", default=list(DEFAULT_BOOKS))
    ap.add_argument("--backfill-since", default=BACKFILL_SINCE)
    ap.add_argument("--discover-from", default=None)
    ap.add_argument("--no-discovery", action="store_true")
    ap.add_argument("--stored-chunks", default=None, help="e.g. 1-30: convert stored backfill files, no API")
    args = ap.parse_args()
    if len(args.books) > 3:
        raise SystemExit("OddsPapi allows at most 3 books per /historical-odds call")
    result = from_stored(args.stored_chunks) if args.stored_chunks else pull(args)
    result["run_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    (BASE / RUN_STATUS).parent.mkdir(parents=True, exist_ok=True)
    (BASE / RUN_STATUS).write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
