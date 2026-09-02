import unittest

import pandas as pd

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
                    "winner_name": "Player One",
                    "loser_name": "Player Two",
                    "winner_rank": 11,
                    "loser_rank": None,
                    "score": "6-4 6-3",
                    "best_of": 3,
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


if __name__ == "__main__":
    unittest.main()
