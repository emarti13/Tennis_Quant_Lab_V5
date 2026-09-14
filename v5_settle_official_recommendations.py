from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from v5_official_performance import official_performance_report
from v5_production_artifacts import artifact_status, promote_csv_last_known_good, write_status
from v5_results_cache import load_results_cache
from v5_results_reset import filter_since_reset, load_reset_timestamp
from v5_settlement import settle_ledger


BASE = Path(__file__).resolve().parent
OUTDIR = BASE / "v5_daily_ready"
OFFICIAL_PATH = OUTDIR / "official_recommendations.csv"
FROZEN_PATH = OUTDIR / "frozen_predictions.csv"
PERFORMANCE_PATH = OUTDIR / "official_performance.json"
STATUS_PATH = OUTDIR / "official_settlement_status.json"


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, low_memory=False)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def _promote_settled(frame: pd.DataFrame, destination: Path, filename: str, required_columns: list[str]) -> None:
    staging = OUTDIR / ".staging"
    staging.mkdir(parents=True, exist_ok=True)
    candidate = staging / filename
    frame.to_csv(candidate, index=False)
    promote_csv_last_known_good(
        candidate,
        destination,
        required_columns=required_columns,
        require_nonempty=False,
    )


def main() -> int:
    OUTDIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    reset_at = load_reset_timestamp()
    official = _read_csv(OFFICIAL_PATH)
    frozen = _read_csv(FROZEN_PATH)

    if official.empty and frozen.empty:
        write_status(STATUS_PATH, artifact_status(
            stage="official_settlement", state="success", rows=0, fixtures=0,
            freshness="NO_RECOMMENDATIONS_OR_FORECASTS", error=None, run_timestamp=now.isoformat(),
        ) | {
            "official_settled": 0,
            "official_open": 0,
            "official_ambiguous_or_missing": 0,
            "forecast_settled": 0,
            "forecast_open": 0,
            "forecast_ambiguous_or_missing": 0,
            "results_reset_at_utc": None if reset_at is None else reset_at.isoformat(),
        })
        report = official_performance_report(pd.DataFrame())
        report["reset_at_utc"] = None if reset_at is None else reset_at.isoformat()
        PERFORMANCE_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
        return 0

    results = load_results_cache()
    if results.empty:
        write_status(STATUS_PATH, artifact_status(
            stage="official_settlement",
            state="failed",
            source_version=None,
            rows=len(official),
            fixtures=official["fixture_id"].astype(str).nunique() if "fixture_id" in official.columns else 0,
            freshness="RESULTS_UNAVAILABLE",
            error="Canonical results cache is missing or empty; existing official and frozen forecast ledgers preserved.",
            run_timestamp=now.isoformat(),
        ) | {"results_reset_at_utc": None if reset_at is None else reset_at.isoformat()})
        return 1

    if official.empty:
        settled_official = official.copy()
        official_stats = {"settled": 0, "open": 0, "ambiguous_or_missing": 0}
    else:
        settled_official, official_stats = settle_ledger(official, results, settled_at=now.isoformat())
        _promote_settled(
            settled_official,
            OFFICIAL_PATH,
            "official_recommendations.csv",
            ["market_key", "official_signal", "result_status", "settled_result", "profit_units"],
        )

    if frozen.empty:
        settled_frozen = frozen.copy()
        forecast_stats = {"settled": 0, "open": 0, "ambiguous_or_missing": 0}
    else:
        settled_frozen, forecast_stats = settle_ledger(frozen, results, settled_at=now.isoformat())
        _promote_settled(
            settled_frozen,
            FROZEN_PATH,
            "frozen_predictions.csv",
            ["fixture_id", "market_key", "result_status", "settled_result", "winner_games", "loser_games"],
        )

    performance_frame = filter_since_reset(
        settled_official,
        reset_at,
        timestamp_columns=("official_at_utc", "snapshot_utc", "start_time_utc"),
    )
    report = official_performance_report(performance_frame)
    report["reset_at_utc"] = None if reset_at is None else reset_at.isoformat()
    report["pre_reset_rows_excluded"] = int(max(0, len(settled_official) - len(performance_frame)))
    PERFORMANCE_PATH.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")

    status_payload = artifact_status(
        stage="official_settlement",
        state="success",
        source_version=now.isoformat(),
        rows=len(settled_official),
        fixtures=settled_official["fixture_id"].astype(str).nunique() if "fixture_id" in settled_official.columns else 0,
        freshness="READY",
        error=None,
        run_timestamp=now.isoformat(),
    ) | {
        "result_rows_loaded": int(len(results)),
        "official_settled": int(official_stats["settled"]),
        "official_open": int(official_stats["open"]),
        "official_ambiguous_or_missing": int(official_stats["ambiguous_or_missing"]),
        "forecast_rows": int(len(settled_frozen)),
        "forecast_fixtures": int(settled_frozen["fixture_id"].astype(str).nunique()) if "fixture_id" in settled_frozen.columns else 0,
        "forecast_settled": int(forecast_stats["settled"]),
        "forecast_open": int(forecast_stats["open"]),
        "forecast_ambiguous_or_missing": int(forecast_stats["ambiguous_or_missing"]),
        "results_reset_at_utc": None if reset_at is None else reset_at.isoformat(),
        "performance_rows_since_reset": int(len(performance_frame)),
    }
    write_status(STATUS_PATH, status_payload)
    print(json.dumps({**status_payload, "official_performance": report}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
