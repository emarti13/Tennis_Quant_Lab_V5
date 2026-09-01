from __future__ import annotations

import argparse
import gzip
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from oddspapi_client import OddsPapiClient
from pull_oddspapi_quota_aware import relevant_fixture, quota_state

SPORT_ID = 12
START_UTC = datetime(2026, 1, 1, tzinfo=timezone.utc)
WINDOW_DAYS = 9
FIXTURE_COOLDOWN_SECONDS = 2.1
HISTORY_COOLDOWN_SECONDS = 5.1
HISTORY_BOOKS = "pinnacle,betrivers,draftkings"
PROTECTED_RESERVE = 50
DEFAULT_HISTORY_BATCH = 500

OUTDIR = Path("oddspapi_history")
FIXTURE_INDEX = OUTDIR / "fixtures_2026.jsonl"
CHECKPOINT = OUTDIR / "historical_checkpoint.json"
SUMMARY = OUTDIR / "backfill_summary.json"
COMPLETE_FLAG = OUTDIR / "BACKFILL_COMPLETE"
CHUNK_DIR = OUTDIR / "chunks"


def iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def iter_windows(start: datetime, end: datetime):
    cursor = start
    while cursor < end:
        nxt = min(cursor + timedelta(days=WINDOW_DAYS), end)
        yield cursor, nxt
        cursor = nxt


def load_fixture_index() -> list[dict]:
    if not FIXTURE_INDEX.exists():
        return []
    rows = []
    for line in FIXTURE_INDEX.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def save_fixture_index(rows: list[dict]) -> None:
    OUTDIR.mkdir(parents=True, exist_ok=True)
    ordered = sorted(rows, key=lambda r: (r.get("startTime") or "", r.get("fixtureId") or ""))
    FIXTURE_INDEX.write_text(
        "".join(json.dumps(r, separators=(",", ":"), ensure_ascii=False) + "\n" for r in ordered),
        encoding="utf-8",
    )


def discover_fixtures(client: OddsPapiClient, end_utc: datetime) -> dict:
    existing = {r.get("fixtureId"): r for r in load_fixture_index() if r.get("fixtureId")}
    windows = list(iter_windows(START_UTC, end_utc))
    quota_before = quota_state(client.account())

    needed_calls = len(windows)
    if quota_before["remaining"] - needed_calls < PROTECTED_RESERVE:
        raise RuntimeError(
            f"Refusing fixture discovery: {needed_calls} billable calls would reduce remaining quota "
            f"from {quota_before['remaining']} below protected reserve {PROTECTED_RESERVE}."
        )

    raw_count = 0
    relevant_count = 0
    for idx, (start, end) in enumerate(windows, 1):
        fixtures = client.fixtures(
            SPORT_ID,
            iso_z(start),
            iso_z(end),
            status_id=2,
            has_odds=True,
        )
        raw_count += len(fixtures)
        filtered = [f for f in fixtures if relevant_fixture(f)]
        relevant_count += len(filtered)
        for fixture in filtered:
            fid = fixture.get("fixtureId")
            if fid:
                existing[fid] = fixture
        print(json.dumps({
            "stage": "fixture_discovery",
            "window": idx,
            "windows_total": len(windows),
            "from": iso_z(start),
            "to": iso_z(end),
            "raw": len(fixtures),
            "relevant": len(filtered),
            "unique_so_far": len(existing),
        }))
        if idx < len(windows):
            time.sleep(FIXTURE_COOLDOWN_SECONDS)

    rows = list(existing.values())
    save_fixture_index(rows)
    quota_after = quota_state(client.account())
    return {
        "windows": len(windows),
        "raw_fixture_rows": raw_count,
        "relevant_fixture_rows_seen": relevant_count,
        "unique_relevant_fixtures": len(rows),
        "quota_before": quota_before,
        "quota_after": quota_after,
        "billable_calls_observed": quota_after["used"] - quota_before["used"],
    }


def load_checkpoint() -> dict:
    if not CHECKPOINT.exists():
        return {"completed_fixture_ids": [], "failed": {}, "next_chunk": 1}
    return json.loads(CHECKPOINT.read_text(encoding="utf-8"))


def save_checkpoint(checkpoint: dict) -> None:
    OUTDIR.mkdir(parents=True, exist_ok=True)
    CHECKPOINT.write_text(json.dumps(checkpoint, indent=2, sort_keys=True), encoding="utf-8")


