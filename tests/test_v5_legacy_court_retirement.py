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


def test_authority_is_the_only_runtime_tournament_court_source():
    for path in ("v5_daily_batch.py", "v5_full_context_live.py"):
        source = Path(path).read_text(encoding="utf-8")
        assert "v5_tournament_authority" in source
        assert "resolve_authority" in source


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
