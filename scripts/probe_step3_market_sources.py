"""One-off probe before building the Step 3 market data layer (user-approved 2026-10-16).

Checks three things the design (docs/superpowers/specs/2026-10-16-market-data-layer-design.md)
relies on, and writes what it saw to research/step3_probe/result.json:

1. OddsPapi /historical-odds does not count against the request quota (the /account
   request_count before and after about 12 calls), and the real quota limit.
2. What /historical-odds returns for fixtures that finished 1-4 days ago, for one from the
   stored January-August backfill, and for ones that have not started yet: which books, how
   many quotes, and how close to the start the last pre-start quote is.
3. Kalshi's public market-data API: does it answer, which tennis series does it list, and do
   settled markets have trades and hourly candles.

Read-only against both APIs; no API key is ever written to the output.
"""
from __future__ import annotations

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
from historical_odds_normalizer import flatten_history  # noqa: E402

ODDS = "https://api.oddspapi.io/v4"
KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
OUT = BASE / "research" / "step3_probe" / "result.json"
CORE_BOOKS = "pinnacle,betrivers,draftkings"
WIDE_BOOKS = "pinnacle,betrivers,draftkings,bet365,kalshi,polymarket,novig,fanduel"


def _get(url, params=None, timeout=30):
    t = time.time()
    try:
        r = requests.get(url, params=params, timeout=timeout)
    except Exception as exc:  # network failure is a finding, not a crash
        return None, {"error": repr(exc)[:300]}
    meta = {"status": r.status_code, "seconds": round(time.time() - t, 2),
            "headers": {k: v for k, v in r.headers.items() if any(w in k.lower() for w in ("limit", "remain", "quota", "credit"))}}
    try:
        return r.json(), meta
    except Exception:
        meta["text"] = r.text[:300]
        return None, meta


def _quota(key):
    body, meta = _get(f"{ODDS}/account", {"apiKey": key})
    subs = (body or {}).get("subscriptions") or []
    cur = next((s for s in subs if s.get("subscription_id") == (body or {}).get("current_subscription_id")), None) \
        or next((s for s in subs if s.get("is_active")), None) or {}
    return {"request_limit": cur.get("request_limit"), "request_count": cur.get("request_count"),
            "valid_from": cur.get("valid_from"), "valid_until": cur.get("valid_until"),
            "plan": cur.get("plan_name") or cur.get("name"), "http": meta}


def _summarize_history(payload, start):
    rows = flatten_history(payload or {})
    out = {}
    for book in sorted({r["bookmaker"] for r in rows}):
        br = [r for r in rows if r["bookmaker"] == book]
        pre = [r for r in br if r["created_at"] < start]
        last_pre = max((r["created_at"] for r in pre), default=None)
        out[book] = {
            "quotes": len(br), "pre_start_quotes": len(pre), "markets": len({r["market_id"] for r in br}),
            "first_quote_h_before_start": round((start - min(r["created_at"] for r in br)).total_seconds() / 3600, 2),
            "last_pre_start_min_before_start": round((start - last_pre).total_seconds() / 60, 1) if last_pre else None,
            "has_active_flag": any(r["active"] is not None for r in br),
            "has_limit": any(r["limit"] is not None for r in br),
        }
    return out


