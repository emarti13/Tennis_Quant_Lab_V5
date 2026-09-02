import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from context_warehouse.io import write_warehouse
from context_warehouse.normalize import build_player_match_rows, canonicalize_matches


class CanonicalWarehouseContractTests(unittest.TestCase):
    def sample_source(self):
        return pd.DataFrame(
            [
                {
                    "tourney_id": "2026-001",
                    "tourney_name": "Example Open",
                    "tourney_date": 20260115,
                    "match_num": 7,
                    "round": "R32",
                    "surface": "hard",
                    "winner_id": 101,
                    "loser_id": 202,
                    "winner_name": "Player One",
                    "loser_name": "Player Two",
                    "winner_hand": "R",
                    "loser_hand": "L",
                    "winner_ht": 188,
                    "loser_ht": 191,
                    "winner_age": 27.4,
                    "loser_age": 29.1,
                    "winner_rank": 11,
                    "loser_rank": None,
                    "winner_rank_points": 2500,
                    "loser_rank_points": 1700,
                    "score": "6-4 6-3",
                    "best_of": 3,
                    "minutes": 91,
                    "w_ace": 8,
                    "w_df": 2,
                    "w_svpt": 58,
                    "w_1stIn": 35,
                    "w_1stWon": 29,
                    "w_2ndWon": 13,
                    "w_SvGms": 10,
                    "w_bpSaved": 3,
                    "w_bpFaced": 4,
                    "l_ace": 4,
                    "l_df": 5,
                    "l_svpt": 61,
                    "l_1stIn": 36,
                    "l_1stWon": 24,
                    "l_2ndWon": 9,
                    "l_SvGms": 10,
                    "l_bpSaved": 5,
                    "l_bpFaced": 8,
                }
            ]
        )

    def test_match_id_is_deterministic_across_reruns(self):
        source = self.sample_source()
        first = canonicalize_matches(source, tour="MEN", level="ATP", source_name="fixture")
        second = canonicalize_matches(source.copy(), tour="MEN", level="ATP", source_name="fixture")
        self.assertEqual(first.loc[0, "match_id"], second.loc[0, "match_id"])
        self.assertTrue(str(first.loc[0, "match_id"]).startswith("m_"))

    def test_surface_and_event_date_are_normalized_without_filling_missing_rank(self):
        result = canonicalize_matches(
            self.sample_source(), tour="MEN", level="ATP", source_name="fixture"
        )
        self.assertEqual(result.loc[0, "surface"], "Hard")
        self.assertEqual(result.loc[0, "event_date"], "2026-01-15")
        self.assertTrue(pd.isna(result.loc[0, "loser_rank"]))

    def test_each_match_produces_exactly_two_player_rows(self):
        matches = canonicalize_matches(
            self.sample_source(), tour="MEN", level="ATP", source_name="fixture"
        )
        rows = build_player_match_rows(matches)
        self.assertEqual(len(rows), 2)
        self.assertEqual(set(rows["player_side"]), {"winner", "loser"})
        self.assertEqual(set(rows["match_id"]), {matches.loc[0, "match_id"]})
        self.assertEqual(set(rows["is_winner"]), {True, False})
        self.assertTrue(rows["player_id"].str.startswith("p_").all())

    def test_player_rows_preserve_source_ids_metadata_and_stats(self):
        matches = canonicalize_matches(
            self.sample_source(), tour="MEN", level="ATP", source_name="fixture"
        )
        rows = build_player_match_rows(matches).set_index("player_side")
        winner = rows.loc["winner"]
        loser = rows.loc["loser"]
        self.assertEqual(winner["source_player_id"], 101)
        self.assertEqual(loser["source_player_id"], 202)
        self.assertEqual(winner["hand"], "R")
        self.assertEqual(loser["height_cm"], 191)
        self.assertEqual(winner["rank_points"], 2500)
        self.assertEqual(winner["aces"], 8)
        self.assertEqual(winner["service_points"], 58)
        self.assertEqual(winner["first_serve_in"], 35)
        self.assertEqual(winner["break_points_faced"], 4)
        self.assertEqual(loser["double_faults"], 5)
        self.assertEqual(loser["second_serve_points_won"], 9)
        self.assertEqual(winner["match_minutes"], 91)

    def test_writer_emits_required_audit_files_and_counts(self):
        matches = canonicalize_matches(
            self.sample_source(), tour="MEN", level="ATP", source_name="fixture"
        )
        players = build_player_match_rows(matches)
        manifest = [{"source_name": "fixture", "input_rows": 1, "canonical_rows": 1}]

        with tempfile.TemporaryDirectory() as tmp:
            summary = write_warehouse(matches, players, Path(tmp), manifest)
            root = Path(tmp)
            self.assertTrue((root / "matches.csv").exists())
            self.assertTrue((root / "player_match_rows.csv").exists())
            self.assertTrue((root / "source_manifest.json").exists())
            self.assertTrue((root / "schema.json").exists())
            self.assertEqual(summary["match_rows"], 1)
            self.assertEqual(summary["player_match_rows"], 2)
            stored_manifest = json.loads((root / "source_manifest.json").read_text())
            self.assertEqual(stored_manifest["sources"][0]["source_name"], "fixture")

    def test_cli_builds_mixed_tour_warehouse(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            men = root / "ATP.csv"
            wta = root / "WTA.csv"
            out = root / "warehouse"
            self.sample_source().to_csv(men, index=False)
            wta_frame = self.sample_source().copy()
            wta_frame["winner_name"] = "WTA One"
            wta_frame["loser_name"] = "WTA Two"
            wta_frame["tourney_id"] = "2026-W01"
            wta_frame.to_csv(wta, index=False)

            completed = subprocess.run(
                [
                    sys.executable,
                    "build_context_warehouse.py",
                    "--input",
                    f"MEN:ATP:{men}",
                    "--input",
                    f"WTA:WTA:{wta}",
                    "--output-dir",
                    str(out),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            matches = pd.read_csv(out / "matches.csv")
            players = pd.read_csv(out / "player_match_rows.csv")
            self.assertEqual(len(matches), 2)
            self.assertEqual(len(players), 4)
            self.assertEqual(set(matches["tour"]), {"MEN", "WTA"})
            forbidden = {"moneyline", "odds", "no_vig", "spread_line", "total_line"}
            self.assertFalse(forbidden.intersection(matches.columns))


if __name__ == "__main__":
    unittest.main()
