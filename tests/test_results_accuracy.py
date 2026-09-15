import pathlib
import sys
import tempfile
import unittest

import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from results_accuracy_page import accuracy_metrics, fixture_headline_metrics, load_accuracy_ledger, recommendation_accuracy_matrix


class ResultsAccuracyTests(unittest.TestCase):
    def test_load_accuracy_ledger_reads_frozen_csv(self):
        frame = pd.DataFrame([{"freeze_key":"a","frozen_at_utc":"2026-09-01T06:00:00+00:00","start_time_utc":"2026-09-01T08:00:00Z","result_status":"SETTLED","settled_result":"WIN","model_probability":.60,"profit_units":1.0}])
        with tempfile.TemporaryDirectory() as tmp:
            path=pathlib.Path(tmp)/"ledger.csv"; frame.to_csv(path,index=False); loaded=load_accuracy_ledger(path)
        self.assertEqual(len(loaded),1); self.assertTrue(pd.api.types.is_datetime64_any_dtype(loaded["frozen_at_utc"]))

    def test_accuracy_metrics_excludes_pushes_and_voids_from_roi_and_win_rate(self):
        df=pd.DataFrame([{"result_status":"SETTLED","settled_result":"WIN","profit_units":1.5},{"result_status":"SETTLED","settled_result":"LOSS","profit_units":-1.0},{"result_status":"SETTLED","settled_result":"PUSH","profit_units":0.0},{"result_status":"SETTLED","settled_result":"VOID","profit_units":0.0}])
        m=accuracy_metrics(df,actionable_only=False); self.assertEqual(m["decisions"],2); self.assertAlmostEqual(m["win_rate"],.5); self.assertAlmostEqual(m["units"],.5); self.assertAlmostEqual(m["roi"],.25)

    def test_fixture_headline_counts_each_fixture_once(self):
        frame=pd.DataFrame([{"fixture_id":"fx1","winner_correct":True,"brier_score":.18,"abs_margin_error":3.46,"abs_total_error":.5},{"fixture_id":"fx2","winner_correct":False,"brier_score":.36,"abs_margin_error":2.,"abs_total_error":1.5}])
        m=fixture_headline_metrics(frame); self.assertEqual(m["settled_fixtures"],2); self.assertAlmostEqual(m["winner_accuracy"],.5)

    def test_recommendation_matrix_splits_market_competition_and_all_signal_tiers(self):
        df=pd.DataFrame([
            {"market_group":"moneyline","tour_v5":"ATP","signal":"BET","result_status":"SETTLED","settled_result":"WIN","profit_units":.8},
            {"market_group":"moneyline","tour_v5":"ATP","signal":"BET","result_status":"SETTLED","settled_result":"LOSS","profit_units":-1.0},
            {"market_group":"moneyline","tour_v5":"WTA","signal":"REVIEW","result_status":"SETTLED","settled_result":"WIN","profit_units":.5},
            {"market_group":"game_spread","tour_v5":"CHALLENGER","signal":"PASS","result_status":"SETTLED","settled_result":"PUSH","profit_units":0.0},
        ])
        table=recommendation_accuracy_matrix(df,"moneyline")
        self.assertEqual(list(table.index),["ATP","WTA","Challenger","All"])
        self.assertIn("BET",table.columns); self.assertIn("LEAN",table.columns); self.assertIn("REVIEW",table.columns); self.assertIn("PASS",table.columns); self.assertIn("Overall",table.columns)
        self.assertEqual(table.loc["ATP","BET"],"50.0% · 1-1 · N=2 · -0.2u · -10.0% ROI")
        self.assertEqual(table.loc["WTA","REVIEW"],"100.0% · 1-0 · N=1 · +0.5u · +50.0% ROI")


if __name__ == "__main__": unittest.main()
