import unittest
from datetime import datetime, timezone

import pandas as pd

import v5_daily_batch


class DailyBatchModuleTests(unittest.TestCase):
    def test_daily_batch_exports_core_functions(self):
        for name in ("freeze_key", "eligible_pre_match", "merge_frozen", "rank_board", "infer_best_of", "build_daily_outputs"):
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

    def test_infer_best_of_uses_five_sets_only_for_mens_slam_main_draw(self):
        self.assertEqual(v5_daily_batch.infer_best_of("US Open Men Singles","MEN"),5)
        self.assertEqual(v5_daily_batch.infer_best_of("Wimbledon Men Singles","ATP"),5)
        self.assertEqual(v5_daily_batch.infer_best_of("US Open Men Singles Qualification","MEN"),3)
        self.assertEqual(v5_daily_batch.infer_best_of("US Open Women Singles","WTA"),3)
        self.assertEqual(v5_daily_batch.infer_best_of("ATP Cincinnati Men Singles","MEN"),3)

    def test_build_daily_outputs_skips_started_fixtures_and_freezes_future_rows(self):
        base={"snapshot_utc":"2026-09-01T05:00:00Z","tournament":"US Open Men Singles","tour":"ATP","player1":"Alpha, Alice","player2":"Beta, Bob","market_group":"moneyline","line":None,"best_bookmaker":"pinnacle","consensus_no_vig_prob":0.5}
        feed=pd.DataFrame([
            {**base,"fixture_id":"future","start_time_utc":"2026-09-01T07:00:00Z","selection":"Alpha, Alice","best_decimal_odds":1.8,"best_american_odds":-125},
            {**base,"fixture_id":"future","start_time_utc":"2026-09-01T07:00:00Z","selection":"Beta, Bob","best_decimal_odds":2.2,"best_american_odds":120},
            {**base,"fixture_id":"future","start_time_utc":"2026-09-01T07:00:00Z","selection":"Alpha, Alice","market_group":"game_spread","line":-3.5,"best_decimal_odds":1.9},
            {**base,"fixture_id":"thin","start_time_utc":"2026-09-01T08:00:00Z","selection":"Alpha, Alice","best_decimal_odds":1.8,"best_american_odds":-125},
            {**base,"fixture_id":"past","start_time_utc":"2026-09-01T05:30:00Z","selection":"Alpha, Alice","best_decimal_odds":1.8,"best_american_odds":-125},
        ])
        now=datetime(2026,9,1,6,0,tzinfo=timezone.utc)
        board,ledger,errors,_states=v5_daily_batch.build_daily_outputs(feed,_FakeContext(),existing_ledger=pd.DataFrame(),now=now)
        self.assertEqual(set(board["fixture_id"]),{"future","thin"})
        self.assertEqual(errors,[])
        future=board[board["fixture_id"]=="future"]
        ml=future[future["market_group"]=="moneyline"].set_index("selection")["model_probability"]
        self.assertAlmostEqual(float(ml["Alpha, Alice"]),0.62); self.assertAlmostEqual(float(ml["Beta, Bob"]),0.38)
        spread=future[future["market_group"]=="game_spread"].iloc[0]
        self.assertTrue(pd.isna(spread["model_probability"])); self.assertEqual(spread["no_price_reason"],"NOT_MODELLED")
        thin=board[board["fixture_id"]=="thin"].iloc[0]
        self.assertTrue(pd.isna(thin["model_probability"])); self.assertEqual(thin["no_price_reason"],"THIN_HISTORY")
        self.assertEqual(len(ledger),2); self.assertTrue(ledger["freeze_key"].is_unique)   # only priced rows freeze
        self.assertEqual(set(board["model_version"]),{"baseline_elo_v1"})


class _FakeContext:
    """Stands in for v5_pricing.PricingContext: 'future' prices, 'thin' does not."""
    def price(self, fixture_id, **kw):
        from v5_pricing import Price
        if fixture_id == "future":
            return Price("future","priced","OK","ATP|2026-08-31|us-open|ny","MEN","ATP","Hard","Outdoor",5,"main","after_start",
                         "M-1","M-2",(40,30),0.62,True)
        return Price(fixture_id,"no_price","THIN_HISTORY","ATP|2026-08-31|us-open|ny","MEN","ATP","Hard","Outdoor",5,"main","after_start",
                     "M-1","M-3",(40,4))


if __name__ == "__main__":
    unittest.main()
