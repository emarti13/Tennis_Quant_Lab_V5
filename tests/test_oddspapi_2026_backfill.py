from __future__ import annotations

import unittest
from datetime import datetime, timezone

from backfill_oddspapi_2026 import iter_windows, START_UTC, WINDOW_DAYS


class BackfillWindowTests(unittest.TestCase):
    def test_fixture_windows_stay_under_ten_days(self):
        end = datetime(2026, 2, 1, tzinfo=timezone.utc)
        windows = list(iter_windows(START_UTC, end))
        self.assertTrue(windows)
        for start, stop in windows:
            self.assertLess((stop - start).total_seconds(), 10 * 24 * 3600)
            self.assertLessEqual((stop - start).days, WINDOW_DAYS)

    def test_windows_cover_period_without_gaps(self):
        end = datetime(2026, 2, 1, tzinfo=timezone.utc)
        windows = list(iter_windows(START_UTC, end))
        self.assertEqual(windows[0][0], START_UTC)
        self.assertEqual(windows[-1][1], end)
        for left, right in zip(windows, windows[1:]):
            self.assertEqual(left[1], right[0])


if __name__ == "__main__":
    unittest.main()
