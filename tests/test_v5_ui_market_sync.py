from pathlib import Path

import pandas as pd


def _feed(snapshot="2026-09-14T00:02:00Z", start="2026-09-14T18:00:00Z"):
    return pd.DataFrame([{
        "snapshot_utc": snapshot,
        "fixture_id": "fx1",
        "start_time_utc": start,
    }])


def test_shared_runtime_state_marks_stale_prices_before_ui_rendering():
    from v5_ui_production import runtime_production_state

    state = runtime_production_state(
        _feed(),
        {"freshness": "READY"},
        now_utc="2026-09-14T13:30:00Z",
    )

    assert state["state"] == "STALE_PRICES"
    assert state["feed_status"]["fresh"] is False


def test_daily_board_and_decision_feed_use_same_runtime_state_helper():
    host = Path("v5_ui_host.py").read_text(encoding="utf-8")
    daily = Path("v5_ui_daily_board.py").read_text(encoding="utf-8")

    assert "runtime_production_state(" in host
    assert "runtime_production_state(" in daily


def test_live_workflow_refreshes_prices_four_times_per_day_without_rebuilding_frozen_forecast_each_time():
    text = Path(".github/workflows/oddspapi_normalized_daily_v2.yml").read_text(encoding="utf-8")
    trigger = text.split("permissions:", 1)[0]

    for cron in (
        'cron: "2 0 * * *"',
        'cron: "2 6 * * *"',
        'cron: "2 12 * * *"',
        'cron: "2 18 * * *"',
    ):
        assert cron in trigger
    assert trigger.count("cron:") == 4

    dispatch = text.split("Trigger daily forecast after fresh market promotion", 1)[1]
    assert "github.event_name == 'workflow_dispatch'" in dispatch
    assert "github.event.schedule == '2 0 * * *'" in dispatch
