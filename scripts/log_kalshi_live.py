"""Log Kalshi tennis prices together with the live score, during matches (research data).

Usage:  python scripts/log_kalshi_live.py [--minutes 0 (forever)] [--interval 30]

Kalshi's history gives prices but not the score; an in-play model needs both at the same
moment. Every interval, for each open Kalshi tennis match (ATP, Challenger, WTA) whose match
milestone has started and not finished, this records the score from Kalshi's public live data
(sets, games in the current set, set scores so far, server, advantage, status) next to both
players' best bid and ask. Public endpoints only: no account, no key, no orders.

Output (append-only): market_history/kalshi/live_scores/YYYY-MM-DD.csv (UTC day), and
market_history/kalshi/live_scores/state.json (milestones found, matches finished).
A match is watched from 10 minutes before its milestone start until Kalshi reports it ended.
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
from scripts.paper_trade_kalshi import Kalshi  # noqa: E402

SERIES = ("KXATPMATCH", "KXATPCHALLENGERMATCH", "KXWTAMATCH")
OUT_DIR = BASE / "market_history" / "kalshi" / "live_scores"
WATCH_BEFORE_MIN = 10
FINISHED = {"closed", "ended", "finished", "complete", "completed", "cancelled", "canceled"}
COLS = ["polled_utc", "series", "event_ticker", "milestone_id", "status", "match_status", "widget_status",
        "server", "advantage", "sets_1", "sets_2", "games_1", "games_2", "round_scores_1", "round_scores_2",
        "competitor_1", "competitor_2", "ticker_1", "bid_1", "ask_1", "ticker_2", "bid_2", "ask_2"]


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def live_details(api: Kalshi, milestone: dict) -> dict:
    return api.get(f"/live_data/{milestone['type']}/milestone/{milestone['id']}").get("live_data", {}).get("details", {})


def load_state() -> dict:
    p = OUT_DIR / "state.json"
    return json.loads(p.read_text()) if p.exists() else {"events": {}}


def save_state(state: dict) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "state.json").write_text(json.dumps(state, indent=1, sort_keys=True) + "\n")


def row_for(series: str, event: str, ms: dict, d: dict, markets: list[dict], now: pd.Timestamp) -> dict:
    """One log row: the score from live data, each competitor's market quote (matched by the
    market's tennis_competitor id; falls back to the market order)."""
    c1, c2 = d.get("competitor1_id"), d.get("competitor2_id")
    by_comp = {(m.get("custom_strike") or {}).get("tennis_competitor"): m for m in markets}
    m1, m2 = by_comp.get(c1), by_comp.get(c2)
    if m1 is None or m2 is None:
        m1, m2 = (markets + [None, None])[:2]
    scores = lambda k: json.dumps([s.get("score") for s in (d.get(k) or [])])  # noqa: E731
    return {"polled_utc": now.isoformat(), "series": series, "event_ticker": event, "milestone_id": ms.get("id"),
            "status": d.get("status"), "match_status": d.get("match_status"), "widget_status": d.get("widget_status"),
            "server": d.get("server"), "advantage": d.get("advantage"),
            "sets_1": d.get("competitor1_overall_score"), "sets_2": d.get("competitor2_overall_score"),
            "games_1": d.get("competitor1_current_round_score"), "games_2": d.get("competitor2_current_round_score"),
            "round_scores_1": scores("competitor1_round_scores"), "round_scores_2": scores("competitor2_round_scores"),
            "competitor_1": c1, "competitor_2": c2,
            "ticker_1": m1 and m1.get("ticker"), "bid_1": m1 and _f(m1.get("yes_bid_dollars")), "ask_1": m1 and _f(m1.get("yes_ask_dollars")),
            "ticker_2": m2 and m2.get("ticker"), "bid_2": m2 and _f(m2.get("yes_bid_dollars")), "ask_2": m2 and _f(m2.get("yes_ask_dollars"))}


def poll_once(api: Kalshi, state: dict, now: pd.Timestamp) -> dict:
    rows, failed, watched = [], 0, 0
    for series in SERIES:
        try:
            markets = api.open_markets(series)
        except RuntimeError:
            failed += 1
            continue
        by_event: dict[str, list] = {}
        for m in markets:
            by_event.setdefault(m["event_ticker"], []).append(m)
        for event, ms_list in by_event.items():
            e = state["events"].setdefault(event, {"milestone": None, "finished": False})
            if e["finished"]:
                continue
            try:
                if e["milestone"] is None:
                    e["milestone"] = api.milestone(event)
                ms = e["milestone"]
                if not ms or not ms.get("start_date"):
                    continue
                if now < pd.Timestamp(ms["start_date"]) - pd.Timedelta(minutes=WATCH_BEFORE_MIN):
                    continue
                d = live_details(api, ms)
            except (RuntimeError, requests.HTTPError):
                failed += 1
                continue
            status = str(d.get("status") or "").lower()
            if status == "not_started" and not d.get("match_status"):
                continue
            watched += 1
            rows.append(row_for(series, event, ms, d, ms_list, now))
            if status in FINISHED or str(d.get("match_status") or "").lower() in FINISHED:
                e["finished"] = True
    if rows:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        path = OUT_DIR / f"{now:%Y-%m-%d}.csv"
        pd.DataFrame(rows, columns=COLS).to_csv(path, mode="a", header=not path.exists(), index=False)
    return {"rows": len(rows), "live_matches": watched, "failures": failed, "api_calls": api.calls}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=0, help="stop after this long (0 = run forever)")
    ap.add_argument("--interval", type=float, default=30)
    args = ap.parse_args()
    api, state = Kalshi(), load_state()
    end = time.time() + args.minutes * 60 if args.minutes else None
    while True:
        started = time.time()
        now = pd.Timestamp.now(tz="UTC").floor("s")
        try:
            info = poll_once(api, state, now)
            save_state(state)
            print(f"{now.isoformat()} {json.dumps(info)}", flush=True)
        except Exception as exc:                               # keep logging; the next poll retries
            print(f"{now.isoformat()} poll failed: {exc}", flush=True)
        if end is not None and time.time() >= end:
            return 0
        time.sleep(max(0.0, args.interval - (time.time() - started)))


if __name__ == "__main__":
    raise SystemExit(main())
