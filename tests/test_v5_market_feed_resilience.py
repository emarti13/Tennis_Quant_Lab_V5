from pathlib import Path

import pandas as pd


def _sample(snapshot="2026-09-07T04:00:00Z", start="2026-09-08T14:00:00Z"):
    return pd.DataFrame([{
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
    }])


def test_stale_prices_do_not_erase_future_fixture_rows():
    from v5_live_market import current_market_rows, future_market_rows, market_feed_status
    frame = _sample()
    now = "2026-09-08T11:25:00Z"
    strict = current_market_rows(frame, now_utc=now)
    fixtures = future_market_rows(frame, now_utc=now)
    status = market_feed_status(frame, now_utc=now)
    assert strict.empty
    assert len(fixtures) == 1
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


def test_today_never_turns_stale_fixture_fallback_into_a_manual_model_run():
    source = Path("v5_ui_host.py").read_text(encoding="utf-8")
    assert "run_interactive_production" not in source
    assert "Run entire daily board" not in source
    assert "Run manual recovery board" not in source


def test_live_workflow_uses_one_quota_conserving_daily_schedule():
    text = Path(".github/workflows/oddspapi_normalized_daily_v2.yml").read_text(encoding="utf-8")
    trigger = text.split("permissions:", 1)[0]
    assert 'cron: "2 0 * * *"' in trigger
    assert trigger.count("cron:") == 1
    assert "\n  push:" not in trigger


def test_live_workflow_treats_quota_skip_as_controlled_state():
    text = Path(".github/workflows/oddspapi_normalized_daily_v2.yml").read_text(encoding="utf-8")
    assert "id: live_pull" in text
    assert "fresh_snapshot" in text
    assert "if: steps.live_pull.outputs.fresh_snapshot == 'true'" in text
    assert "oddspapi_daily/*_manifest.json" in text


def test_fresh_live_market_promotion_dispatches_daily_forecast_recovery():
    text = Path(".github/workflows/oddspapi_normalized_daily_v2.yml").read_text(encoding="utf-8")
    assert "actions: write" in text
    assert "Trigger daily forecast after fresh market promotion" in text
    assert "gh workflow run v5_daily_predictions.yml --ref main -R emarti13/Tennis_Quant_Lab_V5" in text
    assert text.index("Commit live feed and lightweight production artifacts") < text.index(
        "Trigger daily forecast after fresh market promotion"
    )


def test_one_time_recovery_workflow_is_removed_after_successful_use():
    assert not Path(".github/workflows/v5_recover_today_once.yml").exists()


def test_daily_predictions_use_recovery_windows_without_market_refresh_fanout():
    text = Path(".github/workflows/v5_daily_predictions.yml").read_text(encoding="utf-8")
    trigger = text.split("permissions:", 1)[0]
    assert trigger.count("cron:") == 3
    assert "workflow_run:" not in trigger
    assert "\n  push:" not in trigger
    assert "Check whether today's canonical forecast already exists" in text
    assert "python v5_build_daily_forecast_artifacts.py" in text
    assert "python v5_run_repricing.py" in text


def test_daily_forecast_publication_discards_ephemeral_generated_changes_before_rebase():
    text = Path(".github/workflows/v5_daily_predictions.yml").read_text(encoding="utf-8")
    commit_step = text.split("Commit canonical daily production artifacts safely", 1)[1]
    assert "git reset --hard HEAD" in commit_step
    assert commit_step.index("git reset --hard HEAD") < commit_step.index("git pull --rebase origin main")


def test_settlement_is_daily_after_history_recovery_not_chained_to_predictions():
    text = Path(".github/workflows/v5_automatic_settlement.yml").read_text(encoding="utf-8")
    assert 'cron: "30 15 * * *"' in text
    assert 'workflows: ["V5 Player Ratings Refresh", "V5 Daily Predictions"]' not in text


def test_historical_backfill_is_manual_only_while_quota_is_constrained():
    text = Path(".github/workflows/oddspapi_2026_backfill.yml").read_text(encoding="utf-8")
    trigger = text.split("permissions:", 1)[0]
    assert "workflow_dispatch:" in trigger
    assert "\n  schedule:" not in trigger


def test_player_ratings_use_retry_windows_but_skip_heavy_work_after_success():
    text = Path(".github/workflows/v5_player_ratings_refresh.yml").read_text(encoding="utf-8")
    trigger = text.split("permissions:", 1)[0]
    assert trigger.count("cron:") == 3
    assert 'cron: "0 6 * * *"' in trigger
    assert 'cron: "0 10 * * *"' in trigger
    assert 'cron: "0 14 * * *"' in trigger
    assert "Check whether today's history is already fresh" in text
    assert "if: steps.freshness.outputs.history_fresh != 'true'" in text
    assert "python v5_results_cache.py" in text
