import pathlib
import sys
import tempfile
import unittest

import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from results_accuracy_page import accuracy_metrics, load_accuracy_ledger


class ResultsAccuracyTests(unittest.TestCase):
    def test_load_accuracy_ledger_reads_frozen_csv(self):
        frame = pd.DataFrame([
            {
                "freeze_key": "a",
                "frozen_at_utc": "2026-09-01T06:00:00+00:00",
                "start_time_utc": "2026-09-01T08:00:00Z",
                "result_status": "SETTLED",
                "settled_result": "WIN",
                "model_probability": 0.60,
                "profit_units": 1.0,
            }
        ])
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "ledger.csv"
            frame.to_csv(path, index=False)
            loaded = load_accuracy_ledger(path)
        self.assertEqual(len(loaded), 1)
        self.assertTrue(pd.api.types.is_datetime64_any_dtype(loaded["frozen_at_utc"]))
        self.assertEqual(loaded.loc[0, "settled_result"], "WIN")

    def test_accuracy_metrics_excludes_pushes_and_voids_from_roi_and_win_rate(self):
        df = pd.DataFrame([
            {"result_status": "SETTLED", "settled_result": "WIN", "profit_units": 1.5},
            {"result_status": "SETTLED", "settled_result": "LOSS", "profit_units": -1.0},
            {"result_status": "SETTLED", "settled_result": "PUSH", "profit_units": 0.0},
            {"result_status": "SETTLED", "settled_result": "VOID", "profit_units": 0.0},
            {"result_status": "OPEN", "settled_result": None, "profit_units": None},
        ])
        metrics = accuracy_metrics(df)
        self.assertEqual(metrics["frozen"], 5)
        self.assertEqual(metrics["settled"], 4)
        self.assertEqual(metrics["decisions"], 2)
        self.assertEqual(metrics["wins"], 1)
        self.assertEqual(metrics["losses"], 1)
        self.assertEqual(metrics["pushes"], 1)
        self.assertEqual(metrics["voids"], 1)
        self.assertAlmostEqual(metrics["win_rate"], 0.5)
        self.assertAlmostEqual(metrics["units"], 0.5)
        self.assertAlmostEqual(metrics["roi"], 0.25)


if __name__ == "__main__":
    unittest.main()
