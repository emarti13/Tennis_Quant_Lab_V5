import unittest
from datetime import datetime, timezone

from pull_oddspapi_quota_aware import quota_state, books_for_today, tournament_request_groups


class OddsPapiQuotaPolicyTests(unittest.TestCase):
    def test_reads_active_subscription_quota(self):
        account = {
            "current_subscription_id": "sub1",
            "subscriptions": [
                {"subscription_id": "sub1", "is_active": True, "request_limit": 250, "request_count": 78}
            ],
        }
        q = quota_state(account)
        self.assertEqual(q["limit"], 250)
        self.assertEqual(q["used"], 78)
        self.assertEqual(q["remaining"], 172)

    def test_all_tournaments_are_sent_in_one_odds_request(self):
        self.assertEqual(tournament_request_groups([11, 22, 33, 44, 55, 66]), [[11, 22, 33, 44, 55, 66]])

    def test_primary_book_is_daily_when_above_reserve(self):
        now = datetime(2026, 9, 1, tzinfo=timezone.utc)
        self.assertEqual(books_for_today(now, remaining=172), ["pinnacle"])

    def test_secondary_is_only_weekly_and_with_headroom(self):
        # 2026-09-06 is Sunday UTC.
        now = datetime(2026, 9, 6, tzinfo=timezone.utc)
        self.assertEqual(books_for_today(now, remaining=172), ["pinnacle", "betrivers"])
        self.assertEqual(books_for_today(now, remaining=70), ["pinnacle"])

    def test_live_pull_stops_at_protected_reserve(self):
        now = datetime(2026, 9, 1, tzinfo=timezone.utc)
        self.assertEqual(books_for_today(now, remaining=50), [])


if __name__ == "__main__":
    unittest.main()
