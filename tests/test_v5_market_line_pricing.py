import unittest

import pandas as pd

from v5_core import simulate_match
from v5_live_market import add_model_pricing, model_probability_for_market


class ExactMarketLinePricingTests(unittest.TestCase):
    def test_simulator_prices_requested_spread_and_total_lines_including_pushes(self):
        result = simulate_match(
            0.64,
            0.60,
            best_of=5,
            n=500,
            seed=7,
            state_variation=False,
            spread_lines=[-10.0, -7.5, 7.5, 10.0],
            total_lines=[22.0, 22.5, 38.0, 38.5],
        )
        spread = {float(k): v for k, v in result["spread"].items()}
        spread_push = {float(k): v for k, v in result["spread_push"].items()}
        over = {float(k): v for k, v in result["over"].items()}
        total_push = {float(k): v for k, v in result["total_push"].items()}

        for line in (-10.0, -7.5, 7.5, 10.0):
            self.assertIn(line, spread)
            self.assertIn(line, spread_push)
        for line in (22.0, 22.5, 38.0, 38.5):
            self.assertIn(line, over)
            self.assertIn(line, total_push)

        self.assertEqual(spread_push[-7.5], 0.0)
        self.assertEqual(total_push[22.5], 0.0)
        self.assertGreaterEqual(spread_push[-10.0], 0.0)
        self.assertGreaterEqual(total_push[22.0], 0.0)

    def test_integer_spread_probability_excludes_push_from_binary_edge_probability(self):
        result = {
            "pA_win": 0.6,
            "spread": {"-8.0": 0.40, "+8.0": 0.70},
            "spread_push": {"-8.0": 0.10, "+8.0": 0.10},
            "over": {},
            "total_push": {},
        }
        p1_row = {"market_group": "game_spread", "selection": "Alice Alpha", "line": -8.0}
        p2_row = {"market_group": "game_spread", "selection": "Bob Beta", "line": 8.0}
        self.assertAlmostEqual(
            model_probability_for_market(p1_row, result, "Alice Alpha", "Bob Beta"),
            0.40 / 0.90,
        )
        self.assertAlmostEqual(
            model_probability_for_market(p2_row, result, "Alice Alpha", "Bob Beta"),
            0.50 / 0.90,
        )

    def test_integer_total_pricing_accounts_for_push_in_ev(self):
        result = {
            "pA_win": 0.5,
            "spread": {},
            "spread_push": {},
            "over": {"22.0": 0.45},
            "total_push": {"22.0": 0.10},
        }
        rows = pd.DataFrame([
            {
                "market_group": "total_games",
                "selection": "Over",
                "line": 22.0,
                "best_decimal_odds": 2.10,
                "consensus_no_vig_prob": 0.50,
            },
            {
                "market_group": "total_games",
                "selection": "Under",
                "line": 22.0,
                "best_decimal_odds": 2.10,
                "consensus_no_vig_prob": 0.50,
            },
        ])
        out = add_model_pricing(rows, result, "Alice Alpha", "Bob Beta")
        self.assertTrue(out["model_probability"].notna().all())
        self.assertTrue((out["model_push_probability"] == 0.10).all())
        self.assertTrue((out["model_win_probability"] == 0.45).all())
        # 45% win at 2.10, 10% push, 45% loss => +0.045 expected units.
        self.assertTrue((out["expected_value"].round(6) == 0.045).all())


if __name__ == "__main__":
    unittest.main()
