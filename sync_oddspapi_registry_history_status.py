from __future__ import annotations

import argparse
import json
from pathlib import Path

from oddspapi_fixture_registry import FixtureRegistry, seed_from_jsonl, utc_now_z

DEFAULT_CHECKPOINT = Path("oddspapi_history/historical_checkpoint.json")
DEFAULT_FIXTURE_INDEX = Path("oddspapi_history/fixtures_2026.jsonl")
HISTORY_BOOKS = ["pinnacle", "betrivers", "draftkings"]
HISTORY_BOOKSET_KEY = ",".join(HISTORY_BOOKS)


def checkpoint_statuses(checkpoint: dict) -> dict[str, str]:
    statuses: dict[str, str] = {}

    # New checkpoint format: NOT_FOUND is terminal only for the exact bookmaker
    # set that was queried. Preserve that distinction in the registry metadata.
    terminal = checkpoint.get("terminal_not_found_by_bookset") or {}
    for fixture_id in terminal.get(HISTORY_BOOKSET_KEY, []):
        statuses[str(fixture_id)] = "NOT_FOUND"

    # Backward compatibility for checkpoints created before terminal statuses had
    # their own field.
    for fixture_id, error in (checkpoint.get("failed") or {}).items():
        text = str(error).lower()
        statuses[str(fixture_id)] = "NOT_FOUND" if "no historical odds found" in text else "ERROR"

    # A successfully cached response is authoritative if stale error metadata also
    # exists from an earlier attempt.
    for fixture_id in checkpoint.get("completed_fixture_ids", []):
        statuses[str(fixture_id)] = "CACHED"
    return statuses


def sync_registry(
    checkpoint_path: Path = DEFAULT_CHECKPOINT,
    fixture_index_path: Path = DEFAULT_FIXTURE_INDEX,
    registry: FixtureRegistry | None = None,
) -> dict:
    registry = registry or FixtureRegistry()
    observed_at = utc_now_z()

    seeded = None
    if not registry.path.exists() and fixture_index_path.exists():
        seeded = seed_from_jsonl(
            registry,
            fixture_index_path,
            observed_at=observed_at,
            source="2026_backfill",
        )

    if not checkpoint_path.exists():
        return {
            "seeded": seeded,
            "status_updates": 0,
            "registry_rows": len(registry.read_rows()),
        }

    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    statuses = checkpoint_statuses(checkpoint)
    if statuses:
        result = registry.mark_historical_many(
            statuses,
            books=HISTORY_BOOKS,
            observed_at=observed_at,
        )
    else:
        result = {"updated": 0, "registry_rows": len(registry.read_rows())}

    return {
        "seeded": seeded,
        "status_updates": result["updated"],
        "registry_rows": result["registry_rows"],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", default=str(DEFAULT_CHECKPOINT))
    ap.add_argument("--fixture-index", default=str(DEFAULT_FIXTURE_INDEX))
    args = ap.parse_args()
    result = sync_registry(Path(args.checkpoint), Path(args.fixture_index))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
