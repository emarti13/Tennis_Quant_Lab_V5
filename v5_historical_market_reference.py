from __future__ import annotations

import gzip
import json
from collections import Counter
from pathlib import Path
from typing import Iterator

DEFAULT_CHUNK_DIR = Path("oddspapi_history/chunks")


def history_chunk_paths(chunk_dir: Path = DEFAULT_CHUNK_DIR) -> list[Path]:
    """Return retained historical OddsPapi chunk files in deterministic order."""
    if not chunk_dir.exists():
        return []
    return sorted(
        (p for p in chunk_dir.iterdir() if p.is_file() and p.name.endswith(".jsonl.gz")),
        key=lambda p: p.name,
    )


def iter_history_records(chunk_dir: Path = DEFAULT_CHUNK_DIR) -> Iterator[dict]:
    """Yield valid JSON object records from retained gzip JSONL chunks."""
    for path in history_chunk_paths(chunk_dir):
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    item = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(item, dict):
                    yield item


def _fixture_id(record: dict) -> str | None:
    fixture = record.get("fixture")
    if not isinstance(fixture, dict):
        return None
    value = fixture.get("fixtureId")
    return None if value in (None, "") else str(value)


def profile_history_cache(chunk_dir: Path = DEFAULT_CHUNK_DIR) -> dict:
    """Profile retained cache coverage without assuming the nested odds schema."""
    chunks = history_chunk_paths(chunk_dir)
    top_level_keys: Counter[str] = Counter()
    requested_books: Counter[str] = Counter()
    fixture_ids: set[str] = set()
    payload_types: Counter[str] = Counter()
    valid_records = 0
    malformed_lines = 0
    non_object_lines = 0
    blank_lines = 0

    for path in chunks:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    blank_lines += 1
                    continue
                try:
                    item = json.loads(raw)
                except json.JSONDecodeError:
                    malformed_lines += 1
                    continue
                if not isinstance(item, dict):
                    non_object_lines += 1
                    continue

                valid_records += 1
                top_level_keys.update(item.keys())

                fid = _fixture_id(item)
                if fid is not None:
                    fixture_ids.add(fid)

                books = item.get("bookmakers_requested")
                if isinstance(books, list):
                    requested_books.update(str(book) for book in books if book not in (None, ""))

                payload = item.get("historical_odds")
                payload_types[type(payload).__name__] += 1

    return {
        "chunk_count": len(chunks),
        "chunk_files": [p.name for p in chunks],
        "valid_records": valid_records,
        "unique_fixture_ids": len(fixture_ids),
        "requested_book_counts": dict(sorted(requested_books.items())),
        "top_level_key_counts": dict(sorted(top_level_keys.items())),
        "historical_odds_payload_types": dict(sorted(payload_types.items())),
        "malformed_lines": malformed_lines,
        "non_object_lines": non_object_lines,
        "blank_lines": blank_lines,
    }


def normalize_historical_market_records(*_args, **_kwargs):
    """Phase-1 placeholder pending inspection of real retained payload shapes."""
    raise NotImplementedError(
        "Profile the retained OddsPapi cache before implementing canonical market normalization."
    )
