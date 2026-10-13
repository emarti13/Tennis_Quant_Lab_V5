import unittest
from datetime import datetime, timezone

import pandas as pd

import v5_daily_batch


class DailyBatchModuleTests(unittest.TestCase):
    def test_daily_batch_exports_core_functions(self):
        for name in ("freeze_key", "eligible_pre_match", "merge_frozen", "rank_board", "resolve_fixture_surface", "infer_best_of"):
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

    def test_surface_comes_only_from_tournament_authority(self):
        # The legacy hardcoded map (infer_surface) was retired with the 2026-09-21 court-data reset:
        # surface now comes only from context_registry/tournament_authority.csv and fails closed.
        self.assertFalse(hasattr(v5_daily_batch, "infer_surface"))
        self.assertEqual(v5_daily_batch.resolve_fixture_surface("US Open Men Singles", start_time_utc="2026-08-31T15:00:00Z", tour="ATP"),
                         ("Hard", "Tournament authority"))
        self.assertEqual(v5_daily_batch.resolve_fixture_surface("Wimbledon Men Singles", start_time_utc="2026-07-01T12:00:00Z", tour="ATP"),
                         ("Grass", "Tournament authority"))
        with self.assertRaises(ValueError):
            v5_daily_batch.resolve_fixture_surface("Mystery Open", start_time_utc="2026-08-31T15:00:00Z", tour="ATP")

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


def test_unseen_player_uses_explicit_zero_confidence_cold_start():
    from v5_daily_batch import _prepare_fixture
    ratings = DailyBatchModuleTests._ratings()
    feed = pd.DataFrame([{
        # A tournament the authority resolves: this test is about cold start, not surface.
        "fixture_id":"cold-1","start_time_utc":"2026-09-01T07:00:00Z",
        "tournament":"US Open Men Singles","tour":"MEN",
        "player1":"Alice Alpha","player2":"New Player",
    }])
    summary = {"MEN":{"baseline":{"Hard":0.62,"Clay":0.60,"Grass":0.65}}}
    prepared = _prepare_fixture(feed, {"MEN":ratings,"WTA":ratings.iloc[0:0]}, summary)
    assert prepared["player2_cold_start"] is True
    assert prepared["player1_cold_start"] is False
    assert prepared["rating_p2"]["state_confidence"] == 0.0
    assert prepared["rating_p2"]["elo"] == 1500.0
    assert prepared["rating_p2"]["surface_elo"] == 1500.0
    assert prepared["rating_p2"]["serve_global"] == 0.0
    assert prepared["rating_p2"]["return_global"] == 0.0


def test_market_confidence_is_the_weaker_player_on_every_side():
    # A bet on a known player against a no-history opponent used to inherit the known
    # player's confidence and reach BET (2026-09/10: 9 official BETs, e.g. vs Kuzmova).
    from v5_daily_batch import _confidence_for_market
    row = {"market_group": "moneyline", "selection": "Known Player"}
    assert _confidence_for_market(row, "Known Player", "New Player", 0.8, 0.0) == 0.0
    assert _confidence_for_market({**row, "selection": "New Player"}, "Known Player", "New Player", 0.8, 0.0) == 0.0


def test_placeholder_participants_are_never_priced():
    import pytest
    from v5_daily_batch import _prepare_fixture
    feed = pd.DataFrame([{
        "fixture_id": "ph-1", "start_time_utc": "2026-09-01T07:00:00Z",
        "tournament": "US Open Men Singles", "tour": "MEN",
        "player1": "WQF1", "player2": "Alice Alpha",
    }])
    ratings = DailyBatchModuleTests._ratings()
    summary = {"MEN": {"baseline": {"Hard": 0.62, "Clay": 0.60, "Grass": 0.65}}}
    with pytest.raises(ValueError, match="Placeholder participant"):
        _prepare_fixture(feed, {"MEN": ratings, "WTA": ratings.iloc[0:0]}, summary)


def test_placeholder_names():
    from v5_live_market import is_placeholder_participant as ph
    for name in ("WQF1", "Qf8", "WSF2", "R16P14", "Q1", "LL2", "TBD", "Qualifier"):
        assert ph(name), name
    for name in ("Quinn, Ethan", "Qu, Yihan", "Llamas Ruiz, Pablo", "Cretu, Cezar (2001)", "Emanuela Lares"):
        assert not ph(name), name
