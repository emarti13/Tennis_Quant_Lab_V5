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
            has_odds=None,
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


def is_historical_not_found(error: object) -> bool:
    text = str(error).lower()
    return "no historical odds found" in text or ("not_found" in text and "historical" in text)


def terminal_not_found_ids(checkpoint: dict, books: str = HISTORY_BOOKS) -> set[str]:
    explicit = checkpoint.get("terminal_not_found_by_bookset") or {}
    ids = {str(fid) for fid in explicit.get(books, [])}

    # Migrate the legacy checkpoint in place logically: before terminal status had
    # its own field, NOT_FOUND responses lived under `failed`. They were generated
    # with HISTORY_BOOKS, so they are terminal only for that exact book set.
    if books == HISTORY_BOOKS:
        for fixture_id, error in (checkpoint.get("failed") or {}).items():
            if is_historical_not_found(error):
                ids.add(str(fixture_id))
    return ids


def pending_fixtures(fixtures: list[dict], checkpoint: dict, books: str = HISTORY_BOOKS) -> list[dict]:
    completed = {str(fid) for fid in checkpoint.get("completed_fixture_ids", [])}
    unavailable = terminal_not_found_ids(checkpoint, books=books)
    resolved = completed | unavailable
    return [
        fixture for fixture in fixtures
        if fixture.get("fixtureId") and str(fixture.get("fixtureId")) not in resolved
    ]


def fetch_history_batch(client: OddsPapiClient, batch_size: int) -> dict:
    fixtures = load_fixture_index()
    checkpoint = load_checkpoint()
    completed = {str(fid) for fid in checkpoint.get("completed_fixture_ids", [])}
    terminal_not_found = terminal_not_found_ids(checkpoint)
    selected = pending_fixtures(fixtures, checkpoint)[:batch_size]

    if not selected:
        resolved_total = len(completed | terminal_not_found)
        return {
            "selected": 0,
            "completed_total": len(completed),
            "not_found_total": len(terminal_not_found),
            "resolved_total": resolved_total,
            "fixture_total": len(fixtures),
            "remaining": max(0, len(fixtures) - resolved_total),
            "done": resolved_total >= len(fixtures),
        }

    CHUNK_DIR.mkdir(parents=True, exist_ok=True)
    chunk_no = int(checkpoint.get("next_chunk", 1))
    chunk_path = CHUNK_DIR / f"history_chunk_{chunk_no:04d}.jsonl.gz"

    successes: list[str] = []
    retryable_failures: dict[str, str] = {}
    newly_not_found: set[str] = set()
    with gzip.open(chunk_path, "wt", encoding="utf-8") as gz:
        for idx, fixture in enumerate(selected, 1):
            fid = str(fixture["fixtureId"])
            status = "FAILED_RETRYABLE"
            try:
                payload = client.historical_odds(fid, HISTORY_BOOKS)
                gz.write(json.dumps({
                    "fixture": fixture,
                    "bookmakers_requested": HISTORY_BOOKS.split(","),
                    "historical_odds": payload,
                }, separators=(",", ":"), ensure_ascii=False) + "\n")
                successes.append(fid)
                completed.add(fid)
                status = "SUCCESS"
            except Exception as exc:
                if is_historical_not_found(exc):
                    newly_not_found.add(fid)
                    terminal_not_found.add(fid)
                    status = "NOT_FOUND_TERMINAL"
                else:
                    retryable_failures[fid] = str(exc)
            print(json.dumps({
                "stage": "historical_odds",
                "chunk": chunk_no,
                "item": idx,
                "batch_size": len(selected),
                "fixture_id": fid,
                "status": status,
            }))
            if idx < len(selected):
                time.sleep(HISTORY_COOLDOWN_SECONDS)

    checkpoint["completed_fixture_ids"] = sorted(completed)
    terminal_by_bookset = checkpoint.setdefault("terminal_not_found_by_bookset", {})
    terminal_by_bookset[HISTORY_BOOKS] = sorted(terminal_not_found)

    prior_failed = dict(checkpoint.get("failed") or {})
    # Legacy NOT_FOUND entries and successful IDs are no longer retryable failures.
    for fid in terminal_not_found | set(successes):
        prior_failed.pop(fid, None)
    prior_failed.update(retryable_failures)
    checkpoint["failed"] = prior_failed
    checkpoint["next_chunk"] = chunk_no + 1
    checkpoint["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
    save_checkpoint(checkpoint)

    resolved = completed | terminal_not_found
    remaining = max(0, len(fixtures) - len(resolved))
    return {
        "selected": len(selected),
        "succeeded": len(successes),
        "not_found": len(newly_not_found),
        "failed_retryable": len(retryable_failures),
        "completed_total": len(completed),
        "not_found_total": len(terminal_not_found),
        "resolved_total": len(resolved),
        "fixture_total": len(fixtures),
        "remaining": remaining,
        "chunk": str(chunk_path),
        "done": remaining == 0,
    }


def write_summary(discovery: dict | None, history: dict | None) -> dict:
    OUTDIR.mkdir(parents=True, exist_ok=True)
    fixtures = load_fixture_index()
    checkpoint = load_checkpoint()
    completed_ids = {str(fid) for fid in checkpoint.get("completed_fixture_ids", [])}
    not_found_ids = terminal_not_found_ids(checkpoint)
    resolved_ids = completed_ids | not_found_ids
    remaining = max(0, len(fixtures) - len(resolved_ids))
    summary = {
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "fixture_index_rows": len(fixtures),
        "historical_cached": len(completed_ids),
        "historical_not_found_for_bookset": len(not_found_ids),
        "historical_resolved": len(resolved_ids),
        "historical_remaining": remaining,
        "historical_failed_retryable": len(checkpoint.get("failed", {})),
        "historical_bookset": HISTORY_BOOKS,
        "discovery_run": discovery,
        "history_run": history,
    }
    SUMMARY.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    if fixtures and remaining == 0:
        COMPLETE_FLAG.write_text(
            f"Resolved {len(resolved_ids)} fixtures at {summary['updated_at_utc']} "
            f"({len(completed_ids)} cached, {len(not_found_ids)} not found for {HISTORY_BOOKS})\n",
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
    completed = {str(fid) for fid in checkpoint.get("completed_fixture_ids", [])}
    unavailable = terminal_not_found_ids(checkpoint)
    fixture_ids = {str(f.get("fixtureId")) for f in fixtures if f.get("fixtureId")}
    return bool(fixture_ids) and fixture_ids.issubset(completed | unavailable)


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
