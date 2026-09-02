import unittest
from datetime import datetime, timezone

import pandas as pd

import v5_daily_batch


class DailyBatchModuleTests(unittest.TestCase):
    def test_daily_batch_exports_core_functions(self):
        for name in ("freeze_key", "eligible_pre_match", "merge_frozen", "rank_board", "infer_surface", "infer_best_of"):
            self.assertTrue(callable(getattr(v5_daily_batch, name, None)), name)

    def test_freeze_key_is_stable_across_name_formatting_and_numeric_line(self):
        a={"fixture_id":"fx1","market_group":"game_spread","selection":"Darderi, Luciano","line":-3.5}
        b={"fixture_id":"fx1","market_group":"game_spread","selection":"Luciano Darderi","line":"-3.50"}
        self.assertEqual(v5_daily_batch.freeze_key(a),v5_daily_batch.freeze_key(b))
        self.assertNotEqual(v5_daily_batch.freeze_key(a),v5_daily_batch.freeze_key({**a,"market_group":"moneyline"}))

    def test_eligible_pre_match_excludes_started_and_invalid_rows(self):
        now=datetime(2026,9,1,6,0,tzinfo=timezone.utc)
        feed=pd.DataFrame([
            {"fixture_id":"future","start_time_utc":"2026-09-01T07:00:00Z"},
            {"fixture_id":"past","start_time_utc":"2026-09-01T05:00:00Z"},
            {"fixture_id":"bad","start_time_utc":"not-a-date"},
        ])
        self.assertEqual(v5_daily_batch.eligible_pre_match(feed,now=now)["fixture_id"].tolist(),["future"])

    def test_merge_frozen_is_append_only_and_idempotent(self):
        existing=pd.DataFrame([{"freeze_key":"fx1|moneyline|luciano darderi|","fixture_id":"fx1","model_probability":0.61}])
        fresh=pd.DataFrame([
            {"freeze_key":"fx1|moneyline|luciano darderi|","fixture_id":"fx1","model_probability":0.66},
            {"freeze_key":"fx2|moneyline|player two|","fixture_id":"fx2","model_probability":0.55},
        ])
        out=v5_daily_batch.merge_frozen(existing,fresh)
        self.assertEqual(len(out),2)
        self.assertAlmostEqual(float(out[out["fixture_id"]=="fx1"].iloc[0]["model_probability"]),0.61)

    def test_rank_board_prioritizes_signal_then_ev(self):
        board=pd.DataFrame([
            {"selection":"a","signal":"LEAN","expected_value":0.10},
            {"selection":"b","signal":"BET","expected_value":0.06},
            {"selection":"c","signal":"BET","expected_value":0.12},
            {"selection":"d","signal":"PASS","expected_value":0.30},
        ])
        self.assertEqual(v5_daily_batch.rank_board(board)["selection"].tolist(),["c","b","a","d"])

    def test_surface_map_marks_known_tournaments_as_known(self):
        self.assertEqual(v5_daily_batch.infer_surface("US Open Men Singles"),("Hard","Auto — tournament map"))
        self.assertEqual(v5_daily_batch.infer_surface("ATP Challenger Como, Italy Men Singles"),("Clay","Auto — tournament map"))
        self.assertEqual(v5_daily_batch.infer_surface("Wimbledon Men Singles"),("Grass","Auto — tournament map"))
        self.assertEqual(v5_daily_batch.infer_surface("Mystery Open"),("Hard","Auto default — review"))

    def test_infer_best_of_uses_five_sets_only_for_mens_slam_main_draw(self):
        self.assertEqual(v5_daily_batch.infer_best_of("US Open Men Singles","MEN"),5)
        self.assertEqual(v5_daily_batch.infer_best_of("Wimbledon Men Singles","ATP"),5)
        self.assertEqual(v5_daily_batch.infer_best_of("US Open Men Singles Qualification","MEN"),3)
        self.assertEqual(v5_daily_batch.infer_best_of("US Open Women Singles","WTA"),3)
        self.assertEqual(v5_daily_batch.infer_best_of("ATP Cincinnati Men Singles","MEN"),3)

    @staticmethod
    def _ratings():
        return pd.DataFrame([
            {"player":"Alice Alpha","surface":"Hard","serve_global":0.02,"return_global":0.01,"surface_points":1000,"serve_surface":0.01,"return_surface":0.01,"elo":1600,"surface_elo":1600,"form_logit":0.08,"day_vol_logit":0.10,"state_confidence":0.9},
            {"player":"Bob Beta","surface":"Hard","serve_global":-0.01,"return_global":-0.01,"surface_points":1000,"serve_surface":-0.01,"return_surface":-0.01,"elo":1500,"surface_elo":1500,"form_logit":-0.08,"day_vol_logit":0.10,"state_confidence":0.8},
        ])

    @staticmethod
    def _summary():
        return {"MEN":{"baseline":{"Hard":0.62,"Clay":0.60,"Grass":0.65}}}

    @staticmethod
    def _score_candidate():
        return {
            "version":"v5-score-test-baseline",
            "market_prices_used":False,
            "MEN":{"selected_candidate":"conditioned_mechanistic","model":None},
            "WTA":{"selected_candidate":"conditioned_mechanistic","model":None},
        }

    def test_build_fixture_board_prices_all_moneyline_selections(self):
        rows=pd.DataFrame([
            {"snapshot_utc":"2026-09-01T05:00:00Z","fixture_id":"fx1","start_time_utc":"2026-09-01T07:00:00Z","tournament":"US Open Men Singles","tour":"ATP","player1":"Alpha, Alice","player2":"Beta, Bob","market_group":"moneyline","selection":"Alpha, Alice","line":None,"best_bookmaker":"pinnacle","best_decimal_odds":1.8,"best_american_odds":-125,"consensus_no_vig_prob":0.55},
            {"snapshot_utc":"2026-09-01T05:00:00Z","fixture_id":"fx1","start_time_utc":"2026-09-01T07:00:00Z","tournament":"US Open Men Singles","tour":"ATP","player1":"Alpha, Alice","player2":"Beta, Bob","market_group":"moneyline","selection":"Beta, Bob","line":None,"best_bookmaker":"pinnacle","best_decimal_odds":2.2,"best_american_odds":120,"consensus_no_vig_prob":0.45},
        ])
        out=v5_daily_batch.build_fixture_board(rows,{"MEN":self._ratings()},self._summary(),sims=300,score_candidate=self._score_candidate())
        self.assertEqual(len(out),2)
        self.assertTrue(out["model_probability"].notna().all())
        self.assertEqual(set(out["best_of"]),{5})
        self.assertEqual(set(out["model_version"]),{"V5.1_OUTCOME_CALIBRATED_FALLBACK"})
        self.assertEqual(set(out["selected_score_candidate"]),{"conditioned_mechanistic"})
        self.assertEqual(set(out["state_variation_used"]),{False})
        self.assertTrue((out["model_probability"].between(0,1)).all())
        p1=out[out["selection"]=="Alpha, Alice"].iloc[0]
        self.assertAlmostEqual(float(p1["model_probability"]),float(p1["calibrated_probability_p1"]),places=12)
        self.assertNotEqual(float(p1["raw_sim_probability_p1"]),float(p1["calibrated_probability_p1"]))

    def test_build_fixture_board_prices_requested_large_slam_spread(self):
        rows=pd.DataFrame([
            {"fixture_id":"fx2","tournament":"US Open Men Singles","tour":"ATP","player1":"Alpha, Alice","player2":"Beta, Bob","market_group":"game_spread","selection":"Alpha, Alice","line":-9.5,"best_decimal_odds":1.95,"consensus_no_vig_prob":0.50},
            {"fixture_id":"fx2","tournament":"US Open Men Singles","tour":"ATP","player1":"Alpha, Alice","player2":"Beta, Bob","market_group":"game_spread","selection":"Beta, Bob","line":9.5,"best_decimal_odds":1.95,"consensus_no_vig_prob":0.50},
        ])
        out=v5_daily_batch.build_fixture_board(rows,{"MEN":self._ratings()},self._summary(),sims=300,score_candidate=self._score_candidate())
        self.assertEqual(set(out["best_of"]),{5})
        self.assertTrue(out["model_probability"].notna().all())

    def test_build_daily_outputs_skips_started_fixtures_and_freezes_future_rows(self):
        base={"snapshot_utc":"2026-09-01T05:00:00Z","tournament":"US Open Men Singles","tour":"ATP","player1":"Alpha, Alice","player2":"Beta, Bob","market_group":"moneyline","line":None,"best_bookmaker":"pinnacle","consensus_no_vig_prob":0.5}
        feed=pd.DataFrame([
            {**base,"fixture_id":"future","start_time_utc":"2026-09-01T07:00:00Z","selection":"Alpha, Alice","best_decimal_odds":1.8,"best_american_odds":-125},
            {**base,"fixture_id":"future","start_time_utc":"2026-09-01T07:00:00Z","selection":"Beta, Bob","best_decimal_odds":2.2,"best_american_odds":120},
            {**base,"fixture_id":"past","start_time_utc":"2026-09-01T05:30:00Z","selection":"Alpha, Alice","best_decimal_odds":1.8,"best_american_odds":-125},
            {**base,"fixture_id":"past","start_time_utc":"2026-09-01T05:30:00Z","selection":"Beta, Bob","best_decimal_odds":2.2,"best_american_odds":120},
        ])
        now=datetime(2026,9,1,6,0,tzinfo=timezone.utc)
        board,ledger,errors=v5_daily_batch.build_daily_outputs(feed,{"MEN":self._ratings()},self._summary(),existing_ledger=pd.DataFrame(),now=now,sims=100,score_candidate=self._score_candidate())
        self.assertEqual(set(board["fixture_id"]),{"future"})
        self.assertEqual(len(ledger),2); self.assertEqual(errors,[]); self.assertTrue(ledger["freeze_key"].is_unique)


if __name__ == "__main__":
    unittest.main()
