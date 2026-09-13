from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from v5_live_market import future_market_rows, market_feed_status
from v5_production_artifacts import artifact_status, promote_csv_last_known_good, write_status
from v5_reprice_markets import update_repricing_artifacts


BASE = Path(__file__).resolve().parent
MARKET_PATH = BASE / "v5_market_ready" / "market_board_input.csv"
OUTDIR = BASE / "v5_daily_ready"
MARKET_PROB_PATH = OUTDIR / "daily_market_probabilities.csv"
REPRICED_PATH = OUTDIR / "latest_repriced_board.csv"
OFFICIAL_PATH = OUTDIR / "official_recommendations.csv"
RECOMMENDATION_AUDIT_PATH = OUTDIR / "recommendation_audit.csv"
MARKET_HISTORY_PATH = OUTDIR / "market_snapshot_history.csv"
STATUS_PATH = OUTDIR / "repricing_status.json"
HISTORY_DAYS = 14
EASTERN = ZoneInfo("America/New_York")


def production_date(now_utc=None) -> str:
    now = pd.Timestamp(now_utc or datetime.now(timezone.utc))
    if now.tzinfo is None:
        now = now.tz_localize("UTC")
    else:
        now = now.tz_convert("UTC")
    return now.to_pydatetime().astimezone(EASTERN).date().isoformat()


def _read_csv(path: Path, *, missing_ok=True) -> pd.DataFrame:
    if not path.exists():
        if missing_ok:
            return pd.DataFrame()
        raise FileNotFoundError(path)
    try:
        return pd.read_csv(path, low_memory=False)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def _append_market_history(existing: pd.DataFrame, fresh: pd.DataFrame, now) -> pd.DataFrame:
    if fresh is None or fresh.empty:
        return existing.copy()
    combined = pd.concat([existing, fresh], ignore_index=True, sort=False) if not existing.empty else fresh.copy()
    keys = [c for c in ["snapshot_utc", "market_key"] if c in combined.columns]
    if keys:
        combined = combined.drop_duplicates(keys, keep="last")
    if "snapshot_utc" in combined.columns:
        ts = pd.to_datetime(combined["snapshot_utc"], errors="coerce", utc=True)
        cutoff = pd.Timestamp(now)
        if cutoff.tzinfo is None:
            cutoff = cutoff.tz_localize("UTC")
        else:
            cutoff = cutoff.tz_convert("UTC")
        cutoff = cutoff - pd.Timedelta(days=HISTORY_DAYS)
        combined = combined.loc[ts.isna() | (ts >= cutoff)].copy()
    return combined.reset_index(drop=True)


def main() -> int:
    OUTDIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    raw = _read_csv(MARKET_PATH)
    feed = market_feed_status(raw, now_utc=now)
    if feed["state"] != "ready":
        write_status(STATUS_PATH, artifact_status(
            stage="repricing",
            state="blocked",
            source_version=feed.get("snapshot_utc"),
            rows=0,
            fixtures=feed.get("future_fixture_count", 0),
            freshness=str(feed["state"]).upper(),
            error="fresh sportsbook prices are required for repricing",
            run_timestamp=now.isoformat(),
        ))
        return 0

    frozen = _read_csv(MARKET_PROB_PATH)
    if frozen.empty:
        write_status(STATUS_PATH, artifact_status(
            stage="repricing", state="blocked", source_version=feed.get("snapshot_utc"),
            rows=0, fixtures=feed.get("future_fixture_count", 0), freshness="MISSING_FORECAST",
            error="daily market probability artifact is missing/empty", run_timestamp=now.isoformat(),
        ))
        return 0

    expected_date = production_date(now)
    forecast_dates = set(frozen.get("forecast_date", pd.Series(dtype=object)).dropna().astype(str))
    if expected_date not in forecast_dates:
        write_status(STATUS_PATH, artifact_status(
            stage="repricing", state="blocked", source_version=feed.get("snapshot_utc"),
            rows=0, fixtures=feed.get("future_fixture_count", 0), freshness="STALE_FORECAST",
            error=f"no frozen model forecast for production date {expected_date}", run_timestamp=now.isoformat(),
        ) | {"available_forecast_dates": sorted(forecast_dates)})
        return 0
    frozen = frozen[frozen["forecast_date"].astype(str).eq(expected_date)].copy()

    prices = future_market_rows(raw, now_utc=now)
    official_existing = _read_csv(OFFICIAL_PATH)
    audit_existing = _read_csv(RECOMMENDATION_AUDIT_PATH)
    repriced, official, audit = update_repricing_artifacts(
        prices,
        frozen,
        prices_fresh=True,
        existing_official=official_existing,
        existing_audit=audit_existing,
    )

    staging = OUTDIR / ".staging"
    staging.mkdir(parents=True, exist_ok=True)
    repriced_candidate = staging / "latest_repriced_board.csv"
    official_candidate = staging / "official_recommendations.csv"
    audit_candidate = staging / "recommendation_audit.csv"
    history_candidate = staging / "market_snapshot_history.csv"
    repriced.to_csv(repriced_candidate, index=False)
    official.to_csv(official_candidate, index=False)
    if audit.empty:
        audit = pd.DataFrame(columns=["market_key", "event"])
    audit.to_csv(audit_candidate, index=False)

    history_existing = _read_csv(MARKET_HISTORY_PATH)
    history = _append_market_history(history_existing, repriced, now)
    history.to_csv(history_candidate, index=False)

    promote_csv_last_known_good(
        repriced_candidate, REPRICED_PATH,
        required_columns=["fixture_id", "market_key", "model_probability", "signal", "snapshot_utc"],
        require_nonempty=True,
    )
    promote_csv_last_known_good(
        official_candidate, OFFICIAL_PATH,
        required_columns=["market_key", "official_signal", "result_status"],
        require_nonempty=False,
    )
    promote_csv_last_known_good(
        audit_candidate, RECOMMENDATION_AUDIT_PATH,
        required_columns=["market_key", "event"],
        require_nonempty=False,
    )
    promote_csv_last_known_good(
        history_candidate, MARKET_HISTORY_PATH,
        required_columns=["snapshot_utc", "market_key"],
        require_nonempty=True,
    )

    actionable = int(repriced["signal"].isin(["BET", "LEAN"]).sum()) if "signal" in repriced.columns else 0
    matched = int(pd.to_numeric(repriced["model_probability"], errors="coerce").notna().sum())
    write_status(STATUS_PATH, artifact_status(
        stage="repricing",
        state="success",
        source_version=feed.get("snapshot_utc"),
        rows=len(repriced),
        fixtures=repriced["fixture_id"].astype(str).nunique() if "fixture_id" in repriced.columns else 0,
        freshness="READY",
        error=None,
        run_timestamp=now.isoformat(),
    ) | {"forecast_date": expected_date, "matched_model_rows": matched, "actionable_rows": actionable, "official_recommendations": int(len(official))})
    print(f"repriced={len(repriced)} matched={matched} actionable={actionable} official={len(official)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