def fetch_history_batch(client: OddsPapiClient, batch_size: int) -> dict:
    fixtures = load_fixture_index()
    checkpoint = load_checkpoint()
    completed = set(checkpoint.get("completed_fixture_ids", []))
    pending = [f for f in fixtures if f.get("fixtureId") and f.get("fixtureId") not in completed]
    selected = pending[:batch_size]

    if not selected:
        return {
            "selected": 0,
            "completed_total": len(completed),
            "fixture_total": len(fixtures),
            "remaining": 0,
            "done": True,
        }

    CHUNK_DIR.mkdir(parents=True, exist_ok=True)
    chunk_no = int(checkpoint.get("next_chunk", 1))
    chunk_path = CHUNK_DIR / f"history_chunk_{chunk_no:04d}.jsonl.gz"

    successes = []
    failures = {}
    with gzip.open(chunk_path, "wt", encoding="utf-8") as gz:
        for idx, fixture in enumerate(selected, 1):
            fid = fixture["fixtureId"]
            try:
                payload = client.historical_odds(fid, HISTORY_BOOKS)
                gz.write(json.dumps({
                    "fixture": fixture,
                    "bookmakers_requested": HISTORY_BOOKS.split(","),
                    "historical_odds": payload,
                }, separators=(",", ":"), ensure_ascii=False) + "\n")
                successes.append(fid)
                completed.add(fid)
            except Exception as exc:
                failures[fid] = str(exc)
            print(json.dumps({
                "stage": "historical_odds",
                "chunk": chunk_no,
                "item": idx,
                "batch_size": len(selected),
                "fixture_id": fid,
                "status": "SUCCESS" if fid in completed else "FAILED",
            }))
            if idx < len(selected):
                time.sleep(HISTORY_COOLDOWN_SECONDS)

    checkpoint["completed_fixture_ids"] = sorted(completed)
    prior_failed = checkpoint.get("failed", {})
    prior_failed.update(failures)
    for fid in successes:
        prior_failed.pop(fid, None)
    checkpoint["failed"] = prior_failed
    checkpoint["next_chunk"] = chunk_no + 1
    checkpoint["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
    save_checkpoint(checkpoint)

    remaining = max(0, len(fixtures) - len(completed))
    return {
        "selected": len(selected),
        "succeeded": len(successes),
        "failed": len(failures),
        "completed_total": len(completed),
        "fixture_total": len(fixtures),
        "remaining": remaining,
        "chunk": str(chunk_path),
        "done": remaining == 0,
    }


def write_summary(discovery: dict | None, history: dict | None) -> dict:
    OUTDIR.mkdir(parents=True, exist_ok=True)
    fixtures = load_fixture_index()
    checkpoint = load_checkpoint()
    completed = len(set(checkpoint.get("completed_fixture_ids", [])))
    remaining = max(0, len(fixtures) - completed)
    summary = {
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "fixture_index_rows": len(fixtures),
        "historical_completed": completed,
        "historical_remaining": remaining,
        "historical_failed_pending": len(checkpoint.get("failed", {})),
        "discovery_run": discovery,
        "history_run": history,
    }
    SUMMARY.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    if fixtures and remaining == 0:
        COMPLETE_FLAG.write_text(
            f"Completed {completed} fixtures at {summary['updated_at_utc']}\n",
            encoding="utf-8",
        )
    print(json.dumps(summary, indent=2))
    return summary


def already_complete() -> bool:
    if COMPLETE_FLAG.exists():
        return True
    fixtures = load_fixture_index()
    if not fixtures:
        return False
    checkpoint = load_checkpoint()
    completed = set(checkpoint.get("completed_fixture_ids", []))
    fixture_ids = {f.get("fixtureId") for f in fixtures if f.get("fixtureId")}
    return bool(fixture_ids) and fixture_ids.issubset(completed)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--discover", action="store_true")
    parser.add_argument("--history", action="store_true")
    parser.add_argument("--history-batch", type=int, default=DEFAULT_HISTORY_BATCH)
    parser.add_argument("--through", default=None, help="UTC date YYYY-MM-DD; default today")
    args = parser.parse_args()

    if not args.discover and not args.history:
        if already_complete():
            print(json.dumps({"status": "ALREADY_COMPLETE", "summary": str(SUMMARY)}))
            return
        args.discover = not FIXTURE_INDEX.exists()
        args.history = True

    if args.through:
        end_utc = datetime.fromisoformat(args.through).replace(tzinfo=timezone.utc) + timedelta(days=1)
    else:
        end_utc = datetime.now(timezone.utc)

    client = OddsPapiClient()
    discovery = discover_fixtures(client, end_utc) if args.discover else None
    history = fetch_history_batch(client, args.history_batch) if args.history else None
    write_summary(discovery, history)


if __name__ == "__main__":
    main()
