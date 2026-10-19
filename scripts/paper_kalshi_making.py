"""Kalshi Challenger paper market making: quotes computed live, nothing sent (roadmap Phase 4).

Usage:  python scripts/paper_kalshi_making.py run [--poll 10] [--max-minutes 0] [--out DIR]
        python scripts/paper_kalshi_making.py report [--out DIR]

The forward test of docs/experiments/2026-10-19-kalshi-making-sim.md, with the settings fixed
before it starts: ATP Challenger match markets (KXATPCHALLENGERMATCH) only, half-widths 3 and
5 cents around Kalshi's own mid, 100 contracts a side, at most 300 net per market, stop one
minute before the start. Quote and fill rules come from v5_kalshi_making, the same code as the
replay (scripts/simulate_kalshi_making.py).

`run` polls Kalshi's free public market-data API (no account, no keys, and no order endpoint
is ever called). Each poll:
1. lists the open Challenger markets with their best bid/ask (one book snapshot per market);
2. asks Kalshi's live match feed (/live_data, one per match milestone) whether each match has
   started. The start: Kalshi's `occurrence_datetime` is not it (it is the milestone's
   scheduled start + 3 h on every market checked, 2026-10-19), and matches often start later
   than scheduled;
3. fetches the new trades of every market whose volume moved, and checks each against the
   quotes we would have had standing from the snapshot taken before it.
A trade counts only once a later poll has seen the match still "not_started" at least one
minute after the trade (the stop: one minute before the start, as in the replay). Fail
closed: no milestone, no live status, any status other than "not_started", a one-sided or
>20-cent book, or a snapshot older than --max-age seconds gives no quote.

Meant for the user's own machine: Actions cannot poll (CLAUDE.md), and a cloud session's
container does not last. Logs, append-only, under --out (default paper_trading/kalshi_making/,
not committed): markets.csv (first seen), snapshots.csv (best bid/ask when it changes),
status.csv (the start seen live), trades.csv (every trade counted, with its status),
fills.csv (our paper fills). A restart rebuilds positions and the trades already seen; it
needs fresh snapshots before it quotes again.

`report` settles what has finished: the result from Kalshi; fills after the true start known
to the price store (market_history/kalshi/markets, cutoff_source true_start) are dropped as a
second check. Each half-width is counted marked at Kalshi's last mid before the stop (the
test, as in the replay), held to settlement, with and without the maker fee, plus markouts
at 1 and 5 minutes. Writes report.json in --out.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from v5_kalshi_history import KALSHI_DIR  # noqa: E402
from v5_kalshi_making import STOP_BEFORE, MarketBook, pnl  # noqa: E402

API = "https://api.elections.kalshi.com/trade-api/v2"
SERIES = "KXATPCHALLENGERMATCH"
HALF_WIDTHS = (0.03, 0.05)
OUT = BASE / "paper_trading" / "kalshi_making"
PAUSE = 0.15                  # under the public rate limit
LIVE_BATCH = 50
BOOTSTRAP = 2000

MARKET_COLS = ["ticker", "event_ticker", "title", "milestone_id", "scheduled_start_utc", "occurrence_utc", "first_seen_utc"]
SNAP_COLS = ["ts_utc", "ticker", "best_bid", "best_ask", "bid_size", "ask_size", "volume"]
STATUS_COLS = ["event_ticker", "milestone_id", "last_not_started_utc", "first_other_utc", "status"]
TRADE_COLS = ["trade_id", "ticker", "ts_utc", "yes_price", "count", "taker_side", "status", "seen_utc"]
FILL_COLS = ["trade_id", "ticker", "ts_utc", "h", "side", "price", "contracts", "position_after",
             "snapshot_utc", "best_bid", "best_ask"]


def _num(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x > 0 else None


def _ts(v) -> pd.Timestamp | None:
    t = pd.to_datetime(v, utc=True, errors="coerce") if v else None
    return None if t is None or pd.isna(t) else t


def _now() -> pd.Timestamp:
    return pd.Timestamp.now(tz="UTC")


def _read(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False) if path.exists() else pd.DataFrame()


class Log:
    """Append-only CSV logs."""

    def __init__(self, out: Path):
        out.mkdir(parents=True, exist_ok=True)
        self.files = {"markets": (out / "markets.csv", MARKET_COLS), "snapshots": (out / "snapshots.csv", SNAP_COLS),
                      "status": (out / "status.csv", STATUS_COLS), "trades": (out / "trades.csv", TRADE_COLS),
                      "fills": (out / "fills.csv", FILL_COLS)}

    def write(self, name: str, rows: list[dict]) -> None:
        if not rows:
            return
        path, cols = self.files[name]
        new = not path.exists()
        with path.open("a", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            if new:
                w.writeheader()
            w.writerows(rows)


class Kalshi:
    """Read-only public market data. There is deliberately no method that sends an order."""

    def __init__(self):
        self.session = requests.Session()
        self.calls = 0

    def get(self, path: str, **params) -> dict:
        for attempt in range(6):
            self.calls += 1
            r = self.session.get(f"{API}{path}", params=params, timeout=30)
            time.sleep(PAUSE)
            if r.status_code == 429:
                time.sleep(2 ** attempt)
                continue
            r.raise_for_status()
            return r.json()
        r.raise_for_status()
        return {}

    def _pages(self, path: str, key: str, **params) -> list[dict]:
        out, cursor = [], None
        while True:
            body = self.get(path, limit=1000 if key != "milestones" else 200, **params, **({"cursor": cursor} if cursor else {}))
            out += body.get(key) or []
            cursor = body.get("cursor")
            if not cursor:
                return out

    def open_markets(self) -> list[dict]:
        return self._pages("/markets", "markets", series_ticker=SERIES, status="open")

    def trades(self, ticker: str, min_ts: int) -> list[dict]:
        return self._pages("/markets/trades", "trades", ticker=ticker, min_ts=min_ts)

    def milestone(self, event_ticker: str) -> dict | None:
        """The match milestone of an event, or None (fail closed) unless exactly one."""
        ms = [m for m in self.get("/milestones", related_event_ticker=event_ticker, limit=20).get("milestones") or []
              if event_ticker in (m.get("primary_event_tickers") or [])]
        return ms[0] if len(ms) == 1 else None

    def live_status(self, milestone_ids: list[str]) -> dict[str, str]:
        """milestone id -> Kalshi's live match status ('not_started', 'live', ...)."""
        out = {}
        for i in range(0, len(milestone_ids), LIVE_BATCH):
            body = self.get("/live_data/batch", milestone_ids=milestone_ids[i:i + LIVE_BATCH])
            for d in body.get("live_datas") or []:
                out[d.get("milestone_id")] = str((d.get("details") or {}).get("status") or "")
        return out

    def market(self, ticker: str) -> dict:
        return self.get(f"/markets/{ticker}").get("market") or {}


