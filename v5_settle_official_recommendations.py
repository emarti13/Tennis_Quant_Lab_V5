from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from v5_official_performance import official_performance_report
from v5_production_artifacts import artifact_status, promote_csv_last_known_good, write_status
from v5_results_cache import load_results_cache
from v5_settlement import settle_ledger


BASE = Path(__file__).resolve().parent
OUTDIR = BASE / "v5_daily_ready"
OFFICIAL_PATH = OUTDIR / "official_recommendations.csv"
PERFORMANCE_PATH = OUTDIR / "official_performance.json"
STATUS_PATH = OUTDIR / "official_settlement_status.json"


def main() -> int:
    OUTDIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    if not OFFICIAL_PATH.exists():
        write_status(STATUS_PATH, artifact_status(
            stage="official_settlement", state="success", rows=0, fixtures=0,
            freshness="NO_RECOMMENDATIONS", error=None, run_timestamp=now.isoformat(),
        ))
        PERFORMANCE_PATH.write_text(json.dumps(official_performance_report(pd.DataFrame()), indent=2), encoding="utf-8")
        return 0
    try:
        ledger = pd.read_csv(OFFICIAL_PATH, low_memory=False)
    except pd.errors.EmptyDataError:
        ledger = pd.DataFrame()
    if ledger.empty:
        write_status(STATUS_PATH, artifact_status(
            stage="official_settlement", state="success", rows=0, fixtures=0,
            freshness="NO_RECOMMENDATIONS", error=None, run_timestamp=now.isoformat(),
        ))
        PERFORMANCE_PATH.write_text(json.dumps(official_performance_report(ledger), indent=2), encoding="utf-8")
        return 0

    results = load_results_cache()
    if results.empty:
        write_status(STATUS_PATH, artifact_status(
            stage="official_settlement",
            state="failed",
            source_version=None,
            rows=len(ledger),
            fixtures=ledger["fixture_id"].astype(str).nunique() if "fixture_id" in ledger.columns else 0,
            freshness="RESULTS_UNAVAILABLE",
            error="Canonical results cache is missing or empty; existing official ledger preserved.",
            run_timestamp=now.isoformat(),
        ))
        return 1

    settled, stats = settle_ledger(ledger, results, settled_at=now.isoformat())
    staging = OUTDIR / ".staging"
    staging.mkdir(parents=True, exist_ok=True)
    candidate = staging / "official_recommendations.csv"
    settled.to_csv(candidate, index=False)
    promote_csv_last_known_good(
        candidate, OFFICIAL_PATH,
        required_columns=["market_key", "official_signal", "result_status", "settled_result", "profit_units"],
        require_nonempty=False,
    )
    report = official_performance_report(settled)
    PERFORMANCE_PATH.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    write_status(STATUS_PATH, artifact_status(
        stage="official_settlement",
        state="success",
        source_version=now.isoformat(),
        rows=len(settled),
        fixtures=settled["fixture_id"].astype(str).nunique() if "fixture_id" in settled.columns else 0,
        freshness="READY",
        error=None,
        run_timestamp=now.isoformat(),
    ) | {"result_rows_loaded": int(len(results)), **stats})
    print(json.dumps({"official_rows": len(settled), **stats, **report}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
