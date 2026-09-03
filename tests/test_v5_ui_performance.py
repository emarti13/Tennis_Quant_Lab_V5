from __future__ import annotations

import json


def test_performance_headline_keeps_raw_markets_and_fixture_results_separate():
    from v5_ui_performance import headline_metrics

    report = {
        "raw_markets": {
            "bets": 5,
            "wins": 3,
            "losses": 2,
            "pushes": 0,
            "win_rate": 0.60,
            "net_units": 0.5,
            "roi": 0.10,
        },
        "fixture_clusters": {
            "fixtures": 3,
            "profitable_fixtures": 1,
            "losing_fixtures": 2,
            "flat_fixtures": 0,
            "profitable_fixture_rate": 1 / 3,
            "mean_markets_per_fixture": 5 / 3,
            "max_markets_on_one_fixture": 3,
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


def test_load_performance_report_handles_missing_and_valid_artifacts(tmp_path):
    from v5_ui_performance import load_performance_report

    missing = load_performance_report(tmp_path)
    assert missing["status"] == "missing"

    target = tmp_path / "v5_daily_ready"
    target.mkdir(parents=True)
    payload = {
        "status": "ok",
        "raw_markets": {"bets": 2, "wins": 1, "losses": 1, "pushes": 0, "win_rate": 0.5, "net_units": 0.0, "roi": 0.0},
        "fixture_clusters": {"fixtures": 2, "profitable_fixtures": 1, "losing_fixtures": 1, "flat_fixtures": 0, "profitable_fixture_rate": 0.5, "mean_markets_per_fixture": 1.0, "max_markets_on_one_fixture": 1, "net_units": 0.0},
    }
    (target / "settled_performance_audit.json").write_text(json.dumps(payload), encoding="utf-8")

    loaded = load_performance_report(tmp_path)
    assert loaded["status"] == "ok"
    assert loaded["raw_markets"]["bets"] == 2
