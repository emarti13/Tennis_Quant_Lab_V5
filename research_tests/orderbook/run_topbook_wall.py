"""Order-book walls on Kalshi tennis, first look: does the price move toward the side a large resting
order is holding? (Exploratory; top of book only.)

Usage:  python research_tests/orderbook/run_topbook_wall.py OUT_JSON CACHE_JSON DEPTH_CSV_GZ [DEPTH_CSV_GZ ...]

DEPTH files: the server paper trader's market_history/kalshi/paper/depth_*.csv.gz (ticker, polled_utc,
best_bid, bid_depth, best_ask, ask_depth; contracts at the best YES bid and the best YES ask). Only data
before 2026-11-01 is used (rolling forward-test amendment): Oct 20 (00:40-14:38 UTC) and Oct 31,
Challenger match-winner markets only. Start times (milestone start_date) and results come from Kalshi's
public API and are cached in CACHE_JSON.

Pre-registered 2026-11-06, before any of these outcomes was looked at. Idea (r/algobetting post, user
2026-11-05): a large resting order offering one side is someone holding the other; the market follows it.

  SUPPORT   for player A at a poll: contracts bid for YES on A at the best bid, plus contracts offered
            for YES on B at the best ask (selling YES on B is backing A). Same for B.
  DECISION  per match: the latest poll 6 h to 60 min before the scheduled start in which both markets
            have a bid and an ask (polls of the two markets within 3 minutes of each other).
  WALL      support on one side >= 3 x the other and >= 300 contracts. The wall side W is the side
            with the larger support.
  CLOSE     the last such poll before the scheduled start. p(W) = mid(W) / (mid(W) + mid(other)).
  METRICS   move = p_close(W) - p_decision(W) (points); CLV = p_close(W) - cost - taker fee, cost = the
            cheaper of YES on W at the ask and NO on the other at 1 - its bid (fee rounded up to the cent
            on 100 contracts); realised P&L on Kalshi results. 95% ranges resampling matches, and the
            minimum detectable move (2.8 x SE).
            Continuous: correlation of log(support_A / support_B) with the move toward A, all matches.
  CHECKS    the same metrics with the wall side drawn at random (should be ~0 move); counts of matches.
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

API = "https://api.elections.kalshi.com/trade-api/v2"
SEED = 20261106
CUTOFF = pd.Timestamp("2026-11-01T00:00:00Z")
LEAD_FROM_H, LEAD_TO_H, PAIR_TOL_S = 6.0, 1.0, 180
RATIO, MIN_SUPPORT = 3.0, 300


def fee(p: float) -> float:
    return math.ceil(round(0.07 * 100 * p * (1 - p) * 100, 6)) / 100 / 100


def boot(x, seed=SEED, n=2000):
    x = np.asarray(x, float)
    if len(x) == 0:
        return [None, None, None]
    g = np.random.default_rng(seed)
    m = [x[g.integers(0, len(x), len(x))].mean() for _ in range(n)]
    lo, hi = np.percentile(m, [2.5, 97.5])
    return [round(float(x.mean()), 4), round(float(lo), 4), round(float(hi), 4)]


def api_info(events: list[str], tickers: list[str], cache_path: Path) -> dict:
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {"start": {}, "result": {}}
    s = requests.Session()
    s.headers["User-Agent"] = "research-script/1.0"
    for ev in events:
        if ev in cache["start"]:
            continue
        r = s.get(API + "/milestones", params={"related_event_ticker": ev, "limit": 5}, timeout=30).json().get("milestones", [])
        r = [m for m in r if ev in (m.get("primary_event_tickers") or [])] or r
        cache["start"][ev] = r[0].get("start_date") if r else None
        time.sleep(0.25)
    for t in tickers:
        if cache["result"].get(t) in ("yes", "no"):
            continue
        m = s.get(API + f"/markets/{t}", timeout=30).json().get("market") or {}
        cache["result"][t] = m.get("result") or ""
        time.sleep(0.25)
    cache_path.write_text(json.dumps(cache, indent=0, sort_keys=True))
    return cache


def paired_polls(g: pd.DataFrame, ta: str, tb: str) -> pd.DataFrame:
    """One row per poll of A, joined to B's nearest poll within PAIR_TOL_S, both quoted."""
    a = g[g["ticker"] == ta].sort_values("t")
    b = g[g["ticker"] == tb].sort_values("t")
    if a.empty or b.empty:
        return pd.DataFrame()
    x = pd.merge_asof(a, b, on="t", direction="nearest", tolerance=pd.Timedelta(seconds=PAIR_TOL_S), suffixes=("_a", "_b"))
    ok = x[["best_bid_a", "best_ask_a", "best_bid_b", "best_ask_b"]].notna().all(axis=1)
    ok &= (x["best_bid_a"] > 0) & (x["best_bid_b"] > 0) & (x["best_ask_a"] < 1) & (x["best_ask_b"] < 1)
    return x[ok].reset_index(drop=True)


