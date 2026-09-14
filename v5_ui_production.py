from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from v5_interactive_production import production_board_to_today
from v5_live_market import market_feed_status


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, low_memory=False)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def _present(value) -> bool:
    if value is None:
        return False
    try:
        if pd.isna(value):
            return False
    except (TypeError, ValueError):
        pass
    return not (isinstance(value, str) and not value.strip())


def _official_market_text(row: pd.Series) -> str:
    group = str(row.get("market_group") or "").lower().strip()
    selection = str(row.get("selection") or "").strip()
    line = pd.to_numeric(pd.Series([row.get("line")]), errors="coerce").iloc[0]
    if group == "moneyline":
        return f"{selection} ML".strip()
    if group == "game_spread":
        if pd.notna(line):
            return f"{selection} {float(line):+g}".strip()
        return f"{selection} spread".strip()
    if group == "total_games":
        label = selection.title() if selection else "Total"
        if pd.notna(line):
            return f"{label} {float(line):g}".strip()
        return label
    return selection or "Official recommendation"


def _overlay_official_recommendations(today: pd.DataFrame, official: pd.DataFrame) -> pd.DataFrame:
    if today is None or today.empty or official is None or official.empty:
        return today.copy() if today is not None else pd.DataFrame()
    if "Fixture ID" not in today.columns or "fixture_id" not in official.columns:
        return today.copy()

    work = official.copy()
    status = work.get("result_status", pd.Series(index=work.index, dtype=object)).fillna("OPEN").astype(str).str.upper().str.strip()
    signal_source = work["official_signal"] if "official_signal" in work.columns else work.get("signal", pd.Series(index=work.index, dtype=object))
    signal = signal_source.fillna("").astype(str).str.upper().str.strip()
    work = work.loc[status.eq("OPEN") & signal.isin({"BET", "LEAN"})].copy()
    if work.empty:
        return today.copy()

    if "official_at_utc" in work.columns:
        work["_official_at"] = pd.to_datetime(work["official_at_utc"], errors="coerce", utc=True)
        work = work.sort_values(["fixture_id", "_official_at"], kind="stable", na_position="last")

    out = today.copy()
    index = {str(value): idx for idx, value in out["Fixture ID"].items() if _present(value)}
    for _, official_row in work.iterrows():
        fixture_id = str(official_row.get("fixture_id") or "")
        if fixture_id not in index:
            continue
        idx = index[fixture_id]
        out.at[idx, "Official Locked"] = True
        out.at[idx, "Official Market"] = _official_market_text(official_row)
        out.at[idx, "Official Signal"] = str(official_row.get("official_signal") or official_row.get("signal") or "").upper().strip()
        out.at[idx, "Official Price"] = official_row.get("official_price_american") if _present(official_row.get("official_price_american")) else official_row.get("best_american_odds")
        out.at[idx, "Official Edge"] = official_row.get("official_expected_value") if _present(official_row.get("official_expected_value")) else official_row.get("expected_value")
        out.at[idx, "Official Market Key"] = official_row.get("market_key")
        out.at[idx, "Official At"] = official_row.get("official_at_utc")
    return out


def production_ui_state(status: dict | None) -> str:
    status = status or {}
    freshness = str(status.get("freshness") or "").upper().strip()
    if freshness in {"READY", "STALE_PRICES", "NO_FUTURE_FIXTURES", "MISSING", "STALE_FORECAST", "MISSING_FORECAST"}:
        return freshness
    return "MISSING"


def runtime_production_state(market_source: pd.DataFrame | None, repricing_status: dict | None, *, now_utc=None) -> dict:
    """Single live-health contract shared by Daily Board and Decision Feed."""
    feed = market_feed_status(market_source, now_utc=now_utc)
    if feed.get("state") == "missing":
        state = "MISSING"
    elif not feed.get("fresh"):
        state = "STALE_PRICES"
    elif feed.get("state") == "no_future_fixtures":
        state = "NO_FUTURE_FIXTURES"
    else:
        state = production_ui_state(repricing_status)
    return {
        "state": state,
        "feed_status": feed,
        "repricing_status": repricing_status or {},
    }


def load_repricing_status(base_dir: str | Path) -> dict:
    base = Path(base_dir)
    return _read_json(base / "v5_daily_ready" / "repricing_status.json")


def load_canonical_repriced_board(base_dir: str | Path) -> pd.DataFrame:
    return _read_csv(Path(base_dir) / "v5_daily_ready" / "latest_repriced_board.csv")


def load_canonical_today_board(base_dir: str | Path) -> pd.DataFrame:
    base = Path(base_dir)
    production = load_canonical_repriced_board(base)
    today = production_board_to_today(production)
    official = _read_csv(base / "v5_daily_ready" / "official_recommendations.csv")
    return _overlay_official_recommendations(today, official)
