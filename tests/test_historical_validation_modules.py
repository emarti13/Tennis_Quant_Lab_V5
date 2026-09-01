from __future__ import annotations

import unittest
from datetime import datetime, timezone


class HistoricalOddsNormalizerTests(unittest.TestCase):
    def test_flattens_nested_history_and_selects_pre_match_snapshot(self):
        from historical_odds_normalizer import flatten_history, select_snapshot

        payload = {
            "fixtureId": "fx1",
            "bookmakers": {
                "pinnacle": {
                    "markets": {
                        "101": {
                            "outcomes": {
                                "201": {
                                    "players": {
                                        "0": [
                                            {"createdAt": "2026-08-31T18:00:00+00:00", "price": 1.80, "limit": 100, "active": True},
                                            {"createdAt": "2026-08-31T19:30:00+00:00", "price": 1.72, "limit": 125, "active": True},
                                        ]
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        rows = flatten_history(payload)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["fixture_id"], "fx1")
        self.assertEqual(rows[0]["bookmaker"], "pinnacle")
        self.assertEqual(rows[0]["market_id"], "101")
        self.assertEqual(rows[0]["outcome_id"], "201")
        self.assertEqual(rows[0]["player_id"], "0")

        start = datetime(2026, 8, 31, 20, 0, tzinfo=timezone.utc)
        snap = select_snapshot(rows, start_time=start, hours_before=1)
        self.assertEqual(len(snap), 1)
        self.assertEqual(snap[0]["price_decimal"], 1.80)

        close = select_snapshot(rows, start_time=start, closing=True)
        self.assertEqual(close[0]["price_decimal"], 1.72)


class HistoricalMarketMapperTests(unittest.TestCase):
    def test_maps_same_market_schema_as_live_feed_and_devigs_pair(self):
        from historical_market_mapper import map_snapshot_rows

        fixture = {
            "fixtureId": "fx1",
            "participant1Name": "Carlos Alcaraz",
            "participant2Name": "Jannik Sinner",
            "startTime": "2026-08-31T20:00:00Z",
            "tournamentName": "ATP Test",
            "categoryName": "ATP",
        }
        metadata = [{
            "marketId": 121,
            "marketName": "Moneyline",
            "period": "Full Match",
            "marketType": "moneyline",
            "outcomes": [
                {"outcomeId": 121, "outcomeName": "Player 1"},
                {"outcomeId": 122, "outcomeName": "Player 2"},
            ],
        }]
        rows = [
            {"fixture_id": "fx1", "bookmaker": "pinnacle", "market_id": "121", "outcome_id": "121", "player_id": "0", "created_at": datetime(2026, 8, 31, 19, 0, tzinfo=timezone.utc), "price_decimal": 1.80, "snapshot_label": "t-1h", "limit": 100},
            {"fixture_id": "fx1", "bookmaker": "pinnacle", "market_id": "121", "outcome_id": "122", "player_id": "0", "created_at": datetime(2026, 8, 31, 19, 0, tzinfo=timezone.utc), "price_decimal": 2.10, "snapshot_label": "t-1h", "limit": 100},
        ]
        mapped = map_snapshot_rows(rows, fixture, metadata)
        self.assertEqual(len(mapped), 2)
        self.assertEqual(mapped[0]["market_group"], "moneyline")
        self.assertEqual({r["selection"] for r in mapped}, {"Carlos Alcaraz", "Jannik Sinner"})
        self.assertAlmostEqual(sum(r["no_vig_prob"] for r in mapped), 1.0)


class HistoricalFixtureMatcherTests(unittest.TestCase):
    def test_matches_reversed_player_order_by_pair_and_date(self):
        from historical_fixture_matcher import match_fixture

        fixture = {
            "participant1Name": "Alcaraz, Carlos",
            "participant2Name": "Sinner, Jannik",
            "startTime": "2026-06-14T15:00:00Z",
        }
        candidates = [
            {"date": "2026-06-14", "winner_name": "Jannik Sinner", "loser_name": "Carlos Alcaraz", "match_id": "m1"},
            {"date": "2026-06-15", "winner_name": "Other Player", "loser_name": "Carlos Alcaraz", "match_id": "m2"},
        ]
        match = match_fixture(fixture, candidates)
        self.assertIsNotNone(match)
        self.assertEqual(match["match_id"], "m1")

    def test_refuses_ambiguous_same_pair_same_date(self):
        from historical_fixture_matcher import match_fixture

        fixture = {
            "participant1Name": "Player, One",
            "participant2Name": "Player, Two",
            "startTime": "2026-07-01T12:00:00Z",
        }
        candidates = [
            {"date": "2026-07-01", "winner_name": "Player One", "loser_name": "Player Two", "match_id": "a"},
            {"date": "2026-07-01", "winner_name": "Player Two", "loser_name": "Player One", "match_id": "b"},
        ]
        self.assertIsNone(match_fixture(fixture, candidates))


class HistoricalStateReplayTests(unittest.TestCase):
    def test_snapshot_happens_before_target_match_update(self):
        from historical_state_replay import ReplayStateStore

        class Engine:
            def __init__(self):
                self.seen = []
            def snapshot(self, row):
                return {"target": row["id"], "seen": tuple(self.seen)}
            def update(self, row):
                self.seen.append(row["id"])

        matches = [
            {"id": "old", "date": "2026-01-01"},
            {"id": "target", "date": "2026-01-02"},
            {"id": "later", "date": "2026-01-03"},
        ]
        store = ReplayStateStore(Engine())
        out = store.capture(matches, target_ids={"target"})
        self.assertEqual(out["target"]["seen"], ("old",))


class HistoricalBacktestEngineTests(unittest.TestCase):
    def test_grades_moneyline_spread_and_total(self):
        from historical_backtest_engine import grade_market, profit_units

        result = {"winner": "Carlos Alcaraz", "loser": "Jannik Sinner", "games_winner": 18, "games_loser": 14}
        self.assertEqual(grade_market("moneyline", "Carlos Alcaraz", None, result), "WIN")
        self.assertEqual(grade_market("game_spread", "Jannik Sinner", 4.5, result), "WIN")
        self.assertEqual(grade_market("total_games_over", "OVER", 31.5, result), "WIN")
        self.assertEqual(grade_market("total_games_under", "UNDER", 31.5, result), "LOSS")
        self.assertAlmostEqual(profit_units("WIN", 2.50), 1.5)
        self.assertEqual(profit_units("LOSS", 2.50), -1.0)
        self.assertEqual(profit_units("PUSH", 2.50), 0.0)


if __name__ == "__main__":
    unittest.main()
