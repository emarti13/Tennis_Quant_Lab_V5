from pathlib import Path


def test_context_warehouse_workflow_persists_canonical_outputs_and_is_chained_to_results_snapshot():
    source = Path('.github/workflows/v5_context_warehouse.yml').read_text(encoding='utf-8')
    assert 'contents: write' in source
    assert 'v5-production-writer' in source
    assert "'v5_results_ready/tennismylife_results.csv'" in source
    assert "'v5_results_ready/results_status.json'" in source
    assert 'Require canonical current results snapshot' in source
    assert "p.get('state') != 'READY'" in source
    assert 'context_warehouse/matches.parquet' in source
    assert 'context_warehouse/player_match_rows.parquet' in source
    assert 'context_warehouse/source_manifest.json' in source
    assert 'context_warehouse/schema.json' in source
    assert 'git add context_warehouse/matches.parquet' in source
    assert 'git push origin HEAD:main' in source
    # Do not let an independent clock rebuild from a different upstream snapshot.
    assert 'cron:' not in source
