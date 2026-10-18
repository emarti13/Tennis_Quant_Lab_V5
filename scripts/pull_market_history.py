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
3. Backfill, with the time left, in one queue oldest first (OddsPapi drops history after
   4-9 months): older fixtures with no stored history (Pinnacle, Bet365, BetRivers), and
   Bet365 alone for the fixtures the January-August backfill holds without it. OddsPapi
   deletes history by date, so the first fixture that still has it is found with a few
   probe calls (skip_expired) and everything older is logged as not found.
/historical-odds is free but allows one call per 5 s and at most 3 books per call.

`--stored-chunks` derives price points from the January-August backfill already in git
(oddspapi_history/chunks; Pinnacle, BetRivers, DraftKings) without calling the API.

Writes market_history/fixtures/YYYY-MM.csv, market_history/price_points/YYYY-MM.csv and
market_history/pull_log.csv
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
from v5_market_results import INPLAY_DIR, append_inplay, inplay_record  # noqa: E402
from v5_market_history import close_cutoff  # noqa: E402
from v5_market_history import (  # noqa: E402
    DEFAULT_BOOKS, STORE_DIR, append_pull_log, append_store, fixture_record, load_pull_log, pending_fixtures,
    price_points,
)

API = "https://api.oddspapi.io/v4"
SPORT_ID = 12
META = BASE / "oddspapi_markets_tennis.json"
REGISTRY = BASE / "oddspapi_registry" / "fixtures.csv"
RUN_STATUS = STORE_DIR / "run_status.json"
STORED_BOOKS = "pinnacle,betrivers,draftkings"
EXTRA_BOOK = "bet365"     # added to the stored backfill's fixtures, one call each
WINDOW_DAYS = 9
DAILY_DAYS = 8
DISCOVERY_DAYS = 9   # one /fixtures call covers the whole daily window
BACKFILL_SINCE = "2026-01-01"
COOLDOWN = 5.1
NETWORK_PAUSE = 5.0   # first pause after a dropped connection (then 10 s, 20 s)
FLUSH_EVERY = 25
PROBE_WINDOW = 3     # consecutive fixtures tried at each probe point


class Api:
    def __init__(self, key: str):
        self.key, self.session = key, requests.Session()

    def get(self, endpoint: str, retries: int = 4, **params):
        """(status, body). Honours the per-endpoint cooldown (HTTP 429 retryMs). A dropped
        connection or timeout is retried with a growing pause; if it persists the call
        returns status 0 ("error" in the pull log, retried by a later run) instead of
        ending the run and losing everything collected before it."""
        for attempt in range(retries):
            try:
                r = self.session.get(f"{API}/{endpoint}", params={**params, "apiKey": self.key}, timeout=60)
            except requests.RequestException as exc:
                if attempt == retries - 1:
                    return 0, {"error": {"network": type(exc).__name__, "detail": str(exc)[:200]}}
                time.sleep(NETWORK_PAUSE * 2 ** attempt)
                continue
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


