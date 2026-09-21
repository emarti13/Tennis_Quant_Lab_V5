from __future__ import annotations

import gzip
import json
from pathlib import Path

from v5_historical_market_reference import (
    history_chunk_paths,
    iter_history_records,
    profile_history_cache,
)


def _write_chunk(path: Path, rows: list[object], malformed: bool = False) -> None:
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
        if malformed:
            fh.write("{bad json\n")
        fh.write("\n")


def test_history_chunk_paths_are_deterministic(tmp_path: Path) -> None:
    _write_chunk(tmp_path / "history_chunk_0002.jsonl.gz", [])
    _write_chunk(tmp_path / "history_chunk_0001.jsonl.gz", [])
    (tmp_path / "ignore.txt").write_text("x", encoding="utf-8")

    assert [p.name for p in history_chunk_paths(tmp_path)] == [
        "history_chunk_0001.jsonl.gz",
        "history_chunk_0002.jsonl.gz",
    ]


def test_iter_history_records_reads_valid_object_rows_in_chunk_order(tmp_path: Path) -> None:
    _write_chunk(
        tmp_path / "history_chunk_0002.jsonl.gz",
        [{"fixture": {"fixtureId": "fx2"}, "historical_odds": []}],
    )
    _write_chunk(
        tmp_path / "history_chunk_0001.jsonl.gz",
        [{"fixture": {"fixtureId": "fx1"}, "historical_odds": {}}],
        malformed=True,
    )

    rows = list(iter_history_records(tmp_path))
    assert [r["fixture"]["fixtureId"] for r in rows] == ["fx1", "fx2"]


def test_profile_history_cache_reports_schema_and_coverage(tmp_path: Path) -> None:
    _write_chunk(
        tmp_path / "history_chunk_0001.jsonl.gz",
        [
            {
                "fixture": {"fixtureId": 101},
                "bookmakers_requested": ["pinnacle", "draftkings"],
                "historical_odds": {"prices": []},
            },
            {
                "fixture": {"fixtureId": 102},
                "bookmakers_requested": ["pinnacle", "betrivers"],
                "historical_odds": [],
            },
            {
                "fixture": {"fixtureId": 101},
                "bookmakers_requested": ["pinnacle"],
                "historical_odds": None,
            },
        ],
        malformed=True,
    )

    profile = profile_history_cache(tmp_path)

    assert profile["chunk_count"] == 1
    assert profile["valid_records"] == 3
    assert profile["unique_fixture_ids"] == 2
    assert profile["requested_book_counts"] == {
        "betrivers": 1,
        "draftkings": 1,
        "pinnacle": 3,
    }
    assert profile["top_level_key_counts"]["historical_odds"] == 3
    assert profile["historical_odds_payload_types"] == {
        "NoneType": 1,
        "dict": 1,
        "list": 1,
    }
    assert profile["malformed_lines"] == 1
    assert profile["blank_lines"] == 1
    assert profile["non_object_lines"] == 0
