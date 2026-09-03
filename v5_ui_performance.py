from __future__ import annotations

import json
from pathlib import Path
from typing import Any


PERFORMANCE_PATH = Path("v5_daily_ready") / "settled_performance_audit.json"


def load_performance_report(base_dir: str | Path = ".") -> dict[str, Any]:
    path = Path(base_dir) / PERFORMANCE_PATH
    if not path.exists():
        return {"status": "missing", "source": str(path)}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "invalid", "source": str(path), "error": str(exc)}
    if not isinstance(payload, dict):
        return {"status": "invalid", "source": str(path), "error": "report must be a JSON object"}
    payload.setdefault("status", "ok")
    payload.setdefault("source", str(path))
    return payload


def headline_metrics(report: dict[str, Any] | None) -> dict[str, Any]:
    report = report or {}
    raw = report.get("raw_markets") or {}
    fixtures = report.get("fixture_clusters") or {}

    wins = int(raw.get("wins") or 0)
    losses = int(raw.get("losses") or 0)
    pushes = int(raw.get("pushes") or 0)
    fixture_count = int(fixtures.get("fixtures") or 0)
    profitable = int(fixtures.get("profitable_fixtures") or 0)

    return {
        "market_label": "Market results",
        "fixture_label": "Independent fixtures",
        "market_record": f"{wins}-{losses}-{pushes}",
        "market_win_rate": raw.get("win_rate"),
        "market_roi": raw.get("roi"),
        "market_net_units": raw.get("net_units"),
        "fixture_record": f"{profitable} profitable / {fixture_count}",
        "fixture_profitable_rate": fixtures.get("profitable_fixture_rate"),
        "fixture_net_units": fixtures.get("net_units"),
        "mean_markets_per_fixture": fixtures.get("mean_markets_per_fixture"),
        "max_correlated_markets": int(fixtures.get("max_markets_on_one_fixture") or 0),
    }