def skip_expired(api: Api, queue: list, window: int = PROBE_WINDOW) -> tuple[list, list[dict]]:
    """Drop the oldest fixtures whose history OddsPapi has already deleted, without a call per
    fixture. OddsPapi deletes by date (4-9 months back), so per book set, oldest first: probe
    the oldest fixture; if its history is gone, jump 1, 2, 4, ... fixtures on until a probe
    finds history, then halve the gap back to the first such point. A probe point has history
    if any of `window` consecutive fixtures from it does (one fixture can be missing for other
    reasons); an error other than "not found" counts as history (never drop on an error).
    Everything before that point is logged as expired; nothing after it is probed."""
    keep, expired = [], []
    groups: dict[str, list] = {}
    for item in sorted(queue, key=lambda item: str(item[1]["start_time_utc"])):
        groups.setdefault(item[2], []).append(item)
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for books, items in groups.items():
        found: dict[int, bool] = {}

        def has_history(j: int) -> bool:
            if j not in found:
                status, _ = api.get("historical-odds", fixtureId=items[j][1]["fixture_id"], bookmakers=books)
                time.sleep(COOLDOWN)
                found[j] = status != 404
            return found[j]

        def alive(i: int) -> bool:
            return i >= len(items) or any(has_history(j) for j in range(i, min(i + window, len(items))))

        if alive(0):
            keep += items
            continue
        lo, step = 0, 1                      # lo: a probe point known to have no history
        while not alive(lo + step):
            lo, step = lo + step, step * 2
        hi = min(lo + step, len(items))
        while hi - lo > 1:
            mid = (lo + hi) // 2
            lo, hi = (lo, mid) if alive(mid) else (mid, hi)
        first = str(items[hi][1]["start_time_utc"])[:10] if hi < len(items) else "none"
        keep += items[hi:]
        expired += [{"fixture_id": fx["fixture_id"], "start_time_utc": fx["start_time_utc"], "books": books,
                     "mode": mode, "status": "not_found", "http_status": 404, "quotes": 0, "point_rows": 0,
                     "pulled_utc": stamp, "detail": f"history expired: before the first fixture with history ({first})"}
                    for mode, fx, _ in items[:hi]]
    keep.sort(key=lambda item: str(item[1]["start_time_utc"]))
    return keep, expired


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
    # Bet365 for the fixtures the January-August backfill holds without it (user, 2026-10-16).
    extra = pending_fixtures(registry, log, now=now, since=args.backfill_since, books=EXTRA_BOOK,
                             relevant=relevant_fixture, only_stored=True) if not args.no_extra_book else registry.iloc[0:0]
    # One queue, oldest first: OddsPapi drops history after 4-9 months, whichever book it is for.
    older = sorted([("backfill", r, books) for r in backfill.to_dict("records")]
                   + [("bet365_backfill", r, EXTRA_BOOK) for r in extra.to_dict("records")],
                   key=lambda item: item[1]["start_time_utc"])
    older, expired = skip_expired(api, older)
    append_pull_log(expired, BASE)
    queue = [("daily", r, books) for r in daily.to_dict("records")] + older

    resolver = _resolver()
    raw_dir = STORE_DIR / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / f"{now:%Y-%m-%d_%H%M}.jsonl.gz"
    counts, entries, points, fixtures, inplay = {}, [], [], [], []
    with gzip.open(raw_path, "at", encoding="utf-8") as raw:
        for mode, fx, call_books in queue:
            if time.time() - started > args.max_minutes * 60:
                break
            stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
            status, body = api.get("historical-odds", fixtureId=fx["fixture_id"], bookmakers=call_books)
            entry = {"fixture_id": fx["fixture_id"], "start_time_utc": fx["start_time_utc"], "books": call_books,
                     "mode": mode, "http_status": status, "pulled_utc": stamp, "quotes": 0, "point_rows": 0, "detail": ""}
            if status == 200:
                raw.write(json.dumps({"fixture_id": fx["fixture_id"], "pulled_utc": stamp, "books": call_books,
                                      "historical_odds": body}, separators=(",", ":")) + "\n")
                pts = price_points(body, fx, meta)
                points.append(pts)
                fixtures.append(fixture_record(fx, identity=_identity(resolver, fx["fixture_id"]), pulled_utc=stamp))
                inplay.append(inplay_record(fx["fixture_id"], close_cutoff(fx)[0], body, f"oddspapi:{call_books}"))
                entry.update(status="ok", quotes=int(pts["quotes"].sum()) if len(pts) else 0, point_rows=len(pts))
            elif status == 404:
                entry["status"] = "not_found"
            else:
                entry.update(status="rate_limited" if status == 429 else "error", detail=json.dumps(body)[:200])
            entries.append(entry)
            counts[(mode, entry["status"])] = counts.get((mode, entry["status"]), 0) + 1
            if len(entries) >= FLUSH_EVERY:
                _flush(points, fixtures, entries, inplay)
            time.sleep(COOLDOWN)
    _flush(points, fixtures, entries, inplay)
    return {"quota_before": quota_before, "quota_after": _quota(api), "discovery": discovery,
            "queued": {"daily": len(daily), "backfill": len(backfill), "bet365_backfill": len(extra),
                       "expired_by_probe": len(expired)},
            "done": {f"{m}:{s}": n for (m, s), n in sorted(counts.items())},
            "raw_file": raw_path.name, "minutes": round((time.time() - started) / 60, 1)}


