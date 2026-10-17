"""Store Kalshi tennis match markets after they settle (v5_kalshi_history; spec §2.4).

Usage:  python scripts/pull_kalshi_history.py [--max-minutes 6] [--since 2026-01-01]

Kalshi's public market-data API needs no account. Each run lists settled markets of the
four match-winner series: first those that closed in the last 3 days, then older ones,
oldest first, with the time left. Per market it fetches the 1-minute candles over the
market's life and the trades before the start (the in-play trades are not needed for a
pre-match benchmark), ties the event to an OddsPapi fixture by both players' names, and
stores the points. A market whose fixture or true start is not known yet waits up to 3
days (the OddsPapi step in the same workflow discovers them first). Raw candles and trades go to market_history/kalshi/raw/ (not committed;
the workflow uploads them to the monthly release).
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
os.chdir(BASE)
from v5_kalshi_history import (  # noqa: E402
    KALSHI_DIR, SERIES, append_kalshi, append_kalshi_log, kalshi_cutoff, load_kalshi_log, market_points,
    market_record, match_fixture, rebuild_fixture_map, should_wait,
)
from v5_market_history import _ts  # noqa: E402

API = "https://api.elections.kalshi.com/trade-api/v2"
REGISTRY = BASE / "oddspapi_registry" / "fixtures.csv"
DAILY_DAYS = 3
MAX_TRADE_PAGES = 30          # 30,000 pre-start trades per market; more is flagged as truncated
CANDLE_SPAN = timedelta(days=3)
PAUSE = 0.12                  # well under the public 20 requests/second


def load_stored_markets(base: Path) -> pd.DataFrame:
    paths = sorted((base / KALSHI_DIR / "markets").glob("*.csv"))
    return pd.concat([pd.read_csv(p, dtype=str, keep_default_na=False) for p in paths]) if paths else pd.DataFrame(
        columns=["ticker", "event_ticker", "player_name", "occurrence_utc", "open_utc"])


class Kalshi:
    def __init__(self):
        self.session = requests.Session()
        self.calls = 0

    def get(self, path: str, **params):
        for attempt in range(4):
            self.calls += 1
            r = self.session.get(f"{API}{path}", params=params, timeout=60)
            time.sleep(PAUSE)
            if r.status_code == 429:
                time.sleep(2 ** attempt)
                continue
            try:
                return r.status_code, r.json()
            except ValueError:
                return r.status_code, {"text": r.text[:300]}
        return r.status_code, {}

    def settled(self, series: str, min_ts: int, max_ts: int) -> list[dict]:
        out, cursor = [], None
        while True:
            params = {"series_ticker": series, "status": "settled", "min_close_ts": min_ts, "max_close_ts": max_ts,
                      "limit": 1000, **({"cursor": cursor} if cursor else {})}
            status, body = self.get("/markets", **params)
            if status != 200:
                raise RuntimeError(f"/markets {series}: HTTP {status} {str(body)[:200]}")
            out += body.get("markets") or []
            cursor = body.get("cursor")
            if not cursor:
                return out

    def candles(self, series: str, ticker: str, start: pd.Timestamp, end: pd.Timestamp) -> list[dict]:
        out, a = [], start
        while a < end:
            b = min(a + CANDLE_SPAN, end)
            status, body = self.get(f"/series/{series}/markets/{ticker}/candlesticks",
                                    start_ts=int(a.timestamp()), end_ts=int(b.timestamp()), period_interval=1)
            if status != 200:
                raise RuntimeError(f"candles {ticker}: HTTP {status}")
            out += body.get("candlesticks") or []
            a = b
        return out

    def trades(self, ticker: str, max_ts: int) -> tuple[list[dict], bool]:
        out, cursor = [], None
        for _ in range(MAX_TRADE_PAGES):
            status, body = self.get("/markets/trades", ticker=ticker, max_ts=max_ts, limit=1000,
                                    **({"cursor": cursor} if cursor else {}))
            if status != 200:
                raise RuntimeError(f"trades {ticker}: HTTP {status}")
            out += body.get("trades") or []
            cursor = body.get("cursor")
            if not cursor:
                return out, False
        return out, True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-minutes", type=float, default=6)
    ap.add_argument("--since", default="2026-01-01")
    args = ap.parse_args()
    started, now = time.time(), datetime.now(timezone.utc)
    api = Kalshi()
    registry = pd.read_csv(REGISTRY, dtype=str, keep_default_na=False)
    by_fixture = registry.set_index("fixture_id", drop=False)
    log = load_kalshi_log(BASE)
    done = set(log.loc[log["status"].isin({"ok", "no_trades"}), "ticker"])

    listed = []
    for series in SERIES:
        for m in api.settled(series, int(pd.Timestamp(args.since, tz="UTC").timestamp()), int(now.timestamp())):
            if m.get("ticker") not in done:
                listed.append((series, m))
    # The last 3 days first, then the rest oldest first.
    recent = now - timedelta(days=DAILY_DAYS)
    head = [sm for sm in listed if _ts(sm[1].get("close_time")) >= recent]
    tail = sorted([sm for sm in listed if _ts(sm[1].get("close_time")) < recent], key=lambda sm: sm[1].get("close_time"))
    queue = head + tail
    events: dict[str, list] = {}
    for series, m in queue:
        events.setdefault(m["event_ticker"], []).append((series, m))

    raw_dir = KALSHI_DIR / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / f"{now:%Y-%m-%d_%H%M}.jsonl.gz"
    counts: dict[str, int] = {}
    markets, points, entries = [], [], []
    with gzip.open(raw_path, "at", encoding="utf-8") as raw:
        for event, items in events.items():
            if time.time() - started > args.max_minutes * 60:
                break
            mapping, method = match_fixture([m for _, m in items], registry)
            for series, m in items:
                fid, side = mapping.get(m["ticker"], ("", ""))
                fixture = by_fixture.loc[fid].to_dict() if fid and fid in by_fixture.index else None
                if should_wait(m, fixture, now):
                    counts["deferred"] = counts.get("deferred", 0) + 1      # not logged: retried next run
                    continue
                stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
                try:
                    cutoff, source = kalshi_cutoff(m, fixture)
                    opened = _ts(m.get("open_time")) or cutoff - timedelta(days=2)
                    closed = _ts(m.get("close_time")) or cutoff + timedelta(hours=6)
                    candles = api.candles(series, m["ticker"], opened, closed)
                    trades, truncated = api.trades(m["ticker"], int(cutoff.timestamp()))
                except (RuntimeError, ValueError, requests.RequestException) as exc:
                    entries.append({"ticker": m["ticker"], "close_utc": m.get("close_time"), "status": "error",
                                    "detail": str(exc)[:200], "pulled_utc": stamp})
                    counts["error"] = counts.get("error", 0) + 1
                    continue
                raw.write(json.dumps({"market": m, "candles": candles, "pre_start_trades": trades, "pulled_utc": stamp},
                                     separators=(",", ":")) + "\n")
                markets.append(market_record(m, series, fixture_id=fid, side=side, method=method, cutoff=cutoff,
                                             cutoff_source=source, pulled_utc=stamp))
                points.append(market_points(m, candles, trades, cutoff, fixture_id=fid, side=side, truncated=truncated))
                status = "ok" if trades or candles else "no_trades"
                entries.append({"ticker": m["ticker"], "close_utc": m.get("close_time"), "status": status,
                                "detail": method, "pulled_utc": stamp})
                counts[f"{status}:{method}"] = counts.get(f"{status}:{method}", 0) + 1
            if len(entries) >= 100:
                append_kalshi(markets, points, BASE)
                append_kalshi_log(entries, BASE)
                markets, points, entries = [], [], []
    append_kalshi(markets, points, BASE)
    append_kalshi_log(entries, BASE)
    # Match every stored market again: fixtures discovered since a market was stored count now.
    stored = load_stored_markets(BASE)
    fixture_map = rebuild_fixture_map(stored, registry)
    fixture_map.to_csv(BASE / KALSHI_DIR / "fixture_map.csv", index=False)
    result = {"run_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "listed_not_done": len(queue),
              "recent": len(head), "done": counts,
              "fixture_map": fixture_map["match_method"].value_counts().to_dict(), "api_calls": api.calls, "raw_file": raw_path.name,
              "minutes": round((time.time() - started) / 60, 1)}
    (BASE / KALSHI_DIR / "run_status.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
