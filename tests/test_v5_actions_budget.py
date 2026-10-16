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
    assert 'courtspeed_conditions' not in report['jobs']  # retired


def test_every_scheduled_workflow_is_budgeted():
    import re
    from v5_actions_budget import RECURRING_JOBS, SCHEDULED_WORKFLOWS

    scheduled = {}
    for path in Path('.github/workflows').glob('*.yml'):
        trigger = path.read_text(encoding='utf-8').split('\njobs:', 1)[0]
        crons = re.findall(r'^\s*-\s*cron:', trigger, flags=re.M)
        if crons:
            scheduled[path.name] = len(crons)
    assert scheduled == {name: cfg['crons'] for name, cfg in SCHEDULED_WORKFLOWS.items()}
    for cfg in SCHEDULED_WORKFLOWS.values():
        assert all(job in RECURRING_JOBS for job in cfg['jobs'])


def test_live_market_is_one_quota_conserving_run_and_performs_repricing():
    text = _text('oddspapi_normalized_daily_v2.yml')
    trigger = text.split('permissions:', 1)[0]
    assert '2 0 * * *' in trigger
    assert trigger.count('cron:') == 1
    assert 'workflow_dispatch:' in trigger
    assert '\n  push:' not in trigger
    assert 'python v5_run_repricing.py' in text
    assert 'build_v5_context_warehouse.py' not in text
    assert 'python -m pytest' not in text


def test_heavy_forecast_is_paused_until_step4_but_still_runnable_by_hand():
    # User decision 2026-10-16: the old engine's board is unused; no schedule until Step 4.
    text = _text('v5_daily_predictions.yml')
    trigger = text.split('permissions:', 1)[0]
    assert '\n  schedule:' not in trigger
    assert 'workflow_dispatch:' in trigger
    assert '\n  push:' not in trigger
    assert 'workflow_run:' not in trigger
    assert "Check whether today's canonical forecast already exists" in text
    assert "artifact_date == expected_date" in text
    assert "America/New_York" in text
    assert "if: steps.forecast.outputs.forecast_fresh != 'true'" in text
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
    assert 'python v5_settlement.py' not in text
    assert 'python -m pytest' not in text


def test_canonical_production_writers_share_one_serialization_lock():
    # courtspeed_conditions_refresh.yml is retired (echo-only) and writes nothing.
    for name in ('oddspapi_normalized_daily_v2.yml', 'v5_daily_predictions.yml', 'v5_automatic_settlement.yml'):
        text = _text(name)
        assert 'group: v5-production-writer' in text
        assert 'cancel-in-progress: false' in text


def test_historical_backfill_is_manual_only_while_quota_is_constrained():
    backfill = _text('oddspapi_2026_backfill.yml')
    trigger = backfill.split('permissions:', 1)[0]
    assert 'workflow_dispatch:' in trigger
    assert '\n  schedule:' not in trigger


def test_ratings_have_recovery_windows_and_skip_after_success():
    ratings = _text('v5_player_ratings_refresh.yml')
    trigger = ratings.split('permissions:', 1)[0]
    assert trigger.count('cron:') == 3
    assert "Check whether today's history is already fresh" in ratings
    assert "if: steps.freshness.outputs.history_fresh != 'true'" in ratings
    assert 'python v5_results_cache.py' in ratings


def test_context_and_score_acceptance_are_intentional_manual_gates_not_push_fanout():
    for name in ('v5_context_diagnostic.yml', 'v5_score_acceptance.yml'):
        text = _text(name)
        trigger_block = text.split('permissions:', 1)[0]
        assert 'workflow_dispatch:' in trigger_block
        assert '\n  push:' not in trigger_block
        assert '\n  schedule:' not in trigger_block


def test_research_diagnostics_are_manual_only():
    for name in (
        'v5_model_bias_diagnostics.yml',
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
