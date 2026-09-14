from pathlib import Path


def test_settlement_workflow_updates_official_performance_and_frozen_forecasts():
    text = Path(".github/workflows/v5_automatic_settlement.yml").read_text(encoding="utf-8")
    assert "python v5_settle_official_recommendations.py" in text
    assert "v5_daily_ready/official_recommendations.csv" in text
    assert "v5_daily_ready/official_performance.json" in text
    assert "v5_daily_ready/official_settlement_status.json" in text
    assert "v5_daily_ready/frozen_predictions.csv" in text
    assert "python diagnose_v5_settled_performance.py" not in text
    assert "python v5_settlement.py" not in text


def test_combined_settlement_code_updates_frozen_forecast_ledger_for_results_accuracy():
    text = Path("v5_settle_official_recommendations.py").read_text(encoding="utf-8")
    assert 'FROZEN_PATH = OUTDIR / "frozen_predictions.csv"' in text
    assert "settle_ledger(frozen" in text
    assert "forecast_settled" in text


def test_settlement_runs_after_final_history_recovery_without_prediction_fanout():
    text = Path(".github/workflows/v5_automatic_settlement.yml").read_text(encoding="utf-8")
    assert "schedule:" in text
    assert 'cron: "30 15 * * *"' in text
    assert 'workflows: ["V5 Player Ratings Refresh", "V5 Daily Predictions"]' not in text


def test_settlement_code_consumes_persisted_results_cache_not_upstream_network():
    legacy = Path("v5_settlement.py").read_text(encoding="utf-8")
    official = Path("v5_settle_official_recommendations.py").read_text(encoding="utf-8")
    assert "load_results_cache" in legacy
    assert "load_results_cache" in official
    assert "get_manifest" not in legacy
    assert "requests.get" not in legacy
