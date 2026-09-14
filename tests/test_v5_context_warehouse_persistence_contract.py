from pathlib import Path


def test_context_warehouse_workflow_persists_canonical_outputs_and_runs_daily():
    source = Path('.github/workflows/v5_context_warehouse.yml').read_text(encoding='utf-8')
    assert 'schedule:' in source
    assert 'contents: write' in source
    assert 'v5-production-writer' in source
    assert 'context_warehouse/matches.parquet' in source
    assert 'context_warehouse/player_match_rows.parquet' in source
    assert 'context_warehouse/source_manifest.json' in source
    assert 'context_warehouse/schema.json' in source
    assert 'git add context_warehouse/matches.parquet' in source
    assert 'git push origin HEAD:main' in source
