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

    def test_tournaments_are_batched_to_api_maximum_of_five(self):
        self.assertEqual(
            tournament_request_groups([11, 22, 33, 44, 55, 66, 77]),
            [[11, 22, 33, 44, 55], [66, 77]],
        )

    def test_primary_book_is_daily_when_above_reserve(self):
        now = datetime(2026, 9, 1, tzinfo=timezone.utc)
        self.assertEqual(books_for_today(now, remaining=172), ["pinnacle"])

    def test_secondary_is_only_weekly_and_with_headroom(self):
        # 2026-09-06 is Sunday UTC.
        now = datetime(2026, 9, 6, tzinfo=timezone.utc)
        self.assertEqual(books_for_today(now, remaining=172), ["pinnacle", "betrivers"])
        self.assertEqual(books_for_today(now, remaining=70), ["pinnacle"])

    def test_live_production_can_consume_quota_reserved_from_backfill(self):
        # The 50-call reserve exists to protect live production FROM backfill.
        # Live production itself must be allowed to use those protected calls.
        now = datetime(2026, 9, 1, tzinfo=timezone.utc)
        self.assertEqual(books_for_today(now, remaining=50), ["pinnacle"])

    def test_live_pull_stops_only_when_minimum_live_request_cannot_fit(self):
        now = datetime(2026, 9, 1, tzinfo=timezone.utc)
        self.assertEqual(books_for_today(now, remaining=1), [])


if __name__ == "__main__":
    unittest.main()