class PaperRun:
    """State of the paper run: one MarketBook per market, rebuilt from the logs on restart.

    `horizon[t]`: trades up to here are counted (last poll that saw the match not started,
    minus STOP_BEFORE). Trades fetched beyond it wait in `pending` for the next poll; once the
    match is seen started the horizon is final and the book's stop is set to it."""

    def __init__(self, out: Path, max_age: pd.Timedelta):
        self.log, self.max_age = Log(out), max_age
        self.books: dict[str, MarketBook] = {}
        self.meta: dict[str, dict] = {}
        self.started: set[str] = set()                    # events seen started: their books are final
        self.horizon: dict[str, pd.Timestamp] = {}        # event -> trades counted up to here
        self.pending: dict[str, dict[str, dict]] = {}     # ticker -> trade id -> trade
        self.last_snap: dict[str, tuple] = {}
        self.volume: dict[str, float] = {}                # volume when trades were last fetched
        self.fetched: dict[str, pd.Timestamp] = {}        # trades fetched from here on, next time
        markets, fills, trades, status = (_read(out / f) for f in ("markets.csv", "fills.csv", "trades.csv", "status.csv"))
        self.seen = set(trades["trade_id"]) if len(trades) else set()
        for r in markets.to_dict("records"):
            self._open(r)
        for r in status.to_dict("records"):                 # a start seen before a restart stays final
            self.started.add(r["event_ticker"])
            for t, m in self.meta.items():
                if m["event_ticker"] == r["event_ticker"]:
                    self.books[t].stop = _ts(r["last_not_started_utc"]) - STOP_BEFORE if r["last_not_started_utc"] else self.books[t].stop
        for r in fills.to_dict("records"):                  # positions carry over a restart
            b = self.books.get(r["ticker"])
            if b is not None:
                h = float(r["h"])
                b.fills[h].append((r["side"], float(r["price"]), float(r["contracts"])))
                b.pos[h] = float(r["position_after"])
        for t, g in trades.groupby("ticker") if len(trades) else []:
            self.fetched[t] = pd.to_datetime(g["ts_utc"], utc=True).max()

    def _open(self, r: dict) -> None:
        self.meta[r["ticker"]] = r
        self.books[r["ticker"]] = MarketBook(None, HALF_WIDTHS, self.max_age)

    def new_markets(self, markets: list[dict], milestone, at: pd.Timestamp) -> None:
        rows = []
        events = {}
        for m in markets:
            if m.get("ticker") in self.books or m.get("event_ticker") in self.started:
                continue
            ev = m.get("event_ticker", "")
            if ev not in events:
                events[ev] = milestone(ev)
            ms = events[ev]
            r = {"ticker": m["ticker"], "event_ticker": ev, "title": m.get("title", ""),
                 "milestone_id": (ms or {}).get("id", ""), "scheduled_start_utc": (ms or {}).get("start_date", ""),
                 "occurrence_utc": m.get("occurrence_datetime", ""), "first_seen_utc": at.isoformat()}
            self._open(r)
            self.fetched[m["ticker"]] = at                  # only trades after our first snapshot count
            rows.append(r)
        self.log.write("markets", rows)

    def on_listing(self, markets: list[dict], at: pd.Timestamp) -> list[str]:
        """One snapshot per market not yet started; returns the markets whose trades need fetching."""
        snaps, due = [], []
        for m in markets:
            t = m.get("ticker")
            if t not in self.books or self.meta[t]["event_ticker"] in self.started:
                continue
            bid, ask = _num(m.get("yes_bid_dollars")), _num(m.get("yes_ask_dollars"))
            vol = float(m.get("volume_fp") or 0)
            self.books[t].snapshot(at, bid, ask)
            if self.last_snap.get(t) != (bid, ask):
                snaps.append({"ts_utc": at.isoformat(), "ticker": t, "best_bid": bid or "", "best_ask": ask or "",
                              "bid_size": m.get("yes_bid_size_fp", ""), "ask_size": m.get("yes_ask_size_fp", ""), "volume": vol})
                self.last_snap[t] = (bid, ask)
            if t not in self.volume:                         # first sight (or a restart): earlier trades have no book
                self.volume[t] = vol
            elif vol != self.volume[t]:
                due.append(t)
                self.volume[t] = vol
        self.log.write("snapshots", snaps)
        return due

    def on_status(self, live: dict[str, str], at: pd.Timestamp) -> None:
        """Move each match's horizon; a match no longer "not_started" is final."""
        rows = []
        for ev in {m["event_ticker"] for m in self.meta.values()} - self.started:
            tickers = [t for t, m in self.meta.items() if m["event_ticker"] == ev]
            mid = self.meta[tickers[0]]["milestone_id"]
            status = live.get(mid) if mid else None
            if status == "not_started":
                self.horizon[ev] = at - STOP_BEFORE
                continue
            if status is None and mid:
                continue                                     # not answered this poll: the horizon waits
            self.started.add(ev)                             # started, finished, unknown, or no milestone
            stop = self.horizon.get(ev, pd.Timestamp.min.tz_localize("UTC"))
            for t in tickers:
                self.books[t].stop = stop
            rows.append({"event_ticker": ev, "milestone_id": mid, "status": status or "no_milestone",
                         "last_not_started_utc": (self.horizon[ev] + STOP_BEFORE).isoformat() if ev in self.horizon else "",
                         "first_other_utc": at.isoformat()})
        self.log.write("status", rows)

    def on_trades(self, ticker: str, trades: list[dict]) -> None:
        box = self.pending.setdefault(ticker, {})
        for t in trades:
            if t.get("trade_id") and t["trade_id"] not in self.seen and _ts(t.get("created_time")):
                box[t["trade_id"]] = t

    def evaluate(self, at: pd.Timestamp) -> int:
        """Count the pending trades up to each market's horizon, in time order; returns fills."""
        rows, fills = [], []
        for ticker, box in self.pending.items():
            ev, book = self.meta[ticker]["event_ticker"], self.books[ticker]
            horizon = book.stop if ev in self.started else self.horizon.get(ev)
            if horizon is None or not box:
                continue
            ready = sorted((t for t in box.values() if _ts(t["created_time"]) <= horizon),
                           key=lambda t: (_ts(t["created_time"]), t["trade_id"]))
            for t in ready:
                ts = _ts(t["created_time"])
                snap = book.standing(ts)
                status, got = book.trade(ts, float(t["yes_price_dollars"]), float(t["count_fp"]), t["taker_side"])
                self.seen.add(t["trade_id"])
                del box[t["trade_id"]]
                rows.append({"trade_id": t["trade_id"], "ticker": ticker, "ts_utc": ts.isoformat(), "yes_price": t["yes_price_dollars"],
                             "count": t["count_fp"], "taker_side": t["taker_side"], "status": status, "seen_utc": at.isoformat()})
                for h, side, price, q, pos in got:
                    fills.append({"trade_id": t["trade_id"], "ticker": ticker, "ts_utc": ts.isoformat(), "h": h, "side": side,
                                  "price": price, "contracts": q, "position_after": pos, "snapshot_utc": snap[0].isoformat(),
                                  "best_bid": snap[1] or "", "best_ask": snap[2] or ""})
            if ev in self.started:
                box.clear()                                  # after the stop: never counted
        self.log.write("trades", rows)
        self.log.write("fills", fills)
        return len(fills)