def oddspapi(key):
    f = pd.read_csv(BASE / "oddspapi_registry" / "fixtures.csv", low_memory=False)
    f["start"] = pd.to_datetime(f["true_start_time_utc"].fillna(f["start_time_utc"]), utc=True, errors="coerce")
    now = pd.Timestamp.now(tz="UTC")
    tier = lambda df: df[df["tournament_name"].str.contains("ATP|WTA|Challenger", case=False, na=False)]
    recent = tier(f[(f["start"] < now - pd.Timedelta(days=1)) & (f["start"] > now - pd.Timedelta(days=4))])
    picks = []
    name = recent["tournament_name"]
    for sub in (recent[name.str.contains("Challenger")], recent[name.str.contains("WTA")],
                recent[name.str.contains("ATP") & ~name.str.contains("Challenger")]):  # a mix of tours
        picks += list(sub.sample(n=min(2, len(sub)), random_state=1)["fixture_id"])
    old = f[f["historical_status"] == "CACHED"]
    if len(old):
        picks.append(old.sample(n=1, random_state=1)["fixture_id"].iloc[0])
    upcoming = tier(f[f["start"] > now + pd.Timedelta(hours=1)])
    picks += list(upcoming.head(2)["fixture_id"])
    picks = list(dict.fromkeys(picks))[:10]

    before = _quota(key)
    after_account_only = _quota(key)      # does /account itself count?
    calls = []
    for i, fid in enumerate(picks):
        row = f[f["fixture_id"] == fid].iloc[0]
        books = WIDE_BOOKS if i == 0 else CORE_BOOKS
        body, meta = _get(f"{ODDS}/historical-odds", {"apiKey": key, "fixtureId": fid, "bookmakers": books})
        start = row["start"].to_pydatetime()
        calls.append({
            "fixture_id": fid, "tournament": row["tournament_name"], "start_utc": str(row["start"]),
            "kind": "upcoming" if row["start"] > now else ("stored_backfill" if fid in set(old["fixture_id"]) else "recent"),
            "books_asked": books, "http": meta,
            "error": None if meta.get("status") == 200 else (json.dumps(body)[:300] if body else meta.get("text")),
            "books": _summarize_history(body, start) if meta.get("status") == 200 else {},
        })
        time.sleep(1.2)
    after = _quota(key)
    return {"quota_before": before, "quota_after_account_only": after_account_only, "quota_after": after,
            "historical_calls": len(calls),
            "count_delta": (after["request_count"] or 0) - (after_account_only["request_count"] or 0)
            if after["request_count"] is not None and after_account_only["request_count"] is not None else None,
            "calls": calls}


def kalshi():
    res = {}
    body, meta = _get(f"{KALSHI}/series", {"category": "Sports"})
    res["series_http"] = meta
    series = (body or {}).get("series") or []
    tennis = [s for s in series if any(w in (str(s.get("title")) + " " + " ".join(s.get("tags") or [])).lower()
                                      for w in ("tennis", "atp", "wta", "wimbledon", "us open", "challenger"))]
    res["sports_series"] = len(series)
    res["tennis_series"] = [{"ticker": s.get("ticker"), "title": s.get("title"), "tags": s.get("tags")} for s in tennis][:40]
    samples = []
    for s in tennis[:6]:
        mb, mm = _get(f"{KALSHI}/markets", {"series_ticker": s["ticker"], "status": "settled", "limit": 5})
        markets = (mb or {}).get("markets") or []
        entry = {"series": s["ticker"], "markets_http": mm.get("status"), "settled_markets_seen": len(markets)}
        if markets:
            m = markets[0]
            entry["example"] = {k: m.get(k) for k in ("ticker", "title", "event_ticker", "open_time", "close_time",
                                                      "expected_expiration_time", "result", "volume", "status")}
            tb, tm = _get(f"{KALSHI}/markets/trades", {"ticker": m["ticker"], "limit": 1000})
            trades = (tb or {}).get("trades") or []
            entry["trades_http"], entry["trades_seen"] = tm.get("status"), len(trades)
            entry["trade_fields"] = sorted(trades[0].keys()) if trades else []
            close = pd.Timestamp(m.get("close_time") or datetime.now(timezone.utc))
            cb, cm = _get(f"{KALSHI}/series/{s['ticker']}/markets/{m['ticker']}/candlesticks",
                          {"start_ts": int((close - pd.Timedelta(days=3)).timestamp()), "end_ts": int(close.timestamp()),
                           "period_interval": 60})
            candles = (cb or {}).get("candlesticks") or []
            entry["candles_http"], entry["candles_seen"] = cm.get("status"), len(candles)
            if cm.get("status") != 200:
                entry["candles_error"] = json.dumps(cb)[:300] if cb else cm.get("text")
        samples.append(entry)
    res["samples"] = samples
    return res


def main():
    key = os.getenv("ODDSPAPI_KEY")
    result = {"run_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    result["oddspapi"] = oddspapi(key) if key else {"error": "ODDSPAPI_KEY not set"}
    result["kalshi"] = kalshi()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(result, indent=2, default=str)
    assert not key or key not in text
    OUT.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
