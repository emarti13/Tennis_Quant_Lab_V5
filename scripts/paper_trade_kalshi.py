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

"join" (added 2026-10-20, before any of its results): a buy at the best bid and a sell at the
best ask, joining the back of each queue. Every poll reads the public order book: the
contracts ahead of us are the depth at our price when we joined, and only trades at our
price after those are filled us (orders cancelled ahead of us are not credited: cautious). A
trade through our price fills us. If the best price moves, we re-join at the back.
Same size and position limit as the other settings.

Files (append-only, in market_history/kalshi/paper/): snapshots_YYYY-MM-DD.csv, fills_YYYY-MM-DD.csv (UTC day; the server gzips past days),
state.json (last trade seen and positions per market and setting), results.csv (rewritten by
`settle` from the fills).

These fixtures are in the sealed period (from 2026-10-13): the paper run is the forward test of
settings chosen before it and must not be used to choose new ones (CLAUDE.md).

Start of the match: Kalshi's market `occurrence_datetime` is about 3 hours after the real
start (the first runs on 2026-10-19 quoted into matches already being played; those logs were
discarded). The cutoff is the match's `start_date` from Kalshi's milestone for the event, one
minute before; and from 2 hours before that, the milestone's live data is checked every poll:
once it is anything but "not_started" (including "match about to start"), nothing after the
previous poll counts. An event without a milestone is not quoted (fail closed). Snapshots are
as fresh as the poll interval; a trade more than 5 minutes after the last snapshot (a gap
between runs) is not scored.
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
from scripts.simulate_kalshi_making import LIMIT, MAKER_FEE_RATE, SIZE, fill, mid_fair, quotes  # noqa: E402

API = "https://api.elections.kalshi.com/trade-api/v2"
SERIES = ("KXATPCHALLENGERMATCH",)
HALF_WIDTHS = (0.03, 0.05)
JOIN = "join"                  # added 2026-10-20 (user): quote at the best bid and ask, at the back of the queue
SETTINGS = tuple(str(h) for h in HALF_WIDTHS) + (JOIN,)
DEPTH_COLS = ["ticker", "polled_utc", "best_bid", "bid_depth", "best_ask", "ask_depth", "join_bid_ahead", "join_ask_ahead"]
PAPER_DIR = BASE / "market_history" / "kalshi" / "paper"
CUTOFF_MINUTES = 1
LIVE_CHECK_HOURS = 2
MAX_QUOTE_AGE_MINUTES = 5      # a snapshot older than this (a gap between runs) stands for nothing
SNAP_COLS = ["ticker", "event_ticker", "player", "polled_utc", "start_utc", "best_bid", "best_ask", "volume"]
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

    def milestone(self, event_ticker: str) -> dict | None:
        """The event's match: {id, type, start_date}, or None."""
        ms = self.get("/milestones", {"related_event_ticker": event_ticker, "limit": 5}).get("milestones", [])
        ms = [m for m in ms if event_ticker in (m.get("primary_event_tickers") or [])] or ms
        return {k: ms[0].get(k) for k in ("id", "type", "start_date")} if ms else None

    def live_status(self, milestone: dict) -> str:
        """'not_started' until the match is about to begin; anything else means stop."""
        d = self.get(f"/live_data/{milestone['type']}/milestone/{milestone['id']}").get("live_data", {}).get("details", {})
        if d.get("status") == "not_started" and not d.get("match_status"):
            return "not_started"
        return f"{d.get('status')}/{d.get('match_status')}"

    def depth(self, ticker: str) -> dict:
        """{'yes': {price: contracts}, 'no': {price: contracts}}: resting bids on each side
        (a YES ask at a is a NO bid at 1 - a)."""
        ob = self.get(f"/markets/{ticker}/orderbook").get("orderbook_fp", {})
        return {side: {round(float(p), 2): float(q) for p, q in (ob.get(f"{side}_dollars") or [])} for side in ("yes", "no")}

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


def join_fill(taker: str, x: float, count: float, j: dict, pos: float):
    """A trade against our queued quotes (j: bid, bid_ahead, ask, ask_ahead; updated in place).
    Returns (side, price, contracts) or None."""
    if taker == "no" and j.get("bid") and pos < LIMIT:            # a seller hits the bids
        if x < j["bid"]:
            return ("buy", j["bid"], min(count, SIZE, LIMIT - pos))
        if x == j["bid"]:
            left = count - j["bid_ahead"]
            j["bid_ahead"] = max(0.0, -left)
            if left > 0:
                return ("buy", j["bid"], min(left, SIZE, LIMIT - pos))
    elif taker == "yes" and j.get("ask") and pos > -LIMIT:        # a buyer lifts the asks
        if x > j["ask"]:
            return ("sell", j["ask"], min(count, SIZE, LIMIT + pos))
        if x == j["ask"]:
            left = count - j["ask_ahead"]
            j["ask_ahead"] = max(0.0, -left)
            if left > 0:
                return ("sell", j["ask"], min(left, SIZE, LIMIT + pos))
    return None


