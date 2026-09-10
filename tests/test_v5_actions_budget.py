from pathlib import Path

from v5_actions_budget import configured_monthly_minutes


def _text(name):
    return Path('.github/workflows').joinpath(name).read_text(encoding='utf-8')


def test_configured_recurring_budget_stays_below_70_percent_of_allowance():
    report = configured_monthly_minutes()
    assert report['allowance_minutes'] == 3000
    assert report['guardrail_minutes'] == 2100
    assert report['projected_minutes'] < report['guardrail_minutes']
    assert report['headroom_to_allowance'] >= 900


def test_live_market_is_four_lightweight_runs_and_performs_repricing():
    text = _text('oddspapi_normalized_daily_v2.yml')
    trigger = text.split('permissions:', 1)[0]
    assert '15 0,6,12,18 * * *' in trigger
    assert 'workflow_dispatch:' in trigger
    assert '\n  push:' not in trigger
    assert 'python v5_run_repricing.py' in text
    assert 'build_v5_context_warehouse.py' not in text
    assert 'python -m pytest' not in text


def test_heavy_forecast_runs_once_daily_and_never_on_push():
    text = _text('v5_daily_predictions.yml')
    trigger = text.split('permissions:', 1)[0]
    assert 'schedule:' in trigger
    assert trigger.count('cron:') == 1
    assert 'workflow_dispatch:' in trigger
    assert '\n  push:' not in trigger
    assert 'workflow_run:' not in trigger
    assert 'python v5_build_daily_forecast_artifacts.py' in text
    assert 'python v5_run_repricing.py' in text
    assert 'python -m pytest' not in text


def test_settlement_is_once_daily_and_never_on_push():
    text = _text('v5_automatic_settlement.yml')
    trigger = text.split('permissions:', 1)[0]
    assert trigger.count('cron:') == 1
    assert 'workflow_dispatch:' in trigger
    assert '\n  push:' not in trigger
    assert 'workflow_run:' not in trigger
    assert 'python v5_settle_official_recommendations.py' in text
    assert 'python -m pytest' not in text


def test_historical_backfill_is_weekly_not_daily():
    backfill = _text('oddspapi_2026_backfill.yml')
    trigger = backfill.split('permissions:', 1)[0]
    assert '45 3 * * 0' in trigger
    assert trigger.count('cron:') == 1
    assert 'workflow_dispatch:' in trigger


def test_ratings_remain_one_daily_refresh():
    ratings = _text('v5_player_ratings_refresh.yml')
    assert ratings.split('permissions:', 1)[0].count('cron:') == 1


def test_context_and_score_acceptance_are_intentional_manual_gates_not_push_fanout():
    for name in ('v5_context_diagnostic.yml', 'v5_score_acceptance.yml'):
        text = _text(name)
        trigger_block = text.split('permissions:', 1)[0]
        assert 'workflow_dispatch:' in trigger_block
        assert '\n  push:' not in trigger_block
        assert '\n  schedule:' not in trigger_block


def test_research_diagnostics_are_manual_only():
    for name in (
        'v5_total_length_diagnostic.yml',
        'v5_model_bias_diagnostics.yml',
        'v5_margin_calibration_diagnostic.yml',
        'v5_superpowers_completion.yml',
    ):
        text = _text(name)
        trigger_block = text.split('permissions:', 1)[0] if 'permissions:' in text else text.split('jobs:', 1)[0]
        assert 'workflow_dispatch:' in trigger_block
        assert '\n  push:' not in trigger_block
        assert '\n  schedule:' not in trigger_block


def test_full_regression_runs_on_pull_requests_or_manual_dispatch_not_every_main_python_push():
    text = _text('v5_full_test_suite.yml')
    trigger_block = text.split('permissions:', 1)[0]
    assert 'workflow_dispatch:' in trigger_block
    assert 'pull_request:' in trigger_block
    assert '\n  push:' not in trigger_block


def test_probe_and_research_workflows_are_not_scheduled_background_jobs():
    probe_names = (
        'oddspapi_fixture_cost_probe.yml',
        'oddspapi_historical_fixture_probe.yml',
        'oddspapi_probe.yml',
        'oddspapi_relevant_slate_probe_v2.yml',
    )
    for name in probe_names:
        text = _text(name)
        trigger_block = text.split('permissions:', 1)[0] if 'permissions:' in text else text.split('jobs:', 1)[0]
        assert 'workflow_dispatch:' in trigger_block
        assert '\n  schedule:' not in trigger_block
