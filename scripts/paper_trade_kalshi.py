"""Paper-trade the Kalshi Challenger market maker live (research, edge search 3). No orders are sent.

Usage:
  python scripts/paper_trade_kalshi.py poll [--minutes 120] [--interval 60]   # watch and record
  python scripts/paper_trade_kalshi.py settle                                 # score finished matches

The forward test of the settings fixed by docs/experiments/2026-10-19-kalshi-making-sim.md:
Challenger match markets, a buy and a sell 3c and 5c either side of Kalshi's mid, 100
contracts a side, at most 300 net per market, cancelled one minute before the scheduled
start. Same quote and fill rules as the simulation (`simulate_kalshi_making.quotes` / `fill`),
so the paper result is comparable with the replay.

Every poll, from Kalshi's public API (no account, no key):
- each open Challenger market's best bid/ask, appended to snapshots (the quote we would have
  standing until the next poll);
- the trades since the last poll for markets whose volume moved, each checked against the
  quote standing before it (the latest snapshot taken before the trade).
`settle` scores markets whose result is final: held to settlement, and marked at the last mid
before the cutoff.

Files (append-only, in market_history/kalshi/paper/): snapshots_YYYY-MM.csv, fills_YYYY-MM.csv,
state.json (last trade seen and positions per market and setting), results.csv (rewritten by
`settle` from the fills).

These fixtures are in the sealed period (from 2026-10-13): the paper run is the forward test of
settings chosen before it and must not be used to choose new ones (CLAUDE.md).

Limits: the cutoff is Kalshi's scheduled time (`occurrence_datetime`); a match that starts
earlier than scheduled lets in-play trades in until then. Snapshots are as fresh as the poll
interval.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import pandas as pd
import requests

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from scripts.simulate_kalshi_making import MAKER_FEE_RATE, fill, mid_fair, quotes  # noqa: E402

API = "https://api.elections.kalshi.com/trade-api/v2"
SERIES = ("KXATPCHALLENGERMATCH",)
HALF_WIDTHS = (0.03, 0.05)
PAPER_DIR = BASE / "market_history" / "kalshi" / "paper"
CUTOFF_MINUTES = 1
SNAP_COLS = ["ticker", "event_ticker", "player", "polled_utc", "occurrence_utc", "best_bid", "best_ask", "volume"]
FILL_COLS = ["ticker", "event_ticker", "h", "trade_id", "trade_utc", "taker_side", "trade_price", "trade_count",
             "side", "price", "contracts", "standing_bid", "standing_ask", "snapshot_utc"]


class Kalshi:
    """Public market data, throttled, retrying on rate limits and network errors."""

    def __init__(self, pause: float = 0.6):
        self.s, self.pause, self.calls = requests.Session(), pause, 0

    def get(self, path: str, params: dict | None = None) -> dict:
        for wait in (0, 2, 5, 15, 30):
            time.sleep(wait or self.pause)
            try:
                r = self.s.get(API + path, params=params, timeout=30)
                self.calls += 1
            except requests.RequestException:
                continue
            if r.status_code == 429 or r.status_code >= 500:
                continue
            r.raise_for_status()
            return r.json()
        raise RuntimeError(f"Kalshi {path} kept failing")

    def open_markets(self, series: str) -> list[dict]:
        out, cursor = [], None
        while True:
            params = {"series_ticker": series, "status": "open", "limit": 200}
            if cursor:
                params["cursor"] = cursor
            page = self.get("/markets", params)
            out += page.get("markets", [])
            cursor = page.get("cursor")
            if not cursor:
                return out

    def trades(self, ticker: str, min_ts: int) -> list[dict]:
        out, cursor = [], None
        while True:
            params = {"ticker": ticker, "min_ts": min_ts, "limit": 1000}
            if cursor:
                params["cursor"] = cursor
            page = self.get("/markets/trades", params)
            out += page.get("trades", [])
            cursor = page.get("cursor")
            if not cursor:
                return out


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _append(name: str, rows: list[dict], cols: list[str], when: pd.Timestamp) -> None:
    if not rows:
        return
    PAPER_DIR.mkdir(parents=True, exist_ok=True)
    path = PAPER_DIR / f"{name}_{when:%Y-%m}.csv"
    pd.DataFrame(rows, columns=cols).to_csv(path, mode="a", header=not path.exists(), index=False)


def load_state() -> dict:
    p = PAPER_DIR / "state.json"
    return json.loads(p.read_text()) if p.exists() else {"markets": {}}


def save_state(state: dict) -> None:
    PAPER_DIR.mkdir(parents=True, exist_ok=True)
    (PAPER_DIR / "state.json").write_text(json.dumps(state, indent=1, sort_keys=True) + "\n")


def poll_once(api: Kalshi, state: dict, now: pd.Timestamp) -> dict:
    """One poll: score the trades since the last poll against the quote that was standing,
    then record the new standing book. Returns counts for the log line."""
    snaps, fills, seen, failed = [], [], 0, 0
    for series in SERIES:
        for m in api.open_markets(series):
            t = m["ticker"]
            occ = pd.Timestamp(m.get("occurrence_datetime") or m.get("expected_expiration_time"))
            cutoff = occ - pd.Timedelta(minutes=CUTOFF_MINUTES)
            st = state["markets"].setdefault(t, {"event": m.get("event_ticker"), "player": m.get("yes_sub_title"),
                                                 "cutoff": cutoff.isoformat(), "last_trade_ts": None,
                                                 "volume": None, "snapshot": None,
                                                 "pos": {str(h): 0.0 for h in HALF_WIDTHS}})
            st["cutoff"] = cutoff.isoformat()
            volume = _f(m.get("volume_fp"))
            snap = st.get("snapshot")
            # 1) trades since the last poll, against the quote standing from the last snapshot.
            # A market whose trades cannot be fetched keeps its state and is retried next poll.
            if snap is not None and volume is not None and volume != st.get("volume"):
                try:
                    tape = api.trades(t, int(pd.Timestamp(snap["polled_utc"]).timestamp()))
                except RuntimeError:
                    failed += 1
                    continue
                pos, last_ts, found = dict(st["pos"]), st["last_trade_ts"], []
                for tr in sorted(tape, key=lambda x: x["created_time"]):
                    ts = pd.Timestamp(tr["created_time"])
                    if ts <= pd.Timestamp(snap["polled_utc"]) or ts > cutoff:
                        continue
                    if last_ts and ts <= pd.Timestamp(last_ts):
                        continue
                    seen += 1
                    fair = mid_fair(snap["best_bid"], snap["best_ask"])
                    if fair is not None:
                        for h in HALF_WIDTHS:
                            bid, ask = quotes(fair, h, snap["best_bid"], snap["best_ask"])
                            got = fill(tr["taker_side"], float(tr["yes_price_dollars"]), float(tr["count_fp"]),
                                       bid, ask, snap["best_bid"], snap["best_ask"], pos[str(h)])
                            if got:
                                side, price, q = got
                                pos[str(h)] += q if side == "buy" else -q
                                found.append({"ticker": t, "event_ticker": st["event"], "h": h, "trade_id": tr.get("trade_id"),
                                              "trade_utc": tr["created_time"], "taker_side": tr["taker_side"],
                                              "trade_price": float(tr["yes_price_dollars"]), "trade_count": float(tr["count_fp"]),
                                              "side": side, "price": price, "contracts": q, "standing_bid": bid,
                                              "standing_ask": ask, "snapshot_utc": snap["polled_utc"]})
                    last_ts = tr["created_time"]
                st["pos"], st["last_trade_ts"] = pos, last_ts
                fills += found
            # 2) the book standing from now until the next poll
            if now < cutoff:
                snap = {"polled_utc": now.isoformat(), "best_bid": _f(m.get("yes_bid_dollars")),
                        "best_ask": _f(m.get("yes_ask_dollars"))}
                st["snapshot"] = snap
                snaps.append({"ticker": t, "event_ticker": st["event"], "player": st["player"], "polled_utc": snap["polled_utc"],
                              "occurrence_utc": occ.isoformat(), "best_bid": snap["best_bid"], "best_ask": snap["best_ask"],
                              "volume": volume})
            st["volume"] = volume
    _append("snapshots", snaps, SNAP_COLS, now)
    _append("fills", fills, FILL_COLS, now)
    return {"markets": len(snaps), "trades_checked": seen, "fills": len(fills), "markets_retry_next_poll": failed,
            "api_calls": api.calls}


def settle(api: Kalshi) -> pd.DataFrame:
    """Per market and setting: contracts, profit held to settlement, and marked at the last
    mid before the cutoff (with and without Kalshi's maker fee schedule)."""
    fills = pd.concat([pd.read_csv(p) for p in sorted(PAPER_DIR.glob("fills_*.csv"))]) if list(PAPER_DIR.glob("fills_*.csv")) else pd.DataFrame(columns=FILL_COLS)
    snaps = pd.concat([pd.read_csv(p) for p in sorted(PAPER_DIR.glob("snapshots_*.csv"))])
    rows = []
    for t, g in snaps.groupby("ticker"):
        m = api.get(f"/markets/{t}").get("market", {})
        result = m.get("result")
        last = g.sort_values("polled_utc").iloc[-1]
        mark = mid_fair(last["best_bid"], last["best_ask"])
        for h in HALF_WIDTHS:
            f = fills[(fills["ticker"] == t) & (fills["h"] == h)]
            row = {"ticker": t, "event_ticker": last["event_ticker"], "h": h, "result": result,
                   "occurrence_utc": last["occurrence_utc"], "contracts": float(f["contracts"].sum()),
                   "end_position": float((f["contracts"] * f["side"].map({"buy": 1, "sell": -1})).sum())}
            fee = float((MAKER_FEE_RATE * f["contracts"] * f["price"] * (1 - f["price"])).sum())
            for name, value in (("held", {"yes": 1.0, "no": 0.0}.get(result)), ("marked", mark)):
                if value is None:
                    row[name] = row[f"{name}_after_maker_fee"] = None
                    continue
                p = float((f["contracts"] * ((value - f["price"]).where(f["side"] == "buy", f["price"] - value))).sum())
                row[name], row[f"{name}_after_maker_fee"] = round(p, 2), round(p - fee, 2)
            rows.append(row)
    out = pd.DataFrame(rows)
    out.to_csv(PAPER_DIR / "results.csv", index=False)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["poll", "settle"])
    ap.add_argument("--minutes", type=float, default=0, help="keep polling this long (0 = one poll)")
    ap.add_argument("--interval", type=float, default=60, help="seconds between polls")
    args = ap.parse_args()
    api = Kalshi()
    if args.command == "settle":
        out = settle(api)
        done = out[out["result"].isin(["yes", "no"])]
        for h, g in done.groupby("h"):
            print(f"h={h}: markets {g['ticker'].nunique()}, contracts {g['contracts'].sum():.0f}, "
                  f"marked ${g['marked'].sum():.2f}, held ${g['held'].sum():.2f}")
        return 0
    state = load_state()
    end = time.time() + args.minutes * 60
    while True:
        started = time.time()
        now = pd.Timestamp.now(tz="UTC").floor("s")
        try:
            info = poll_once(api, state, now)
            save_state(state)
            print(f"{now.isoformat()} {json.dumps(info)}", flush=True)
        except Exception as exc:                               # keep watching; the next poll retries
            print(f"{now.isoformat()} poll failed: {exc}", flush=True)
        if time.time() >= end:
            return 0
        time.sleep(max(0.0, args.interval - (time.time() - started)))


if __name__ == "__main__":
    raise SystemExit(main())
