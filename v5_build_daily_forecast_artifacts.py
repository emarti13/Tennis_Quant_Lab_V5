from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from v5_daily_batch import _load_full_context_assets, _load_ratings, _load_summary
from v5_daily_forecast import forecast_rows_from_board, market_probability_rows_from_board
from v5_forecast_context import enrich_daily_board_context
from v5_production_artifacts import artifact_status, promote_csv_last_known_good, write_status


BASE = Path(__file__).resolve().parent
OUTDIR = BASE / "v5_daily_ready"
BOARD_PATH = OUTDIR / "latest_board.csv"
MARKET_PATH = BASE / "v5_market_ready" / "market_board_input.csv"
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


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, low_memory=False)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def main() -> int:
    OUTDIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    board = _read_csv(BOARD_PATH)
    if board.empty:
        write_status(STATUS_PATH, artifact_status(
            stage="daily_forecast", state="failed", rows=0, fixtures=0,
            freshness="MISSING" if not BOARD_PATH.exists() else "NO_FUTURE_FIXTURES",
            error=f"missing/empty source board: {BOARD_PATH}", run_timestamp=now.isoformat(),
        ))
        return 2

    market_feed = _read_csv(MARKET_PATH)
    context_errors: list[dict] = []
    if not market_feed.empty:
        try:
            summary = _load_summary()
            ratings = _load_ratings()
            context_history, tournament_registry, weather_cache, _, _ = _load_full_context_assets()
            board, context_errors = enrich_daily_board_context(
                board,
                market_feed,
                ratings,
                summary,
                context_history,
                tournament_registry=tournament_registry,
                weather_cache=weather_cache,
            )
        except Exception as exc:
            context_errors = [{"fixture_id": "ALL", "stage": "forecast_context", "error": f"{type(exc).__name__}:{exc}"}]

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
    state = "success" if not context_errors else "partial"
    write_status(STATUS_PATH, artifact_status(
        stage="daily_forecast",
        state=state,
        source_version=source_version,
        rows=len(forecasts),
        fixtures=forecasts["fixture_id"].astype(str).nunique(),
        freshness="READY",
        error=None if not context_errors else f"{len(context_errors)} context display enrichment issue(s)",
        run_timestamp=now.isoformat(),
    ) | {"forecast_date": production_date(now), "context_errors": context_errors})
    print(f"daily forecasts: {len(forecasts)} fixtures; frozen market probabilities: {len(market_probs)}; context_errors={len(context_errors)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