def join_quote(prev: dict | None, best_bid, best_ask, book: dict) -> dict | None:
    """Our join quotes for the next interval: the best bid and ask, behind what rests there
    (behind less if contracts ahead of us were traded or cancelled; at the back after a move)."""
    if mid_fair(best_bid, best_ask) is None:
        return None
    bid_depth = book["yes"].get(round(best_bid, 2), 0.0)
    ask_depth = book["no"].get(round(1 - best_ask, 2), 0.0)
    j = {"bid": best_bid, "ask": best_ask, "bid_ahead": bid_depth, "ask_ahead": ask_depth,
         "bid_depth": bid_depth, "ask_depth": ask_depth}
    if prev:
        if prev.get("bid") == best_bid:
            j["bid_ahead"] = min(prev["bid_ahead"], bid_depth)
        if prev.get("ask") == best_ask:
            j["ask_ahead"] = min(prev["ask_ahead"], ask_depth)
    return j


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _append(name: str, rows: list[dict], cols: list[str], when: pd.Timestamp) -> None:
    if not rows:
        return
    PAPER_DIR.mkdir(parents=True, exist_ok=True)
    path = PAPER_DIR / f"{name}_{when:%Y-%m-%d}.csv"
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
    snaps, fills, seen, failed, depth_rows = [], [], 0, 0, []
    events = state.setdefault("events", {})
    previous_poll = state.get("last_poll")
    markets = [m for series in SERIES for m in api.open_markets(series)]
    for ev in sorted({m["event_ticker"] for m in markets}):
        e = events.setdefault(ev, {"milestone": None, "stop_at": None, "status": None})
        try:
            if e["milestone"] is None:
                e["milestone"] = api.milestone(ev)
            ms = e["milestone"]
            if ms and ms.get("start_date") and e["stop_at"] is None and \
                    now >= pd.Timestamp(ms["start_date"]) - pd.Timedelta(hours=LIVE_CHECK_HOURS):
                e["status"] = api.live_status(ms)
                if e["status"] != "not_started":       # started (or about to): nothing after the previous poll counts
                    e["stop_at"] = previous_poll or now.isoformat()
        except (RuntimeError, requests.HTTPError):
            failed += 1
            ms = e.get("milestone")
            if ms and ms.get("start_date") and e["stop_at"] is None and \
                    now >= pd.Timestamp(ms["start_date"]) - pd.Timedelta(hours=LIVE_CHECK_HOURS):
                e["stop_at"] = previous_poll or now.isoformat()   # cannot confirm it has not started: stop
    for m in markets:
        t = m["ticker"]
        e = events.get(m["event_ticker"], {})
        ms = e.get("milestone")
        if not ms or not ms.get("start_date"):
            continue                                   # no known start: fail closed, do not quote
        start = pd.Timestamp(ms["start_date"])
        cutoff = start - pd.Timedelta(minutes=CUTOFF_MINUTES)
        if e.get("stop_at"):
            cutoff = min(cutoff, pd.Timestamp(e["stop_at"]))
        st = state["markets"].setdefault(t, {"event": m.get("event_ticker"), "player": m.get("yes_sub_title"),
                                             "cutoff": cutoff.isoformat(), "last_trade_ts": None,
                                             "volume": None, "snapshot": None,
                                             "pos": {k: 0.0 for k in SETTINGS}})
        st["pos"].setdefault(JOIN, 0.0)
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
            jq = dict(st["join"]) if st.get("join") else None
            for tr in sorted(tape, key=lambda x: x["created_time"]):
                ts = pd.Timestamp(tr["created_time"])
                if ts <= pd.Timestamp(snap["polled_utc"]) or ts > cutoff:
                    continue
                if last_ts and ts <= pd.Timestamp(last_ts):
                    continue
                seen += 1
                if ts - pd.Timestamp(snap["polled_utc"]) > pd.Timedelta(minutes=MAX_QUOTE_AGE_MINUTES):
                    last_ts = tr["created_time"]
                    continue                           # no fresh quote was standing: not scored
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
                if jq:
                    got = join_fill(tr["taker_side"], float(tr["yes_price_dollars"]), float(tr["count_fp"]), jq, pos[JOIN])
                    if got:
                        side, price, q = got
                        pos[JOIN] += q if side == "buy" else -q
                        found.append({"ticker": t, "event_ticker": st["event"], "h": JOIN, "trade_id": tr.get("trade_id"),
                                      "trade_utc": tr["created_time"], "taker_side": tr["taker_side"],
                                      "trade_price": float(tr["yes_price_dollars"]), "trade_count": float(tr["count_fp"]),
                                      "side": side, "price": price, "contracts": q, "standing_bid": jq["bid"],
                                      "standing_ask": jq["ask"], "snapshot_utc": snap["polled_utc"]})
                last_ts = tr["created_time"]
            st["pos"], st["last_trade_ts"] = pos, last_ts
            if jq:
                st["join"] = jq
            fills += found
        # 2) the book standing from now until the next poll
        if now < cutoff:
            snap = {"polled_utc": now.isoformat(), "best_bid": _f(m.get("yes_bid_dollars")),
                    "best_ask": _f(m.get("yes_ask_dollars"))}
            st["snapshot"] = snap
            try:
                book = api.depth(t) if mid_fair(snap["best_bid"], snap["best_ask"]) is not None else None
            except (RuntimeError, requests.HTTPError):
                book = None
                failed += 1
            st["join"] = join_quote(st.get("join"), snap["best_bid"], snap["best_ask"], book) if book else None
            if st["join"]:
                j = st["join"]
                depth_rows.append({"ticker": t, "polled_utc": snap["polled_utc"], "best_bid": j["bid"], "bid_depth": j["bid_depth"],
                                   "best_ask": j["ask"], "ask_depth": j["ask_depth"], "join_bid_ahead": j["bid_ahead"],
                                   "join_ask_ahead": j["ask_ahead"]})
            snaps.append({"ticker": t, "event_ticker": st["event"], "player": st["player"], "polled_utc": snap["polled_utc"],
                          "start_utc": start.isoformat(), "best_bid": snap["best_bid"], "best_ask": snap["best_ask"],
                          "volume": volume})
        st["volume"] = volume
    state["last_poll"] = now.isoformat()
    _append("snapshots", snaps, SNAP_COLS, now)
    _append("fills", fills, FILL_COLS, now)
    _append("depth", depth_rows, DEPTH_COLS, now)
    return {"markets": len(snaps), "trades_checked": seen, "fills": len(fills), "markets_retry_next_poll": failed,
            "api_calls": api.calls}


