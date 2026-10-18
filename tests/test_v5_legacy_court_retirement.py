from pathlib import Path


def test_context_builder_no_longer_derives_legacy_court_speed():
    source = Path("build_v5_context_matchups.py").read_text(encoding="utf-8")
    assert "from v5_court_speed import" not in source
    assert "add_derived_court_speed_features" not in source


def test_production_runtime_no_longer_imports_legacy_court_conditions():
    for path in ("v5_daily_batch.py", "v5_full_context_live.py"):
        source = Path(path).read_text(encoding="utf-8")
        assert "v5_court_conditions_source" not in source
        assert "resolve_court_conditions" not in source
        assert "CourtSpeed canonical conditions" not in source


def test_master_schedule_is_the_only_runtime_tournament_court_source():
    # Rebuild plan Step 4g: production takes surface, setting and best-of only from the master
    # schedule through v5_fixture_resolution (CLAUDE.md), via the one pricing function.
    for path in ("v5_daily_batch.py", "v5_interactive_production.py", "v5_ui_production.py", "v5_ui_daily_board.py"):
        source = Path(path).read_text(encoding="utf-8")
        for retired in ("v5_tournament_authority", "resolve_authority", "v5_master_schedule_context",
                        "v5_tournament_context_registry", "tennis_master_schedule.csv"):
            assert retired not in source, (path, retired)
    assert "from v5_fixture_resolution import" in Path("v5_pricing.py").read_text(encoding="utf-8")


def test_context_builder_neutralizes_retired_court_characteristics():
    source = Path("build_v5_context_matchups.py").read_text(encoding="utf-8")
    assert '"court_speed": np.nan' in source
    assert '"altitude_m": np.nan' in source


def test_retired_court_code_and_workflows_are_gone():
    for path in (
        "v5_court_conditions_source.py", "v5_court_speed.py", "v5_courtspeed_fetch.py",
        "v5_refresh_court_conditions.py", "retire_legacy_court_paths.py", "data/court_conditions",
        ".github/workflows/courtspeed_conditions_refresh.yml", ".github/workflows/v5_court_speed.yml",
    ):
        assert not Path(path).exists(), path