def main() -> int:
    out_json, cache_json, files = sys.argv[1], Path(sys.argv[2]), sys.argv[3:]
    d = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
    d["t"] = pd.to_datetime(d["polled_utc"], utc=True, errors="coerce")
    d = d[d["t"] < CUTOFF].dropna(subset=["t"])
    for c in ("best_bid", "bid_depth", "best_ask", "ask_depth"):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d["event"] = d["ticker"].str.rsplit("-", n=1).str[0]
    pairs = d.groupby("event")["ticker"].unique()
    pairs = pairs[pairs.map(len) == 2]
    info = api_info(sorted(pairs.index), sorted({t for v in pairs for t in v}), cache_json)
    rows, counts = [], {"events_with_two_markets": int(len(pairs)), "no_start": 0, "no_decision_poll": 0}
    for ev, (ta, tb) in pairs.items():
        st = info["start"].get(ev)
        if not st:
            counts["no_start"] += 1
            continue
        st = pd.Timestamp(st)
        x = paired_polls(d[d["event"] == ev], ta, tb)
        x = x[x["t"] < st]
        dec = x[(x["t"] >= st - pd.Timedelta(hours=LEAD_FROM_H)) & (x["t"] <= st - pd.Timedelta(hours=LEAD_TO_H))]
        if dec.empty:
            counts["no_decision_poll"] += 1
            continue
        r, c = dec.iloc[-1], x.iloc[-1]
        sa = r["bid_depth_a"] + r["ask_depth_b"]
        sb = r["bid_depth_b"] + r["ask_depth_a"]
        mid = lambda row, s: (row[f"best_bid_{s}"] + row[f"best_ask_{s}"]) / 2  # noqa: E731
        pa_dec = mid(r, "a") / (mid(r, "a") + mid(r, "b"))
        pa_close = mid(c, "a") / (mid(c, "a") + mid(c, "b"))
        res_a = info["result"].get(ta, "")
        rows.append({"event": ev, "support_a": sa, "support_b": sb, "pa_dec": pa_dec, "pa_close": pa_close,
                     "cost_a": min(r["best_ask_a"], 1 - r["best_bid_b"]), "cost_b": min(r["best_ask_b"], 1 - r["best_bid_a"]),
                     "res_a": res_a, "lead_min": (st - r["t"]).total_seconds() / 60, "close_lead_min": (st - c["t"]).total_seconds() / 60})
    m = pd.DataFrame(rows)
    res = {"counts": counts, "matches": int(len(m)), "results": {}}
    R = res["results"]
    if len(m):
        m["move_a"] = m["pa_close"] - m["pa_dec"]
        lr = np.log((m["support_a"] + 1) / (m["support_b"] + 1))
        R["corr(log support ratio A/B, move toward A)"] = round(float(np.corrcoef(lr, m["move_a"])[0, 1]), 4) if len(m) > 2 else None
        R["median minutes before start: decision / close"] = [round(float(m["lead_min"].median()), 1), round(float(m["close_lead_min"].median()), 1)]

        def wall_stats(m: pd.DataFrame, side_a: np.ndarray):
            mv = np.where(side_a, m["move_a"], -m["move_a"])
            cost = np.where(side_a, m["cost_a"], m["cost_b"])
            pc = np.where(side_a, m["pa_close"], 1 - m["pa_close"])
            fees = np.array([fee(float(p)) for p in cost])
            clv = pc - cost - fees
            won = np.where(side_a, m["res_a"] == "yes", m["res_a"] == "no")
            settled = m["res_a"].isin(["yes", "no"]).to_numpy()
            pnl = np.where(won, 1 - cost, -cost) - fees
            b = boot(mv)
            se = (b[2] - b[1]) / 3.92 if b[0] is not None else None
            return {"n": int(len(mv)), "move_pts": [None if v is None else round(100 * v, 2) for v in b],
                    "mde_move_pts": None if se is None else round(100 * 2.8 * se, 2),
                    "clv_cents": [None if v is None else round(100 * v, 2) for v in boot(clv)],
                    "clv_hit": round(float((mv > 0).mean()), 3) if len(mv) else None,
                    "pnl_cents": [None if v is None else round(100 * v, 2) for v in boot(pnl[settled])], "settled": int(settled.sum())}
        big = np.maximum(m["support_a"], m["support_b"])
        small = np.minimum(m["support_a"], m["support_b"])
        wall = ((big >= RATIO * small) & (big >= MIN_SUPPORT)).to_numpy()
        side_a = (m["support_a"] >= m["support_b"]).to_numpy()
        mw = m[wall].reset_index(drop=True)
        R["PRIMARY wall side (support >= 3x and >= 300 contracts)"] = wall_stats(mw, side_a[wall]) if len(mw) else {"n": 0}
        g = np.random.default_rng(SEED)
        R["CHECK random side, same matches"] = wall_stats(mw, g.random(len(mw)) < 0.5) if len(mw) else {"n": 0}
        R["all matches, larger-support side (no thresholds)"] = wall_stats(m, side_a)
    Path(out_json).write_text(json.dumps(res, indent=1, default=str) + "\n")
    print(json.dumps(res, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