def _read_log(path: Path, numeric: tuple[str, ...]) -> pd.DataFrame:
    """One log file with its number columns as numbers. A value that is not a number (a line cut
    by a write in progress, say) becomes empty and is reported, so settle names the bad file."""
    df = pd.read_csv(path, dtype={c: str for c in numeric})
    for c in numeric:
        raw = df[c]
        df[c] = pd.to_numeric(raw, errors="coerce")
        bad = raw.notna() & df[c].isna()
        if bad.any():
            print(f"{path.name}: {int(bad.sum())} non-numeric {c} values, e.g. {raw[bad].iloc[0]!r} (row {bad.idxmax()})",
                  file=sys.stderr)
    return df


def settle(api: Kalshi) -> pd.DataFrame:
    """Per market and setting: contracts, profit held to settlement, and marked at the last
    mid before the cutoff (with and without Kalshi's maker fee schedule)."""
    fill_files = sorted(PAPER_DIR.glob("fills_*.csv*"))                # daily files; past days gzipped
    fills = (pd.concat([_read_log(p, ("trade_price", "trade_count", "price", "contracts")) for p in fill_files])
             if fill_files else pd.DataFrame(columns=FILL_COLS))
    snaps = pd.concat([_read_log(p, ("best_bid", "best_ask", "volume")) for p in sorted(PAPER_DIR.glob("snapshots_*.csv*"))])
    rows = []
    for t, g in snaps.groupby("ticker"):
        m = api.get(f"/markets/{t}").get("market", {})
        result = m.get("result")
        last = g.sort_values("polled_utc").iloc[-1]
        mark = mid_fair(last["best_bid"], last["best_ask"])
        for h in SETTINGS:
            f = fills[(fills["ticker"] == t) & (fills["h"].astype(str) == h)]
            row = {"ticker": t, "event_ticker": last["event_ticker"], "h": h, "result": result,
                   "start_utc": last["start_utc"], "contracts": float(f["contracts"].sum()),
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
        for h, g in done.groupby(done["h"].astype(str)):
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
