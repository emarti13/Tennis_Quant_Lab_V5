"""Live pre-match prices and the start-time-aware freshness rule (rebuild plan Step 3).

Spec docs/superpowers/specs/2026-10-16-market-data-layer-design.md §2.3 and §5.3 (approved
2026-10-16): OddsPapi /historical-odds also answers for matches that have not started, with
every price change up to now, and does not count against the request quota. Inside the
existing live run (no new schedule, no polling), the day's upcoming fixtures are fetched
for Pinnacle, Bet365 and BetRivers and the price standing at the fetch time is stored in
market_history/live/YYYY-MM.csv (append-only). It is computed by the same code as the
closing price (`v5_market_history.price_points` with the fetch time as cutoff).

`is_actionable` is the one rule for whether a live price may be acted on:
- the match has not started: before the scheduled start, and no true start reported;
- the snapshot is fresh: fetched at most `max_age_minutes` ago. OddsPapi records changes
  only, so the age of the quote's own change time says nothing about staleness; the fetch
  time does;
- the book was still offering the price when fetched (not withdrawn);
- every timestamp is present (fail closed).
Started fixtures leave the live board. The old engine keeps its own rules until Step 4
switches it to this one.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from v5_market_history import STORE_DIR, _append, _iso, _ts, price_points

LIVE_DIR = STORE_DIR / "live"
DEFAULT_MAX_AGE_MINUTES = 60
LIVE_COLUMNS = ["fetched_utc", "fixture_id", "start_time_utc", "bookmaker", "market_group", "market_id",
                "outcome_id", "player_key", "side", "line", "price", "quote_utc", "withdrawn", "minutes_to_start"]
LIVE_KEY = ["fetched_utc", "fixture_id", "bookmaker", "market_id", "outcome_id", "player_key"]


def has_started(fixture: dict, now) -> bool:
    """Started if a true start is reported at or before `now`, or the scheduled start has passed.
    No start time at all counts as started (fail closed)."""
    now = _ts(now)
    true_start, scheduled = _ts(fixture.get("true_start_time_utc")), _ts(fixture.get("start_time_utc"))
    if true_start is not None and true_start <= now:
        return True
    return scheduled is None or scheduled <= now


def live_quotes(payload: dict, fixture: dict, market_meta: list[dict], fetched) -> pd.DataFrame:
    """The price standing at `fetched` per book and selection, for a fixture not yet started."""
    fetched = _ts(fetched)
    if has_started(fixture, fetched):
        return pd.DataFrame(columns=LIVE_COLUMNS)
    pts = price_points(payload, fixture, market_meta, cutoff=fetched)
    if pts.empty:
        return pd.DataFrame(columns=LIVE_COLUMNS)
    start = _ts(fixture.get("start_time_utc"))
    out = pd.DataFrame({
        "fetched_utc": _iso(fetched), "fixture_id": pts["fixture_id"], "start_time_utc": _iso(start),
        "bookmaker": pts["bookmaker"], "market_group": pts["market_group"], "market_id": pts["market_id"],
        "outcome_id": pts["outcome_id"], "player_key": pts["player_key"], "side": pts["side"], "line": pts["line"],
        "price": pts["close_price"], "quote_utc": pts["close_utc"],
        # A gap means the book withdrew the price before the fetch: it is not on offer.
        "withdrawn": pd.to_numeric(pts["close_gap_min"], errors="coerce").fillna(float("inf")) > 0,
        "minutes_to_start": round((start - fetched).total_seconds() / 60, 1),
    })
    return out[out["price"].notna()][LIVE_COLUMNS]


def is_actionable(quote: dict, fixture: dict, now, max_age_minutes: float = DEFAULT_MAX_AGE_MINUTES) -> tuple[bool, str]:
    """(actionable, reason): reason is "OK", MISSING_TIMESTAMP, STARTED, STALE_SNAPSHOT, WITHDRAWN or NO_PRICE."""
    now, fetched = _ts(now), _ts(quote.get("fetched_utc"))
    if now is None or fetched is None or _ts(fixture.get("start_time_utc")) is None:
        return False, "MISSING_TIMESTAMP"
    if has_started(fixture, now):
        return False, "STARTED"
    if fetched > now or (now - fetched).total_seconds() / 60 > max_age_minutes:
        return False, "STALE_SNAPSHOT"
    if str(quote.get("withdrawn")).lower() in ("true", "1"):
        return False, "WITHDRAWN"
    try:
        price = float(quote.get("price"))
    except (TypeError, ValueError):
        return False, "NO_PRICE"
    if not price > 1.0:
        return False, "NO_PRICE"
    return True, "OK"


def append_live(quotes: pd.DataFrame, base: Path | str = ".") -> int:
    """Append-only per month of the fetch."""
    if quotes.empty:
        return 0
    added = 0
    for month, chunk in quotes.groupby(quotes["fetched_utc"].str[:7]):
        added += _append(chunk, Path(base) / LIVE_DIR / f"{month}.csv", LIVE_COLUMNS, LIVE_KEY)
    return added
