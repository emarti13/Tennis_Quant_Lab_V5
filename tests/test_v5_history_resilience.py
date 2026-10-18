from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests


def test_history_status_preserves_last_success_and_enforces_max_age(tmp_path):
    from v5_history_freshness import history_status

    now = datetime(2026, 9, 11, 14, 0, tzinfo=timezone.utc)
    payload = {
        "status": "FAILED",
        "finished_utc": now.isoformat(),
        "last_successful_utc": (now - timedelta(hours=24)).isoformat(),
        "error": "upstream timeout",
    }
    path = tmp_path / "v5_refresh_last.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    status = history_status(path, now=now, max_age_hours=36)
    assert status["state"] == "DEGRADED"
    assert status["usable"] is True
    assert 23.9 <= status["age_hours"] <= 24.1
    assert status["last_successful_utc"] == payload["last_successful_utc"]

    blocked = history_status(path, now=now + timedelta(hours=13), max_age_hours=36)
    assert blocked["state"] == "STALE"
    assert blocked["usable"] is False


def test_manifest_fetch_retries_transient_failures(monkeypatch):
    import refresh_tennismylife_cloud as refresh

    calls = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"files": [{"name": "2026.csv", "url": "https://example.test/2026.csv"}]}

    def fake_get(*args, **kwargs):
        calls.append((args, kwargs))
        if len(calls) < 3:
            raise requests.exceptions.ConnectTimeout("temporary outage")
        return Response()

    monkeypatch.setattr(refresh.requests, "get", fake_get)
    monkeypatch.setattr(refresh.time, "sleep", lambda _: None)
    files = refresh.get_manifest(attempts=3, timeout_seconds=5)

    assert len(calls) == 3
    assert files[0]["name"] == "2026.csv"


def test_streamlit_interactive_path_never_builds_context_over_network():
    # The override run prices from files already in the repo (v5_pricing.PricingContext);
    # it never fetches results or rebuilds a warehouse.
    for path in ("v5_interactive_production.py", "v5_pricing.py"):
        source = Path(path).read_text(encoding="utf-8")
        for banned in ("build_context_warehouse", "refresh_tennismylife", "import requests", "urllib"):
            assert banned not in source, (path, banned)


def test_player_refresh_has_retry_windows_but_skips_when_already_fresh():
    text = Path(".github/workflows/v5_player_ratings_refresh.yml").read_text(encoding="utf-8")
    trigger = text.split("permissions:", 1)[0]
    assert trigger.count("cron:") >= 3
    assert "Check whether today's history is already fresh" in text
    assert "history_fresh=" in text
    assert "if: steps.freshness.outputs.history_fresh != 'true'" in text
    assert "Commit refresh audit even when upstream is unavailable" in text


def test_daily_predictions_restore_context_cache_and_fail_closed_when_cache_is_too_old():
    text = Path(".github/workflows/v5_daily_predictions.yml").read_text(encoding="utf-8")
    assert "Restore last-known-good context warehouse" in text
    assert "Build context warehouse with cached fallback" in text
    assert "V5_CONTEXT_MAX_AGE_HOURS" in text
    assert "context_warehouse/cache_status.json" in text
    assert "Save fresh context warehouse" in text
