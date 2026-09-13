from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


def test_results_cache_builds_from_persisted_refresh_files_and_dedupes(tmp_path):
    from v5_results_cache import build_results_cache, load_results_cache

    a = tmp_path / "2026.csv"
    b = tmp_path / "ongoing_tourneys.csv"
    rows = [
        {
            "tourney_id": "2026-001",
            "match_num": 1,
            "tourney_date": 20260910,
            "tourney_name": "Test Open",
            "winner_name": "Player A",
            "loser_name": "Player B",
            "score": "6-4 6-4",
        }
    ]
    pd.DataFrame(rows).to_csv(a, index=False)
    pd.DataFrame(rows).to_csv(b, index=False)

    out = tmp_path / "v5_results_ready" / "tennismylife_results.csv"
    status = tmp_path / "v5_results_ready" / "results_status.json"
    report = build_results_cache([a, b], out, status, source_success_utc="2026-09-12T12:00:00+00:00")

    assert report["state"] == "READY"
    assert report["rows"] == 1
    assert out.exists()
    loaded = load_results_cache(out)
    assert len(loaded) == 1
    assert loaded.iloc[0]["winner_name"] == "Player A"
    payload = json.loads(status.read_text(encoding="utf-8"))
    assert payload["source_success_utc"] == "2026-09-12T12:00:00+00:00"


def test_settlement_uses_persisted_results_cache_not_live_network():
    source = Path("v5_settlement.py").read_text(encoding="utf-8")
    assert "get_manifest()" not in source
    assert "requests.get" not in source
    assert "load_results_cache" in source


def test_official_settlement_uses_same_persisted_results_cache():
    source = Path("v5_settle_official_recommendations.py").read_text(encoding="utf-8")
    assert "load_tennismylife_results" not in source
    assert "load_results_cache" in source