def run(args) -> int:
    out = Path(args.out)
    state = PaperRun(out, pd.Timedelta(seconds=args.max_age))
    api, started, polls, n_fills = Kalshi(), time.time(), 0, 0
    print(f"paper run: {SERIES}, half-widths {HALF_WIDTHS}, logs in {out} (no orders are sent)", flush=True)
    while True:
        tick = time.time()
        try:
            listing = api.open_markets()
            at = _now()                                      # after the response: the book is at least this old
            state.new_markets(listing, api.milestone, at)
            due = state.on_listing(listing, at)
            open_ids = sorted({m["milestone_id"] for m in state.meta.values()
                               if m["milestone_id"] and m["event_ticker"] not in state.started})
            live = api.live_status(open_ids)
            state.on_status(live, _now())                    # after the response: not started at least until now
            for t in due:
                fetch_at = _now()
                state.on_trades(t, api.trades(t, int(state.fetched.get(t, fetch_at).timestamp()) - 2))
                state.fetched[t] = fetch_at
            n_fills += state.evaluate(_now())
        except (requests.RequestException, ValueError, KeyError) as exc:
            print(f"{_now():%H:%M:%S} poll failed: {type(exc).__name__}: {str(exc)[:120]}", flush=True)
        polls += 1
        if polls % 30 == 1:
            quoting = sum(1 for m in state.meta.values() if m["event_ticker"] not in state.started)
            print(f"{_now():%H:%M:%S} polls {polls}, markets quoting {quoting}, paper fills {n_fills}, api calls {api.calls}", flush=True)
        if args.max_minutes and time.time() - started > args.max_minutes * 60:
            return 0
        time.sleep(max(0.0, args.poll - (time.time() - tick)))


