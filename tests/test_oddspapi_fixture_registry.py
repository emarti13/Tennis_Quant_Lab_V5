from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


class OddsPapiFixtureRegistryTests(unittest.TestCase):
    def test_upsert_never_drops_existing_ids_and_preserves_first_seen(self):
        from oddspapi_fixture_registry import FixtureRegistry

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "fixtures.csv"
            reg = FixtureRegistry(path)
            reg.upsert([{"fixtureId": "fx-old", "startTime": "2026-01-01T12:00:00Z", "participant1Name": "Player A", "participant2Name": "Player B", "tournamentId": 1, "tournamentName": "ATP Test", "categoryName": "ATP", "statusId": 0}], observed_at="2026-01-01T10:00:00Z", source="live")
            reg.upsert([
                {"fixtureId": "fx-new", "startTime": "2026-01-02T12:00:00Z", "participant1Name": "Player C", "participant2Name": "Player D", "tournamentId": 2, "tournamentName": "WTA Test", "categoryName": "WTA", "statusId": 0},
                {"fixtureId": "fx-old", "startTime": "2026-01-01T12:05:00Z", "participant1Name": "Player A", "participant2Name": "Player B", "tournamentId": 1, "tournamentName": "ATP Test Updated", "categoryName": "ATP", "statusId": 2},
            ], observed_at="2026-01-02T10:00:00Z", source="historical_discovery")

            rows = {r["fixture_id"]: r for r in reg.read_rows()}
            self.assertEqual(set(rows), {"fx-old", "fx-new"})
            self.assertEqual(rows["fx-old"]["first_seen_utc"], "2026-01-01T10:00:00Z")
            self.assertEqual(rows["fx-old"]["last_seen_utc"], "2026-01-02T10:00:00Z")
            self.assertEqual(rows["fx-old"]["status_id"], "2")
            self.assertEqual(rows["fx-old"]["tournament_name"], "ATP Test Updated")
            self.assertEqual(rows["fx-old"]["sources"], "historical_discovery|live")

    def test_marks_historical_cache_state_without_changing_fixture_identity(self):
        from oddspapi_fixture_registry import FixtureRegistry

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "fixtures.csv"
            reg = FixtureRegistry(path)
            reg.upsert([{"fixtureId": "fx1", "startTime": "2026-02-01T12:00:00Z", "participant1Name": "A", "participant2Name": "B", "tournamentId": 4, "tournamentName": "ATP Example", "categoryName": "ATP", "statusId": 2}], observed_at="2026-02-02T00:00:00Z", source="seed")
            reg.mark_historical("fx1", status="CACHED", books=["pinnacle", "betrivers"], observed_at="2026-09-01T12:00:00Z")
            row = reg.read_rows()[0]
            self.assertEqual(row["fixture_id"], "fx1")
            self.assertEqual(row["historical_status"], "CACHED")
            self.assertEqual(row["historical_books"], "betrivers|pinnacle")
            self.assertEqual(row["historical_checked_utc"], "2026-09-01T12:00:00Z")

    def test_bulk_historical_status_update_is_single_pass_and_preserves_rows(self):
        from oddspapi_fixture_registry import FixtureRegistry

        with tempfile.TemporaryDirectory() as td:
            reg = FixtureRegistry(Path(td) / "fixtures.csv")
            reg.upsert([
                {"fixtureId": "fx1", "participant1Name": "A", "participant2Name": "B"},
                {"fixtureId": "fx2", "participant1Name": "C", "participant2Name": "D"},
            ], observed_at="2026-01-01T00:00:00Z", source="seed")
            reg.mark_historical_many({"fx1": "CACHED", "fx2": "NOT_FOUND"}, books=["pinnacle", "betrivers", "draftkings"], observed_at="2026-09-01T13:00:00Z")
            rows = {r["fixture_id"]: r for r in reg.read_rows()}
            self.assertEqual(rows["fx1"]["historical_status"], "CACHED")
            self.assertEqual(rows["fx2"]["historical_status"], "NOT_FOUND")
            self.assertEqual(rows["fx2"]["historical_books"], "betrivers|draftkings|pinnacle")
            self.assertEqual(len(rows), 2)

    def test_checkpoint_statuses_distinguish_cached_not_found_and_error(self):
        from sync_oddspapi_registry_history_status import checkpoint_statuses

        checkpoint = {
            "completed_fixture_ids": ["fx1"],
            "failed": {
                "fx2": "OddsPapi HTTP 404: No historical odds found.",
                "fx3": "timeout",
            },
        }
        statuses = checkpoint_statuses(checkpoint)
        self.assertEqual(statuses, {"fx1": "CACHED", "fx2": "NOT_FOUND", "fx3": "ERROR"})

    def test_seed_jsonl_is_idempotent(self):
        from oddspapi_fixture_registry import FixtureRegistry, seed_from_jsonl

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "fixtures_2026.jsonl"
            source.write_text(
                json.dumps({"fixtureId": "fx1", "participant1Name": "A", "participant2Name": "B", "statusId": 2}) + "\n" +
                json.dumps({"fixtureId": "fx2", "participant1Name": "C", "participant2Name": "D", "statusId": 2}) + "\n",
                encoding="utf-8",
            )
            reg = FixtureRegistry(root / "registry.csv")
            seed_from_jsonl(reg, source, observed_at="2026-09-01T00:00:00Z", source="2026_backfill")
            seed_from_jsonl(reg, source, observed_at="2026-09-02T00:00:00Z", source="2026_backfill")
            rows = reg.read_rows()
            self.assertEqual(len(rows), 2)
            self.assertEqual({r["fixture_id"] for r in rows}, {"fx1", "fx2"})


if __name__ == "__main__":
    unittest.main()
