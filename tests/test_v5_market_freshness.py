import pathlib
import sys
import unittest

import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from v5_live_market import current_market_rows


class MarketFreshnessTests(unittest.TestCase):
    def test_removes_started_fixtures(self):
        df = pd.DataFrame([
            {
                "snapshot_utc": "2026-09-01T12:15:00Z",
                "start_time_utc": "2026-09-01T13:00:00Z",
                "fixture_id": "past",
            },
            {
                "snapshot_utc": "2026-09-01T12:15:00Z",
                "start_time_utc": "2026-09-01T18:00:00Z",
                "fixture_id": "future",
            },
        ])
        out = current_market_rows(df, now_utc="2026-09-01T15:00:00Z")
        self.assertEqual(out["fixture_id"].tolist(), ["future"])

    def test_rejects_stale_snapshot(self):
        df = pd.DataFrame([
            {
                "snapshot_utc": "2026-08-31T19:08:17Z",
                "start_time_utc": "2026-09-01T18:00:00Z",
                "fixture_id": "future-but-stale-price",
            }
        ])
        out = current_market_rows(
            df,
            now_utc="2026-09-01T15:21:00Z",
            max_snapshot_age_hours=13,
        )
        self.assertTrue(out.empty)
        self.assertTrue(out.attrs.get("stale_market_feed"))

    def test_keeps_future_rows_from_fresh_snapshot(self):
        df = pd.DataFrame([
            {
                "snapshot_utc": "2026-09-01T12:15:00Z",
                "start_time_utc": "2026-09-01T18:00:00Z",
                "fixture_id": "future",
            }
        ])
        out = current_market_rows(
            df,
            now_utc="2026-09-01T15:21:00Z",
            max_snapshot_age_hours=13,
        )
        self.assertEqual(len(out), 1)
        self.assertFalse(out.attrs.get("stale_market_feed", False))


class EmptyAllPricesTests(unittest.TestCase):
    def test_empty_all_book_prices_file_returns_empty_frame(self):
        import tempfile
        from pathlib import Path
        import v5_live_market

        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp) / "all_book_prices.csv"
            empty.write_text("", encoding="utf-8")
            original = v5_live_market.ALL_PRICE_CANDIDATES
            v5_live_market.ALL_PRICE_CANDIDATES = [empty]
            try:
                result = v5_live_market.load_all_book_prices()
            finally:
                v5_live_market.ALL_PRICE_CANDIDATES = original

        self.assertTrue(result.empty)


if __name__ == "__main__":
    unittest.main()
