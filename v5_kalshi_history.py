"""Kalshi tennis match markets in the price store (rebuild plan Step 3, spec §2.4).

Kalshi lists one market per player ("Cameron Norrie wins"); its YES price is that player's
win probability in dollars (0.01-0.99). Trading continues after the start, so every point
is cut at the start of the matched OddsPapi fixture: the true start when OddsPapi reported
it, else the scheduled start (Kalshi's own `occurrence_datetime` when no fixture matched;
`cutoff_source` says which).

Per market, from Kalshi's 1-minute candles (best bid/ask, only minutes with activity) and
trades:
- open: first trade before the start;
- close: last trade before the start, and the best bid/ask standing at the start;
- T-24/12/6/1 h: best bid/ask standing then;
- pre-start traded contracts and trade count.
Prices are as quoted; fees are applied where edge is measured (CLAUDE.md: include fees).

Stored per start month, append-only: market_history/kalshi/markets/YYYY-MM.csv and
market_history/kalshi/price_points/YYYY-MM.csv. Raw candles and trades go to a monthly
release (decision D3), not git.
"""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pandas as pd

from v5_market_history import CHECKPOINT_HOURS, STORE_DIR, _append, _iso, _ts
from v5_player_registry import player_key

# Match-winner series in scope. ITF series exist and are out of scope (CLAUDE.md).
SERIES = {"KXATPMATCH": "ATP", "KXWTAMATCH": "WTA", "KXATPCHALLENGERMATCH": "CHALLENGER",
          "KXWTACHALLENGERMATCH": "WTA125"}
KALSHI_DIR = STORE_DIR / "kalshi"
MATCH_WINDOW_HOURS = 36

MARKET_COLUMNS = [
    "ticker", "event_ticker", "series", "family", "title", "player_name", "rules_primary",
    "occurrence_utc", "open_utc", "close_utc", "result", "volume",
    "fixture_id", "side", "match_method", "cutoff_utc", "cutoff_source", "pulled_utc",
]
POINT_COLUMNS = [
    "ticker", "fixture_id", "side",
    "open_trade_price", "open_trade_utc", "close_trade_price", "close_trade_utc",
    "close_bid", "close_ask", "close_quote_utc",
    *[c for h in CHECKPOINT_HOURS for c in (f"t{h}h_bid", f"t{h}h_ask")],
    "pre_start_contracts", "pre_start_trades", "trades_seen", "trades_truncated", "candles_seen",
]
LOG_COLUMNS = ["ticker", "close_utc", "status", "detail", "pulled_utc"]


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _fixture_name(name: str) -> str:
    return player_key(name)


def match_fixture(event_markets: list[dict], registry: pd.DataFrame) -> tuple[dict, str]:
    """Tie a Kalshi event (its two player markets) to one OddsPapi fixture.

    "names": both players' full names fold to the fixture's two participants. Unique match
    within +-36 h of Kalshi's scheduled time, or nothing (fail closed): returns
    ({ticker: (fixture_id, side)}, method)."""
    names = {m["ticker"]: _fixture_name(m.get("yes_sub_title") or "") for m in event_markets}
    when = _ts(event_markets[0].get("occurrence_datetime") or event_markets[0].get("open_time"))
    if when is None or len(set(names.values())) != len(names) or not all(names.values()):
        return {}, "unmatched"
    start = pd.to_datetime(registry["start_time_utc"], utc=True, errors="coerce")
    near = registry[(start - when).abs() <= pd.Timedelta(hours=MATCH_WINDOW_HOURS)]
    hits = []
    for r in near.itertuples():
        sides = {player_key(r.participant1_name): "p1", player_key(r.participant2_name): "p2"}
        if all(n in sides for n in names.values()):
            hits.append((r.fixture_id, sides))
    if len(hits) != 1:
        return {}, "ambiguous" if hits else "unmatched"
    fid, sides = hits[0]
    return {t: (fid, sides[n]) for t, n in names.items()}, "names"


def should_wait(market: dict, fixture: dict | None, now, wait_hours: float = 72) -> bool:
    """Wait (up to `wait_hours` after the market closed) for the matched fixture and its true
    start, so the close is cut at the real start; after that, store with what is known."""
    closed = _ts(market.get("close_time")) or _ts(now)
    young = closed > _ts(now) - pd.Timedelta(hours=wait_hours)
    return young and not (fixture and str(fixture.get("true_start_time_utc") or "").strip())


def kalshi_cutoff(market: dict, fixture: dict | None) -> tuple[pd.Timestamp, str]:
    if fixture:
        for col, src in (("true_start_time_utc", "true_start"), ("start_time_utc", "scheduled_start")):
            t = _ts(fixture.get(col))
            if t is not None:
                return t, src
    t = _ts(market.get("occurrence_datetime"))
    if t is None:
        raise ValueError(f"{market.get('ticker')} has no start time")
    return t, "kalshi_occurrence"


