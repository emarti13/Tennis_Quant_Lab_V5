import math
import unittest

from v5_core import simulate_match
from v5_model_calibration import calibrated_match_probability, calibration_record


class IndependentCalibrationTests(unittest.TestCase):
    def test_calibration_is_symmetric_when_players_are_swapped(self):
        p_ab = calibrated_match_probability(0.646, 0.608, 0.71, "MEN")
        p_ba = calibrated_match_probability(0.608, 0.646, 0.29, "MEN")
        self.assertAlmostEqual(p_ab + p_ba, 1.0, places=12)

    def test_calibration_matches_2025_fitted_formula(self):
        p1_serve = 0.646
        p2_serve = 0.608
        p_elo = 0.71
        x_sr = math.log(p1_serve / (1 - p1_serve)) - math.log(p2_serve / (1 - p2_serve))
        x_elo = math.log(p_elo / (1 - p_elo))
        expected = 1 / (1 + math.exp(-(2.559868394630198 * x_sr + 0.703321947598873 * x_elo)))
        self.assertAlmostEqual(
            calibrated_match_probability(p1_serve, p2_serve, p_elo, "MEN"),
            expected,
            places=12,
        )

    def test_calibration_metadata_is_outcome_only_and_holdout_documented(self):
        men = calibration_record("MEN")
        self.assertEqual(men["fit_year"], 2025)
        self.assertEqual(men["validation_year"], 2026)
        self.assertEqual(men["inputs"], ["serve_return", "surface_elo"])
        self.assertNotIn("market", " ".join(men.keys()).lower())
        self.assertLess(
            men["validation_2026"]["combined_log_loss"],
            men["validation_2026"]["serve_return_log_loss"],
        )

    def test_score_distribution_can_be_conditioned_to_calibrated_match_probability(self):
        result = simulate_match(
            0.64,
            0.61,
            best_of=3,
            n=3000,
            seed=17,
            state_variation=False,
            target_pA_win=0.72,
            spread_lines=[-3.5, 3.5],
            total_lines=[21.5, 22.5],
        )
        self.assertAlmostEqual(result["pA_win"], 0.72, places=12)
        self.assertNotAlmostEqual(result["raw_pA_win"], 0.72, places=3)
        self.assertEqual(result["calibration_target_pA_win"], 0.72)
        self.assertGreaterEqual(result["spread"]["-3.5"], 0.0)
        self.assertLessEqual(result["spread"]["-3.5"], 1.0)
        self.assertGreaterEqual(result["over"]["21.5"], 0.0)
        self.assertLessEqual(result["over"]["21.5"], 1.0)


if __name__ == "__main__":
    unittest.main()
