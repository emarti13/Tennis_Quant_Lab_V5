from pathlib import Path


def test_today_is_artifact_only_and_never_runs_production_inside_streamlit():
    source = Path("v5_ui_host.py").read_text(encoding="utf-8")
    assert "load_canonical_today_board" in source
    assert "run_interactive_production" not in source
    assert "Run entire daily board" not in source
    assert "Run manual recovery board" not in source
    assert "v5_daily_results" not in source
