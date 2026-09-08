from pathlib import Path


def test_settlement_workflow_generates_official_and_legacy_performance_artifacts():
    text = Path(".github/workflows/v5_automatic_settlement.yml").read_text(encoding="utf-8")
    assert "python v5_settle_official_recommendations.py" in text
    assert "v5_daily_ready/official_performance.json" in text
    assert "python diagnose_v5_settled_performance.py" in text
    assert "v5_daily_ready/settled_performance_audit.json" in text


def test_settlement_runs_on_daily_schedule_without_prediction_chain_fanout():
    text = Path(".github/workflows/v5_automatic_settlement.yml").read_text(encoding="utf-8")
    assert "schedule:" in text
    assert 'cron: "30 10 * * *"' in text
    assert "workflow_run:" not in text