def _standing_quote(candles: list[dict], at: pd.Timestamp) -> tuple[float | None, float | None, str]:
    """Best bid/ask from the last 1-minute candle ending at or before `at`."""
    best = None
    for c in candles:
        end = pd.Timestamp(int(c["end_period_ts"]), unit="s", tz="UTC")
        if end > at:
            break
        best = (c, end)
    if best is None:
        return None, None, ""
    c, end = best
    bid = _num((c.get("yes_bid") or {}).get("close_dollars"))
    ask = _num((c.get("yes_ask") or {}).get("close_dollars"))
    return (bid if bid else None), (ask if ask and ask < 1 else None), _iso(end)


def market_points(market: dict, candles: list[dict], trades: list[dict], cutoff: pd.Timestamp,
                  *, fixture_id: str = "", side: str = "", truncated: bool = False) -> dict:
    candles = sorted(candles, key=lambda c: int(c["end_period_ts"]))
    pre = sorted((t for t in trades if _ts(t.get("created_time")) is not None and _ts(t["created_time"]) < cutoff),
                 key=lambda t: t["created_time"])
    out = {"ticker": market["ticker"], "fixture_id": fixture_id, "side": side,
           "trades_seen": len(trades), "trades_truncated": truncated, "candles_seen": len(candles),
           "pre_start_trades": len(pre), "pre_start_contracts": round(sum(_num(t.get("count_fp")) or 0 for t in pre), 2)}
    first, last = (pre[0], pre[-1]) if pre else (None, None)
    out["open_trade_price"] = _num(first["yes_price_dollars"]) if first else None
    out["open_trade_utc"] = _iso(_ts(first["created_time"])) if first else ""
    out["close_trade_price"] = _num(last["yes_price_dollars"]) if last else None
    out["close_trade_utc"] = _iso(_ts(last["created_time"])) if last else ""
    # A candle ending exactly at the cutoff minute may include in-play activity: use the one before.
    out["close_bid"], out["close_ask"], out["close_quote_utc"] = _standing_quote(candles, cutoff - timedelta(seconds=60))
    for h in CHECKPOINT_HOURS:
        out[f"t{h}h_bid"], out[f"t{h}h_ask"], _ = _standing_quote(candles, cutoff - timedelta(hours=h))
    return out


def market_record(market: dict, series: str, *, fixture_id: str, side: str, method: str,
                  cutoff: pd.Timestamp, cutoff_source: str, pulled_utc: str) -> dict:
    return {
        "ticker": market["ticker"], "event_ticker": market.get("event_ticker"), "series": series,
        "family": SERIES.get(series, ""), "title": market.get("title"), "player_name": market.get("yes_sub_title"),
        "rules_primary": market.get("rules_primary"), "occurrence_utc": market.get("occurrence_datetime"),
        "open_utc": market.get("open_time"), "close_utc": market.get("close_time"), "result": market.get("result"),
        "volume": market.get("volume_fp"), "fixture_id": fixture_id, "side": side, "match_method": method,
        "cutoff_utc": _iso(cutoff), "cutoff_source": cutoff_source, "pulled_utc": pulled_utc,
    }


def append_kalshi(markets: list[dict], points: list[dict], base: Path | str = ".") -> int:
    """Append-only per start month (by the cutoff): a stored market row is never replaced."""
    base = Path(base)
    mk = pd.DataFrame(markets, columns=MARKET_COLUMNS)
    if mk.empty:
        return 0
    month = mk.set_index("ticker")["cutoff_utc"].map(lambda s: f"{_ts(s):%Y-%m}")
    for m, chunk in mk.groupby(mk["ticker"].map(month)):
        _append(chunk, base / KALSHI_DIR / "markets" / f"{m}.csv", MARKET_COLUMNS, ["ticker"])
    pts = pd.DataFrame(points, columns=POINT_COLUMNS)
    added = 0
    for m, chunk in pts.groupby(pts["ticker"].map(month)):
        added += _append(chunk, base / KALSHI_DIR / "price_points" / f"{m}.csv", POINT_COLUMNS, ["ticker"])
    return added


def load_kalshi_log(base: Path | str = ".") -> pd.DataFrame:
    path = Path(base) / KALSHI_DIR / "pull_log.csv"
    return pd.read_csv(path, dtype=str, keep_default_na=False) if path.exists() else pd.DataFrame(columns=LOG_COLUMNS)


def append_kalshi_log(entries: list[dict], base: Path | str = ".") -> None:
    if not entries:
        return
    path = Path(base) / KALSHI_DIR / "pull_log.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(entries, columns=LOG_COLUMNS).to_csv(path, mode="a", header=not path.exists(), index=False)