def _flush(points: list, fixtures: list, entries: list, inplay: list | None = None) -> None:
    """Store first, log second: a fixture is logged as done only once its prices are stored.
    In-play winner calls (v5_market_results) are stored alongside."""
    if fixtures:
        append_store(pd.concat(points, ignore_index=True) if points else pd.DataFrame(), fixtures, BASE)
    if inplay:
        append_inplay(inplay, BASE)
    append_pull_log(entries, BASE)
    for buf in (points, fixtures, entries, inplay if inplay is not None else []):
        buf.clear()


def _stored_inplay_done() -> set:
    paths = sorted((BASE / INPLAY_DIR).glob("*.csv"))
    return set(pd.concat([pd.read_csv(p, dtype=str, usecols=["fixture_id"]) for p in paths])["fixture_id"]) if paths else set()


def from_stored(spec: str) -> dict:
    """Price points from the January-August backfill files (no API calls), and the in-play
    winner call for every stored fixture that has none yet (also for fixtures whose prices
    were converted before in-play calls existed)."""
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
    entries, points, fixtures, inplay = [], [], [], []
    inplay_done = _stored_inplay_done()
    for i in wanted:
        path = BASE / "oddspapi_history" / "chunks" / f"history_chunk_{i:04d}.jsonl.gz"
        if not path.exists():
            continue
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            for line in fh:
                rec = json.loads(line)
                fid = (rec.get("fixture") or {}).get("fixtureId")
                if not fid:
                    continue
                if fid not in registry.index:
                    missing += 1
                    continue
                fx = registry.loc[fid].to_dict()
                if fid not in inplay_done:
                    inplay.append(inplay_record(fid, close_cutoff(fx)[0], rec.get("historical_odds"), "oddspapi_backfill_2026"))
                    inplay_done.add(fid)
                if fid in done:
                    if len(inplay) >= 500:
                        _flush([], [], [], inplay)
                    continue
                stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
                pts = price_points(rec.get("historical_odds"), fx, meta)
                points.append(pts)
                fixtures.append(fixture_record(fx, identity=_identity(resolver, fid), source="oddspapi_backfill_2026",
                                               pulled_utc=stamp))
                entries.append({"fixture_id": fid, "start_time_utc": fx["start_time_utc"], "books": STORED_BOOKS,
                                "mode": "stored", "status": "ok", "http_status": "", "quotes": int(pts["quotes"].sum()) if len(pts) else 0,
                                "point_rows": len(pts), "pulled_utc": stamp, "detail": path.name})
                done.add(fid)
                n += 1
                rows += len(pts)
                if len(entries) >= 500:
                    _flush(points, fixtures, entries, inplay)
        _flush(points, fixtures, entries, inplay)
        print(f"{path.name}: fixtures so far {n}, rows {rows}", flush=True)
    return {"stored_chunks": spec, "fixtures": n, "point_rows": rows, "not_in_registry": missing}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-minutes", type=float, default=27)
    ap.add_argument("--books", nargs="+", default=list(DEFAULT_BOOKS))
    ap.add_argument("--backfill-since", default=BACKFILL_SINCE)
    ap.add_argument("--discover-from", default=None)
    ap.add_argument("--no-discovery", action="store_true")
    ap.add_argument("--no-extra-book", action="store_true", help="skip the Bet365 backfill of stored fixtures")
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