def _boot(x: np.ndarray, rng) -> list[float]:
    if len(x) == 0:
        return [float("nan")] * 2
    b = x[rng.integers(0, len(x), size=(BOOTSTRAP, len(x)))].sum(axis=1)
    return [round(float(np.percentile(b, 2.5)), 2), round(float(np.percentile(b, 97.5)), 2)]


def true_starts(base: Path) -> dict:
    """ticker -> true start known to the price store (the daily Kalshi pull)."""
    paths = sorted((base / KALSHI_DIR / "markets").glob("*.csv"))
    if not paths:
        return {}
    mk = pd.concat([pd.read_csv(p, dtype=str, keep_default_na=False) for p in paths]).drop_duplicates("ticker", keep="last")
    mk = mk[mk["cutoff_source"] == "true_start"]
    return {t: _ts(c) for t, c in zip(mk["ticker"], mk["cutoff_utc"]) if _ts(c) is not None}


def mid_at(snaps: pd.DataFrame, ts: pd.Timestamp) -> float | None:
    """Kalshi's mid standing at ts from the logged snapshots of one market (two-sided only)."""
    s = snaps[(snaps["ts"] <= ts) & (snaps["bid"] > 0) & (snaps["ask"] > snaps["bid"])]
    return None if s.empty else float((s["bid"].iloc[-1] + s["ask"].iloc[-1]) / 2)


