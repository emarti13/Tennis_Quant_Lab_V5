from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import v5_season_files as seasons


def _utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


def test_history_and_current_season_split_moves_with_the_calendar():
    assert seasons.history_end_year(_utc(2026, 10, 12)) == 2025
    assert seasons.history_end_year(_utc(2027, 1, 1)) == 2026
    assert seasons.history_cache_key(_utc(2026, 10, 12)) == "v5-tennis-history-2010-2025-v4"
    assert seasons.history_cache_key(_utc(2027, 1, 1)) == "v5-tennis-history-2010-2026-v4"


def test_previous_season_files_are_kept_only_in_the_new_season_grace_window():
    assert seasons.recent_season_years(_utc(2026, 10, 12)) == (2026,)
    assert seasons.recent_season_years(_utc(2027, 1, 3)) == (2026, 2027)
    assert seasons.recent_season_years(_utc(2027, 2, 15)) == (2027,)


def test_state_builder_sources_follow_season_years_not_a_fixed_year():
    men = seasons.season_sources("MEN", (2027,))
    assert men == [
        ("2027.csv", "Main"),
        ("2027_atp_quali.csv", "Qualifying"),
        ("2027_challenger.csv", "Challenger"),
    ]
    assert seasons.season_sources("WTA", (2026, 2027)) == [("2026_wta.csv", "Main"), ("2027_wta.csv", "Main")]

    source = Path("build_v5_states.py").read_text(encoding="utf-8")
    assert '"2026' not in source
    assert "season_sources(" in source


def test_results_cache_uses_rolling_season_files():
    from v5_results_cache import default_result_files

    files = default_result_files(_utc(2027, 1, 5))
    assert "2026.csv" in files and "2027_wta.csv" in files
    assert "ongoing_tourneys.csv" in files
    assert "2026.csv" not in default_result_files(_utc(2027, 3, 1))


def test_refresh_targets_tolerate_unpublished_new_season_only_in_grace_window():
    import refresh_tennismylife_cloud as refresh

    targets, optional = refresh.build_targets(_utc(2027, 1, 2))
    assert {"2026.csv", "2027.csv", "2027_wta.csv"} <= set(targets)
    assert "2027.csv" in optional and "ongoing_tourneys.csv" not in optional

    targets, optional = refresh.build_targets(_utc(2027, 5, 1))
    assert "2026.csv" not in targets
    assert optional == set()


def test_bootstrap_rebuilds_a_cache_that_does_not_cover_last_season(tmp_path, monkeypatch):
    import bootstrap_v5_history as boot

    cache = tmp_path / ".v5_history_cache"
    cache.mkdir()
    for name in boot.OUTPUTS:
        (cache / name).write_text("x\n1\n", encoding="utf-8")
    assert boot.cache_is_current(cache) is False  # no coverage record (pre-v4 cache)

    (cache / boot.COVERAGE_FILE).write_text(json.dumps({"start_year": 2010, "end_year": boot.END_YEAR - 1}))
    assert boot.cache_is_current(cache) is False

    (cache / boot.COVERAGE_FILE).write_text(json.dumps({"start_year": 2010, "end_year": boot.END_YEAR}))
    assert boot.cache_is_current(cache) is True


def test_bootstrap_refuses_history_that_skips_last_season(tmp_path, monkeypatch):
    import pytest
    import bootstrap_v5_history as boot

    monkeypatch.chdir(tmp_path)
    old = boot.END_YEAR - 1
    manifest = [
        {"name": f"{old}.csv", "url": "u"},
        {"name": f"{old}_atp_quali.csv", "url": "u"},
        {"name": f"{old}_challenger.csv", "url": "u"},
        {"name": f"{old}_wta.csv", "url": "u"},
    ]
    monkeypatch.setattr(boot, "fetch_manifest", lambda: manifest)
    with pytest.raises(RuntimeError, match="skips a season"):
        boot.main()


def test_refresh_log_does_not_store_build_output(tmp_path):
    import refresh_tennismylife_cloud as refresh

    refresh.log(tmp_path, {"type": "refresh_success", "build": {"returncode": 0, "stdout_tail": "x" * 5000}})
    line = json.loads((tmp_path / refresh.LOG_FILE).read_text(encoding="utf-8").strip())
    assert line["build"] == {"returncode": 0}


def test_ratings_workflow_cache_key_is_derived_not_hardcoded():
    for wf in ("v5_player_ratings_refresh.yml",):
        text = Path(".github/workflows", wf).read_text(encoding="utf-8")
        assert "2010-2025" not in text
        assert "v5_season_files.py cache-key" in text
