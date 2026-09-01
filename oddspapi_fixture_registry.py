from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

DEFAULT_REGISTRY = Path("oddspapi_registry/fixtures.csv")

FIELDS = [
    "fixture_id",
    "start_time_utc",
    "true_start_time_utc",
    "true_end_time_utc",
    "participant1_id",
    "participant1_name",
    "participant2_id",
    "participant2_name",
    "sport_id",
    "tournament_id",
    "tournament_name",
    "tournament_slug",
    "category_name",
    "category_slug",
    "season_id",
    "status_id",
    "status_name",
    "has_odds",
    "external_providers_json",
    "first_seen_utc",
    "last_seen_utc",
    "sources",
    "historical_status",
    "historical_books",
    "historical_checked_utc",
]


def utc_now_z() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _fixture_to_row(fixture: dict) -> dict[str, str]:
    return {
        "fixture_id": _text(fixture.get("fixtureId")),
        "start_time_utc": _text(fixture.get("startTime")),
        "true_start_time_utc": _text(fixture.get("trueStartTime")),
        "true_end_time_utc": _text(fixture.get("trueEndTime")),
        "participant1_id": _text(fixture.get("participant1Id")),
        "participant1_name": _text(fixture.get("participant1Name")),
        "participant2_id": _text(fixture.get("participant2Id")),
        "participant2_name": _text(fixture.get("participant2Name")),
        "sport_id": _text(fixture.get("sportId")),
        "tournament_id": _text(fixture.get("tournamentId")),
        "tournament_name": _text(fixture.get("tournamentName")),
        "tournament_slug": _text(fixture.get("tournamentSlug")),
        "category_name": _text(fixture.get("categoryName")),
        "category_slug": _text(fixture.get("categorySlug")),
        "season_id": _text(fixture.get("seasonId")),
        "status_id": _text(fixture.get("statusId")),
        "status_name": _text(fixture.get("statusName")),
        "has_odds": _text(fixture.get("hasOdds")),
        "external_providers_json": json.dumps(
            fixture.get("externalProviders") or {},
            sort_keys=True,
            separators=(",", ":"),
        ),
    }


def _merge_pipe_values(existing: str, incoming: Iterable[str] | str | None) -> str:
    values = set(filter(None, (existing or "").split("|")))
    if isinstance(incoming, str):
        values.update(filter(None, incoming.split("|")))
    elif incoming:
        values.update(str(x) for x in incoming if x)
    return "|".join(sorted(values))


class FixtureRegistry:
    def __init__(self, path: Path | str = DEFAULT_REGISTRY):
        self.path = Path(path)

    def read_rows(self) -> list[dict[str, str]]:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return []
        with self.path.open("r", newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def _write_rows(self, rows: Iterable[dict[str, str]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        ordered = sorted(rows, key=lambda r: (r.get("start_time_utc", ""), r.get("fixture_id", "")))
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with tmp.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
            writer.writeheader()
            for row in ordered:
                writer.writerow({field: row.get(field, "") for field in FIELDS})
        tmp.replace(self.path)

    def upsert(self, fixtures: Iterable[dict], observed_at: str | None = None, source: str = "unknown") -> dict:
        observed_at = observed_at or utc_now_z()
        by_id = {row.get("fixture_id", ""): row for row in self.read_rows() if row.get("fixture_id")}
        inserted = 0
        updated = 0

        for fixture in fixtures:
            incoming = _fixture_to_row(fixture)
            fixture_id = incoming["fixture_id"]
            if not fixture_id:
                continue

            current = by_id.get(fixture_id)
            if current is None:
                current = {field: "" for field in FIELDS}
                current.update(incoming)
                current["first_seen_utc"] = observed_at
                current["last_seen_utc"] = observed_at
                current["sources"] = _merge_pipe_values("", source)
                by_id[fixture_id] = current
                inserted += 1
                continue

            # Identity key and first-seen timestamp are immutable. All non-empty
            # upstream metadata may be refreshed as OddsPapi learns more.
            for field, value in incoming.items():
                if field != "fixture_id" and value != "":
                    current[field] = value
            current["last_seen_utc"] = observed_at
            current["sources"] = _merge_pipe_values(current.get("sources", ""), source)
            updated += 1

        self._write_rows(by_id.values())
        return {
            "inserted": inserted,
            "updated": updated,
            "registry_rows": len(by_id),
            "path": str(self.path),
        }

    def mark_historical(
        self,
        fixture_id: str,
        status: str,
        books: Iterable[str] | str | None = None,
        observed_at: str | None = None,
    ) -> None:
        rows = self.read_rows()
        by_id = {row.get("fixture_id", ""): row for row in rows if row.get("fixture_id")}
        if fixture_id not in by_id:
            raise KeyError(f"Fixture {fixture_id} is not present in registry")
        row = by_id[fixture_id]
        row["historical_status"] = status
        row["historical_books"] = _merge_pipe_values(row.get("historical_books", ""), books)
        row["historical_checked_utc"] = observed_at or utc_now_z()
        self._write_rows(by_id.values())


def seed_from_jsonl(
    registry: FixtureRegistry,
    source_path: Path | str,
    observed_at: str | None = None,
    source: str = "historical_seed",
) -> dict:
    source_path = Path(source_path)
    fixtures = []
    with source_path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                fixtures.append(json.loads(line))
    return registry.upsert(fixtures, observed_at=observed_at, source=source)


def ingest_json_file(
    registry: FixtureRegistry,
    source_path: Path | str,
    observed_at: str | None = None,
    source: str = "live",
) -> dict:
    payload = json.loads(Path(source_path).read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        fixtures = payload.get("fixtures") or payload.get("data") or []
    else:
        fixtures = payload
    if not isinstance(fixtures, list):
        raise ValueError(f"Expected fixture list in {source_path}")
    return registry.upsert(fixtures, observed_at=observed_at, source=source)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--registry", default=str(DEFAULT_REGISTRY))
    ap.add_argument("--seed-jsonl")
    ap.add_argument("--ingest-json")
    ap.add_argument("--source", default="manual")
    ap.add_argument("--observed-at")
    args = ap.parse_args()

    registry = FixtureRegistry(args.registry)
    if args.seed_jsonl:
        result = seed_from_jsonl(
            registry,
            args.seed_jsonl,
            observed_at=args.observed_at,
            source=args.source,
        )
    elif args.ingest_json:
        result = ingest_json_file(
            registry,
            args.ingest_json,
            observed_at=args.observed_at,
            source=args.source,
        )
    else:
        result = {"registry_rows": len(registry.read_rows()), "path": str(registry.path)}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
