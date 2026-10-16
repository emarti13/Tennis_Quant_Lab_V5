from pathlib import Path

import pandas as pd


def _feed(snapshot="2026-09-14T00:02:00Z", start="2026-09-15T18:00:00Z"):
    return pd.DataFrame([{
        "snapshot_utc": snapshot,
        "fixture_id": "fx1",
        "start_time_utc": start,
    }])


def test_shared_runtime_state_keeps_prices_actionable_until_24_hours_old():
    from v5_ui_production import runtime_production_state

    state = runtime_production_state(
        _feed(),
        {"freshness": "READY"},
        now_utc="2026-09-14T23:59:00Z",
    )

    assert state["state"] == "READY"
    assert state["feed_status"]["fresh"] is True


def test_shared_runtime_state_marks_prices_stale_after_24_hours():
    from v5_ui_production import runtime_production_state

    state = runtime_production_state(
        _feed(),
        {"freshness": "READY"},
        now_utc="2026-09-15T00:03:00Z",
    )

    assert state["state"] == "STALE_PRICES"
    assert state["feed_status"]["fresh"] is False


def test_fresh_canonical_prices_cannot_be_overridden_by_stale_downstream_price_state():
    from v5_ui_production import runtime_production_state

    state = runtime_production_state(
        _feed(snapshot="2026-09-21T03:38:12Z", start="2026-09-22T18:00:00Z"),
        {
            "freshness": "STALE_PRICES",
            "source_version": "2026-09-20T03:43:31Z",
        },
        now_utc="2026-09-21T04:00:00Z",
    )

    assert state["state"] == "READY"
    assert state["feed_status"]["snapshot_utc"] == "2026-09-21T03:38:12+00:00"
    assert state["feed_status"]["fresh"] is True


def test_fresh_prices_keep_forecast_freshness_as_a_separate_failure_domain():
    from v5_ui_production import runtime_production_state

    state = runtime_production_state(
        _feed(snapshot="2026-09-21T03:38:12Z", start="2026-09-22T18:00:00Z"),
        {
            "freshness": "STALE_FORECAST",
            "source_version": "2026-09-21T03:38:12Z",
        },
        now_utc="2026-09-21T04:00:00Z",
    )

    assert state["state"] == "STALE_FORECAST"
    assert state["feed_status"]["fresh"] is True


def test_daily_board_and_decision_feed_use_same_runtime_state_helper():
    host = Path("v5_ui_host.py").read_text(encoding="utf-8")
    daily = Path("v5_ui_daily_board.py").read_text(encoding="utf-8")

    assert "runtime_production_state(" in host
    assert "runtime_production_state(" in daily


def test_live_workflow_refreshes_prices_once_per_day_without_starting_the_paused_forecast():
    text = Path(".github/workflows/oddspapi_normalized_daily_v2.yml").read_text(encoding="utf-8")
    trigger = text.split("permissions:", 1)[0]

    assert 'cron: "2 0 * * *"' in trigger
    assert trigger.count("cron:") == 1

    # The daily forecast is paused until rebuild Step 4 (user decision 2026-10-16).
    assert "Trigger daily forecast after fresh market promotion" not in text
