from pathlib import Path

import pandas as pd


def _sample(snapshot="2026-09-07T04:00:00Z", start="2026-09-08T14:00:00Z"):
    return pd.DataFrame([
        {
            "snapshot_utc": snapshot,
            "fixture_id": "fx1",
            "start_time_utc": start,
            "tournament": "Test",
            "tour": "ATP",
            "player1": "A",
            "player2": "B",
            "market_group": "moneyline",
            "selection": "A",
            "best_american_odds": -120,
        }
    ])


def test_stale_prices_do_not_erase_future_fixture_rows():
    from v5_live_market import current_market_rows, future_market_rows, market_feed_status

    frame = _sample()
    now = "2026-09-08T11:25:00Z"

    strict = current_market_rows(frame, now_utc=now)
    fixtures = future_market_rows(frame, now_utc=now)
    status = market_feed_status(frame, now_utc=now)

    assert strict.empty, "stale prices must remain unusable for market recommendations"
    assert len(fixtures) == 1, "future fixtures must survive even when prices are stale"
    assert status["available"] is True
    assert status["fresh"] is False
    assert status["future_fixture_count"] == 1
    assert status["state"] == "stale_prices"


def test_missing_feed_and_no_future_fixtures_are_distinct_states():
    from v5_live_market import market_feed_status

    missing = market_feed_status(pd.DataFrame(), now_utc="2026-09-08T11:25:00Z")
    expired = market_feed_status(
        _sample(snapshot="2026-09-08T10:00:00Z", start="2026-09-08T10:30:00Z"),
        now_utc="2026-09-08T11:25:00Z",
    )

    assert missing["state"] == "missing"
    assert expired["fresh"] is True
    assert expired["state"] == "no_future_fixtures"


def test_live_workflow_uses_even_six_hour_schedule():
    text = Path(".github/workflows/oddspapi_normalized_daily_v2.yml").read_text(encoding="utf-8")
    assert "15 0,6,12,18 * * *" in text
    assert "15 0,12,16,20 * * *" not in text
