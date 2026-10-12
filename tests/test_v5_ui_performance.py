from __future__ import annotations

import json
from pathlib import Path


def test_performance_headline_keeps_raw_markets_and_fixture_results_separate():
    from v5_ui_performance import headline_metrics

    report = {
        "raw_markets": {
            "bets": 5, "wins": 3, "losses": 2, "pushes": 0,
            "win_rate": 0.60, "net_units": 0.5, "roi": 0.10,
        },
        "fixture_clusters": {
            "fixtures": 3, "profitable_fixtures": 1, "losing_fixtures": 2,
            "flat_fixtures": 0, "profitable_fixture_rate": 1 / 3,
            "mean_markets_per_fixture": 5 / 3, "max_markets_on_one_fixture": 3,
            "net_units": 0.5,
        },
    }
    out = headline_metrics(report)
    assert out["market_win_rate"] == 0.60
    assert out["fixture_profitable_rate"] == 1 / 3
    assert out["market_record"] == "3-2-0"
    assert out["fixture_record"] == "1 profitable / 3"
    assert out["max_correlated_markets"] == 3
    assert out["market_label"] != out["fixture_label"]


def test_official_recommendations_override_legacy_audit_for_headline():
    from v5_ui_performance import headline_metrics

    report = {
        "official": {
            "official_recommendations": 4,
            "unique_fixtures": 3,
            "wins": 3,
            "losses": 1,
            "pushes": 0,
            "win_rate": 0.75,
            "net_units": 1.6,
            "roi": 0.40,
            "max_recommendations_per_fixture": 2,
            "fixture_cluster": {
                "fixtures": 3,
                "profitable_fixtures": 2,
                "profitable_fixture_rate": 2 / 3,
                "net_units": 1.6,
            },
        },
        "legacy": {
            "raw_markets": {"bets": 3000, "wins": 1400, "losses": 1600, "pushes": 0, "win_rate": 0.466, "net_units": -200, "roi": -0.067},
            "fixture_clusters": {"fixtures": 200, "profitable_fixtures": 80, "profitable_fixture_rate": 0.4, "max_markets_on_one_fixture": 40, "net_units": -200},
        },
    }
    out = headline_metrics(report)
    assert out["scope"] == "official"
    assert out["market_record"] == "3-1-0"
    assert out["fixture_record"] == "2 profitable / 3"
    assert out["max_correlated_markets"] == 2


def test_load_performance_report_prefers_official_and_keeps_legacy_audit_without_reset(tmp_path):
    from v5_ui_performance import load_performance_report

    missing = load_performance_report(tmp_path)
    assert missing["status"] == "missing"

    target = tmp_path / "v5_daily_ready"
    target.mkdir(parents=True)
    legacy = {
        "status": "ok",
        "raw_markets": {"bets": 2, "wins": 1, "losses": 1, "pushes": 0, "win_rate": 0.5, "net_units": 0.0, "roi": 0.0},
        "fixture_clusters": {"fixtures": 2, "profitable_fixtures": 1, "losing_fixtures": 1, "flat_fixtures": 0, "profitable_fixture_rate": 0.5, "mean_markets_per_fixture": 1.0, "max_markets_on_one_fixture": 1, "net_units": 0.0},
    }
    official = {"official_recommendations": 1, "unique_fixtures": 1, "wins": 1, "losses": 0, "pushes": 0, "win_rate": 1.0, "net_units": 1.0, "roi": 1.0, "max_recommendations_per_fixture": 1, "fixture_cluster": {"fixtures": 1, "profitable_fixtures": 1, "profitable_fixture_rate": 1.0, "net_units": 1.0}}
    (target / "settled_performance_audit.json").write_text(json.dumps(legacy), encoding="utf-8")
    (target / "official_performance.json").write_text(json.dumps(official), encoding="utf-8")

    loaded = load_performance_report(tmp_path)
    assert loaded["status"] == "ok"
    assert loaded["official"]["official_recommendations"] == 1
    assert loaded["legacy"]["raw_markets"]["bets"] == 2


def test_reset_epoch_suppresses_legacy_fallback_and_allows_zero_official_record(tmp_path):
    from v5_ui_performance import headline_metrics, load_performance_report

    target = tmp_path / "v5_daily_ready"
    target.mkdir(parents=True)
    (target / "results_reset.json").write_text(json.dumps({"reset_at_utc": "2026-09-14T16:26:28Z"}), encoding="utf-8")
    (target / "official_performance.json").write_text(json.dumps({
        "official_recommendations": 0,
        "unique_fixtures": 0,
        "wins": 0,
        "losses": 0,
        "pushes": 0,
        "roi": None,
        "net_units": 0.0,
        "fixture_cluster": {"fixtures": 0, "profitable_fixtures": 0},
    }), encoding="utf-8")
    (target / "settled_performance_audit.json").write_text(json.dumps({
        "raw_markets": {"bets": 999, "wins": 999, "losses": 0},
    }), encoding="utf-8")

    loaded = load_performance_report(tmp_path)
    assert loaded["legacy"] == {}
    out = headline_metrics(loaded)
    assert out["scope"] == "official"
    assert out["market_record"] == "0-0-0"


def test_performance_page_copy_allows_multiple_official_markets_and_excludes_ancillary_observations():
    source = Path("v5_ui_performance.py").read_text(encoding="utf-8")
    # Customer copy: up to one official market per family per fixture; alternate lines excluded.
    assert "one official moneyline, one spread and one total per fixture" in source.lower()
    assert "alternate lines are pricing candidates, not separate bets" in source.lower()
