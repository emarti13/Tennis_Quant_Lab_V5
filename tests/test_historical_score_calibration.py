import unittest

import pandas as pd

from historical_score_calibration import build_result_index, matched_walkforward_scores


class HistoricalScoreCalibrationTests(unittest.TestCase):
    def test_result_index_parses_completed_game_total_and_margin(self):
        results = pd.DataFrame([
            {"tourney_date": 20250820, "winner_name": "Alpha, Alice", "loser_name": "Bob Beta", "score": "6-4 7-6(5)", "tourney_name": "Test Open"},
            {"tourney_date": 20250821, "winner_name": "Gamma G", "loser_name": "Delta D", "score": "6-2 1-0 RET", "tourney_name": "Test Open"},
        ])
        idx = build_result_index(results)
        row = idx[("2025-08-20", "alice alpha", "bob beta")]
        self.assertEqual(row["actual_total"], 23)
        self.assertEqual(row["actual_margin"], 3)
        self.assertNotIn(("2025-08-21", "gamma g", "delta d"), idx)

    def test_walkforward_join_uses_date_and_names_without_market_data(self):
        results = pd.DataFrame([
            {"tourney_date": 20250820, "winner_name": "Alpha, Alice", "loser_name": "Bob Beta", "score": "6-4 6-4", "tourney_name": "Test Open"},
        ])
        wf = pd.DataFrame([
            {"date": "2025-08-20", "surface": "Hard", "winner": "Alice Alpha", "loser": "Beta, Bob", "winner_serve_p": .64, "loser_serve_p": .60, "elo_winner_p": .70},
        ])
        matched = matched_walkforward_scores(wf, build_result_index(results))
        self.assertEqual(len(matched), 1)
        self.assertEqual(int(matched.iloc[0]["actual_total"]), 20)
        self.assertEqual(int(matched.iloc[0]["actual_margin"]), 4)
        self.assertAlmostEqual(float(matched.iloc[0]["winner_serve_p"]), .64)

    def test_score_rows_have_deterministic_player_a_orientation_and_signed_margin(self):
        results = pd.DataFrame([
            {"tourney_date": 20250820, "winner_name": "Zulu Z", "loser_name": "Alpha A", "score": "6-4 6-4", "tourney_name": "Test Open"},
        ])
        wf = pd.DataFrame([
            {"date": "2025-08-20", "surface": "Hard", "winner": "Zulu Z", "loser": "Alpha A", "winner_serve_p": .64, "loser_serve_p": .60, "elo_winner_p": .70},
        ])
        row = matched_walkforward_scores(wf, build_result_index(results)).iloc[0]
        self.assertEqual(row["player_a"], "Alpha A")
        self.assertEqual(row["player_b"], "Zulu Z")
        self.assertEqual(int(row["target_a_win"]), 0)
        self.assertEqual(int(row["actual_margin_a"]), -4)
        self.assertAlmostEqual(float(row["a_serve_p"]), .60)
        self.assertAlmostEqual(float(row["b_serve_p"]), .64)
        self.assertAlmostEqual(float(row["elo_a_p"]), .30)


if __name__ == "__main__":
    unittest.main()