def settle(markets: pd.DataFrame, status: pd.DataFrame, fills: pd.DataFrame, snaps: pd.DataFrame,
           results: dict, true_start: dict) -> pd.DataFrame:
    """One row per (finished market, half-width, maker fee): held, marked, markouts."""
    stops = {r["event_ticker"]: _ts(r["last_not_started_utc"]) - STOP_BEFORE
             for r in status.to_dict("records") if r["last_not_started_utc"]}
    rows = []
    for m in markets.to_dict("records"):
        result, stop = results.get(m["ticker"]), stops.get(m["event_ticker"])
        if result not in ("yes", "no") or stop is None:
            continue
        if m["ticker"] in true_start:
            stop = min(stop, true_start[m["ticker"]] - STOP_BEFORE)
        ms = snaps[snaps["ticker"] == m["ticker"]]
        mark = mid_at(ms, stop)
        mf = fills[(fills["ticker"] == m["ticker"]) & (fills["ts"] <= stop)]
        for h in HALF_WIDTHS:
            g = mf[mf["h"] == h]
            fl = list(zip(g["side"], g["price"], g["contracts"]))
            outs = {k: [mid_at(ms, min(t + pd.Timedelta(minutes=k), stop)) for t in g["ts"]] for k in (1, 5)}
            for fee in (False, True):
                held, vol, pos = pnl(fl, float(result == "yes"), fee)
                rows.append({"ticker": m["ticker"], "h": h, "maker_fee": fee, "held": held,
                             "marked": pnl(fl, mark, fee)[0] if mark is not None else np.nan,
                             "contracts": vol, "end_position": pos,
                             **{f"markout_{k}m": sum(pnl([f], x, False)[0] for f, x in zip(fl, xs) if x is not None)
                                for k, xs in outs.items()}})
    return pd.DataFrame(rows)


def report(args) -> int:
    out, rng = Path(args.out), np.random.default_rng(20261019)
    markets, fills, snaps, status = (_read(out / f) for f in ("markets.csv", "fills.csv", "snapshots.csv", "status.csv"))
    if markets.empty:
        print("no markets logged yet")
        return 0
    snaps = snaps.reindex(columns=SNAP_COLS)
    snaps = snaps.assign(ts=pd.to_datetime(snaps["ts_utc"], utc=True), bid=pd.to_numeric(snaps["best_bid"], errors="coerce"),
                         ask=pd.to_numeric(snaps["best_ask"], errors="coerce"))
    fills = fills.reindex(columns=FILL_COLS)
    fills = fills.assign(ts=pd.to_datetime(fills["ts_utc"], utc=True), h=fills["h"].astype(float),
                         price=fills["price"].astype(float), contracts=fills["contracts"].astype(float))
    status = status.reindex(columns=STATUS_COLS).fillna("")
    api, done = Kalshi(), set(status["event_ticker"])
    results = {t: api.market(t).get("result") for t, ev in zip(markets["ticker"], markets["event_ticker"]) if ev in done}
    d = settle(markets, status, fills, snaps, results, true_starts(BASE))
    rep = {"run_utc": _now().isoformat(timespec="seconds"), "series": SERIES,
           "markets_seen": int(len(markets)), "settled_markets": int(d["ticker"].nunique()) if len(d) else 0,
           "void_or_unsettled": int(sum(r not in ("yes", "no") for r in results.values())), "settings": []}
    for (h, fee), g in (d.groupby(["h", "maker_fee"]) if len(d) else []):
        gm = g.dropna(subset=["marked"])
        rep["settings"].append({
            "h": h, "maker_fee": fee, "markets": int(len(g)), "markets_filled": int((g["contracts"] > 0).sum()),
            "contracts": round(float(g["contracts"].sum())),
            "marked_at_last_mid": round(float(gm["marked"].sum()), 2), "marked_ci95": _boot(gm["marked"].to_numpy(), rng),
            "held_to_settlement": round(float(g["held"].sum()), 2), "held_ci95": _boot(g["held"].to_numpy(), rng),
            "markout_1m": round(float(g["markout_1m"].sum()), 2), "markout_5m": round(float(g["markout_5m"].sum()), 2),
            "cents_per_contract_marked": round(100 * float(gm["marked"].sum() / max(gm["contracts"].sum(), 1)), 2),
            "worst_market_held": round(float(g["held"].min()), 2), "mean_abs_end_position": round(float(g["end_position"].abs().mean()), 1)})
    (out / "report.json").write_text(json.dumps(rep, indent=1, default=str) + "\n", encoding="utf-8")
    print(json.dumps(rep, indent=1, default=str))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--poll", type=float, default=10, help="seconds between polls")
    r.add_argument("--max-age", type=float, default=60, help="seconds a book snapshot stays usable")
    r.add_argument("--max-minutes", type=float, default=0, help="stop after this long (0: run until stopped)")
    r.add_argument("--out", default=str(OUT))
    p = sub.add_parser("report")
    p.add_argument("--out", default=str(OUT))
    args = ap.parse_args()
    return run(args) if args.cmd == "run" else report(args)


if __name__ == "__main__":
    raise SystemExit(main())
