from pathlib import Path


def test_settlement_workflow_generates_and_commits_clustered_performance_audit():
    text = Path(".github/workflows/v5_automatic_settlement.yml").read_text(encoding="utf-8")
    assert "python diagnose_v5_settled_performance.py" in text
    assert "v5_daily_ready/settled_performance_audit.json" in text


def test_settlement_runs_after_daily_predictions_and_on_daily_schedule():
    text = Path(".github/workflows/v5_automatic_settlement.yml").read_text(encoding="utf-8")
    assert '"V5 Daily Predictions"' in text
    assert "schedule:" in text
    assert "cron:" in text
