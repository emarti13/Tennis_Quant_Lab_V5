from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import pandas as pd
from v5_live_market import future_market_rows, market_feed_status
from v5_production_artifacts import artifact_status, promote_csv_last_known_good, write_status
from v5_recommendation_ledger import official_recommendations_switch
from v5_reprice_markets import market_reference, update_repricing_artifacts

BASE = Path(__file__).resolve().parent
MARKET_PATH = BASE / "v5_market_ready" / "market_board_input.csv"
BOOK_PRICES_PATH = BASE / "v5_market_ready" / "all_book_prices.csv"
OUTDIR = BASE / "v5_daily_ready"
MARKET_PROB_PATH = OUTDIR / "daily_market_probabilities.csv"
REPRICED_PATH = OUTDIR / "latest_repriced_board.csv"
OFFICIAL_PATH = OUTDIR / "official_recommendations.csv"
RECOMMENDATION_AUDIT_PATH = OUTDIR / "recommendation_audit.csv"
MARKET_HISTORY_PATH = OUTDIR / "market_snapshot_history.csv"
STATUS_PATH = OUTDIR / "repricing_status.json"
EASTERN = ZoneInfo("America/New_York")


def production_date(now_utc=None):
    now = pd.Timestamp(now_utc or datetime.now(timezone.utc))
    now = now.tz_localize("UTC") if now.tzinfo is None else now.tz_convert("UTC")
    return now.to_pydatetime().astimezone(EASTERN).date().isoformat()


def _read_csv(path, *, missing_ok=True):
    if not path.exists():
        if missing_ok: return pd.DataFrame()
        raise FileNotFoundError(path)
    try: return pd.read_csv(path, low_memory=False)
    except pd.errors.EmptyDataError: return pd.DataFrame()


def _append_market_history(existing, fresh, now=None):
    """Append every repriced observation permanently; dedupe only identical snapshot+market keys."""
    if fresh is None or fresh.empty: return existing.copy()
    combined = pd.concat([existing, fresh], ignore_index=True, sort=False) if not existing.empty else fresh.copy()
    keys = [c for c in ["snapshot_utc", "market_key"] if c in combined.columns]
    if keys: combined = combined.drop_duplicates(keys, keep="last")
    return combined.reset_index(drop=True)


def main():
    OUTDIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    raw = _read_csv(MARKET_PATH)
    feed = market_feed_status(raw, now_utc=now)
    if feed["state"] != "ready":
        write_status(STATUS_PATH, artifact_status(stage="repricing", state="blocked", source_version=feed.get("snapshot_utc"), rows=0, fixtures=feed.get("future_fixture_count", 0), freshness=str(feed["state"]).upper(), error="fresh sportsbook prices are required for repricing", run_timestamp=now.isoformat()))
        return 0
    frozen = _read_csv(MARKET_PROB_PATH)
    if frozen.empty:
        write_status(STATUS_PATH, artifact_status(stage="repricing", state="blocked", source_version=feed.get("snapshot_utc"), rows=0, fixtures=feed.get("future_fixture_count", 0), freshness="MISSING_FORECAST", error="daily market probability artifact is missing/empty", run_timestamp=now.isoformat()))
        return 0
    expected_date = production_date(now)
    forecast_dates = set(frozen.get("forecast_date", pd.Series(dtype=object)).dropna().astype(str))
    if expected_date not in forecast_dates:
        write_status(STATUS_PATH, artifact_status(stage="repricing", state="blocked", source_version=feed.get("snapshot_utc"), rows=0, fixtures=feed.get("future_fixture_count", 0), freshness="STALE_FORECAST", error=f"no frozen model forecast for production date {expected_date}", run_timestamp=now.isoformat()) | {"available_forecast_dates": sorted(forecast_dates)})
        return 0
    frozen = frozen[frozen["forecast_date"].astype(str).eq(expected_date)].copy()
    prices = future_market_rows(raw, now_utc=now)
    switch = official_recommendations_switch(BASE / "production_switches.json")
    repriced, official, audit = update_repricing_artifacts(prices, frozen, prices_fresh=True, existing_official=_read_csv(OFFICIAL_PATH), existing_audit=_read_csv(RECOMMENDATION_AUDIT_PATH), official_enabled=switch["enabled"],
        reference=market_reference(future_market_rows(_read_csv(BOOK_PRICES_PATH), now_utc=now)))
    staging = OUTDIR / ".staging"; staging.mkdir(parents=True, exist_ok=True)
    candidates = {
        REPRICED_PATH: (staging / "latest_repriced_board.csv", repriced, ["fixture_id", "market_key", "model_probability", "signal", "snapshot_utc"], True),
        OFFICIAL_PATH: (staging / "official_recommendations.csv", official, ["market_key", "official_signal", "result_status"], False),
        RECOMMENDATION_AUDIT_PATH: (staging / "recommendation_audit.csv", audit if not audit.empty else pd.DataFrame(columns=["market_key", "event"]), ["market_key", "event"], False),
    }
    history = _append_market_history(_read_csv(MARKET_HISTORY_PATH), repriced, now)
    candidates[MARKET_HISTORY_PATH] = (staging / "market_snapshot_history.csv", history, ["snapshot_utc", "market_key"], True)
    for target, (candidate, frame, required, nonempty) in candidates.items():
        frame.to_csv(candidate, index=False)
        promote_csv_last_known_good(candidate, target, required_columns=required, require_nonempty=nonempty)
    actionable = int(repriced["signal"].isin(["BET", "LEAN"]).sum()) if "signal" in repriced.columns else 0
    gap_flags = int((repriced.get("guard_reason", pd.Series(dtype=object)) == "MODEL_MARKET_GAP").sum())
    matched = int(pd.to_numeric(repriced["model_probability"], errors="coerce").notna().sum())
    write_status(STATUS_PATH, artifact_status(stage="repricing", state="success", source_version=feed.get("snapshot_utc"), rows=len(repriced), fixtures=repriced["fixture_id"].astype(str).nunique() if "fixture_id" in repriced.columns else 0, freshness="READY", error=None, run_timestamp=now.isoformat()) | {"forecast_date": expected_date, "matched_model_rows": matched, "actionable_rows": actionable, "model_market_gap_flags": gap_flags, "official_recommendations": int(len(official)), "market_history_retention": "permanent",
        "official_recommendations_state": "active" if switch["enabled"] else "paused",
        "official_recommendations_paused_since": None if switch["enabled"] else switch["since"],
        "official_recommendations_reason": None if switch["enabled"] else switch["reason"]})
    print(f"repriced={len(repriced)} matched={matched} actionable={actionable} official={len(official)}")
    return 0


if __name__ == "__main__": raise SystemExit(main())
