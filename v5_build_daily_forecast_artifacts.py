from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from v5_daily_forecast import forecast_rows_from_board, market_probability_rows_from_board
from v5_production_artifacts import artifact_status, promote_csv_last_known_good, write_status


BASE = Path(__file__).resolve().parent
OUTDIR = BASE / "v5_daily_ready"
BOARD_PATH = OUTDIR / "latest_board.csv"
FORECAST_PATH = OUTDIR / "daily_forecasts.csv"
MARKET_PROB_PATH = OUTDIR / "daily_market_probabilities.csv"
STATUS_PATH = OUTDIR / "forecast_status.json"
EASTERN = ZoneInfo("America/New_York")


def production_date(now_utc=None) -> str:
    now = pd.Timestamp(now_utc or datetime.now(timezone.utc))
    if now.tzinfo is None:
        now = now.tz_localize("UTC")
    else:
        now = now.tz_convert("UTC")
    return now.to_pydatetime().astimezone(EASTERN).date().isoformat()


def build_forecast_artifacts(board: pd.DataFrame, *, now_utc=None):
    forecast_date = production_date(now_utc)
    forecasts = forecast_rows_from_board(board, forecast_date=forecast_date)
    market_probs = market_probability_rows_from_board(board, forecast_date=forecast_date)
    return forecasts, market_probs


def main() -> int:
    OUTDIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    if not BOARD_PATH.exists():
        write_status(STATUS_PATH, artifact_status(
            stage="daily_forecast", state="failed", rows=0, fixtures=0,
            freshness="MISSING", error=f"missing source board: {BOARD_PATH}",
            run_timestamp=now.isoformat(),
        ))
        return 2
    try:
        board = pd.read_csv(BOARD_PATH, low_memory=False)
    except pd.errors.EmptyDataError:
        board = pd.DataFrame()
    if board.empty:
        write_status(STATUS_PATH, artifact_status(
            stage="daily_forecast", state="failed", rows=0, fixtures=0,
            freshness="NO_FUTURE_FIXTURES", error="source board is empty",
            run_timestamp=now.isoformat(),
        ))
        return 2

    forecasts, market_probs = build_forecast_artifacts(board, now_utc=now)
    staging = OUTDIR / ".staging"
    staging.mkdir(parents=True, exist_ok=True)
    forecast_candidate = staging / "daily_forecasts.csv"
    prob_candidate = staging / "daily_market_probabilities.csv"
    forecasts.to_csv(forecast_candidate, index=False)
    market_probs.to_csv(prob_candidate, index=False)

    promote_csv_last_known_good(
        forecast_candidate, FORECAST_PATH,
        required_columns=["fixture_id", "forecast_date", "model_version", "full_context_probability_p1"],
        require_nonempty=True,
    )
    promote_csv_last_known_good(
        prob_candidate, MARKET_PROB_PATH,
        required_columns=["fixture_id", "forecast_date", "market_key", "model_probability"],
        require_nonempty=True,
    )
    source_version = None
    if "frozen_at_utc" in board.columns and not board["frozen_at_utc"].dropna().empty:
        source_version = str(board["frozen_at_utc"].dropna().iloc[0])
    write_status(STATUS_PATH, artifact_status(
        stage="daily_forecast",
        state="success",
        source_version=source_version,
        rows=len(forecasts),
        fixtures=forecasts["fixture_id"].astype(str).nunique(),
        freshness="READY",
        error=None,
        run_timestamp=now.isoformat(),
    ) | {"forecast_date": production_date(now)})
    print(f"daily forecasts: {len(forecasts)} fixtures; frozen market probabilities: {len(market_probs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
