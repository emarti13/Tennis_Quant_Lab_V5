from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from v5_interactive_production import production_board_to_today


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def production_ui_state(status: dict | None) -> str:
    status = status or {}
    freshness = str(status.get("freshness") or "").upper().strip()
    if freshness in {"READY", "STALE_PRICES", "NO_FUTURE_FIXTURES", "MISSING", "STALE_FORECAST", "MISSING_FORECAST"}:
        return freshness
    return "MISSING"


def load_repricing_status(base_dir: str | Path) -> dict:
    base = Path(base_dir)
    return _read_json(base / "v5_daily_ready" / "repricing_status.json")


def load_canonical_repriced_board(base_dir: str | Path) -> pd.DataFrame:
    path = Path(base_dir) / "v5_daily_ready" / "latest_repriced_board.csv"
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, low_memory=False)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def load_canonical_today_board(base_dir: str | Path) -> pd.DataFrame:
    production = load_canonical_repriced_board(base_dir)
    return production_board_to_today(production)
