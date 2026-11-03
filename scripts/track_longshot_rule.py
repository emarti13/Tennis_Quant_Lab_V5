"""Forward test of registration 2026-11-03 (docs/registrations/2026-11-03-kalshi-longshot-favourite.md):
back the favourite when a Kalshi tennis long shot trades at 20c or less before the start.

Usage:  python scripts/track_longshot_rule.py [--registered 2026-11-03T15:00:00Z]

Paper only: no account, no key, no orders. Reads the server's 5-minute pre-match quotes and
live-score log (market_history/kalshi/live_scores/), settles with Kalshi's public market results,
and rewrites market_history/kalshi/registrations/longshot_2026-11-03.csv and _summary.json.

The rule, exactly as registered:
- Series KXATPMATCH, KXATPCHALLENGERMATCH, KXWTAMATCH; matches whose scheduled start
  (Kalshi milestone start_date) is after the registration time.
- Decision snapshot: the latest 5-minute pre-match snapshot taken between 6 hours and
  60 minutes before the scheduled start, and before the match first appears in the live log.
- Long shot: the market whose YES bid is 0.20 or less in that snapshot, with both of the
  match's markets quoted (bid and ask present) and the long shot's YES spread at most 0.05.
- Bet: 100 contracts on the favourite at the cheaper executable price of (a) NO on the long
  shot at 1 - long shot YES bid and (b) YES on the favourite at its YES ask.
- Fee: Kalshi taker fee rounded up to the cent per order, ceil(0.07 * 100 * P * (1 - P) * 100) / 100
  dollars for the 100-contract order.
- Result: the long shot's Kalshi market result (yes / no); anything else is void and left out.
- Metric: P&L per contract after the fee; pass if the 95% range (resampling matches, seed fixed)
  is wholly above zero once at least 300 matches have settled. The window ends at 300 settled
  matches or on 2027-01-31, whichever comes first.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import requests

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from scripts.log_kalshi_live import read_log  # noqa: E402

LIVE = BASE / "market_history" / "kalshi" / "live_scores"
OUT = BASE / "market_history" / "kalshi" / "registrations"
NAME = "longshot_2026-11-03"
SERIES = ("KXATPMATCH", "KXATPCHALLENGERMATCH", "KXWTAMATCH")
REGISTERED_DEFAULT = "2026-11-03T15:00:00Z"
LONGSHOT_BID, MAX_SPREAD, CONTRACTS = 0.20, 0.05, 100
WINDOW_FROM_H, WINDOW_TO_H = 6.0, 1.0
MIN_MATCHES, WINDOW_END, SEED = 300, "2027-01-31", 20261103
API = "https://api.elections.kalshi.com/trade-api/v2"


def taker_fee_per_contract(price: float) -> float:
    return math.ceil(round(0.07 * CONTRACTS * price * (1 - price) * 100, 6)) / 100 / CONTRACTS


def load_quotes() -> pd.DataFrame:
    files = sorted((LIVE / "prematch").glob("*.csv*"))
    if not files:
        return pd.DataFrame()
    q = pd.concat([pd.read_csv(p) for p in files], ignore_index=True)
    q["polled_utc"] = pd.to_datetime(q["polled_utc"], utc=True, errors="coerce")
    q["start_date"] = pd.to_datetime(q["start_date"], utc=True, errors="coerce")
    for c in ("bid", "ask"):
        q[c] = pd.to_numeric(q[c], errors="coerce")
    return q[q["series"].isin(SERIES)]


def first_live() -> dict[str, pd.Timestamp]:
    out: dict[str, pd.Timestamp] = {}
    for p in sorted(LIVE.glob("*.csv*")):
        try:
            d = read_log(p)
        except (OSError, ValueError):
            continue
        t = pd.to_datetime(d["polled_utc"], utc=True, errors="coerce")
        for ev, tt in d.assign(t=t).groupby("event_ticker")["t"].min().items():
            out[ev] = min(out.get(ev, tt), tt)
    return out


def decisions(q: pd.DataFrame, live: dict, registered: pd.Timestamp) -> pd.DataFrame:
    """One row per qualifying match, from the rule above. Uses nothing after the decision snapshot."""
    rows = []
    if q.empty:
        return pd.DataFrame()
    start = q.groupby("event_ticker")["start_date"].max()                 # filled once the milestone is known
    for ev, g in q.groupby("event_ticker"):
        st = start.get(ev)
        if pd.isna(st) or st <= registered:
            continue
        lo, hi = st - pd.Timedelta(hours=WINDOW_FROM_H), st - pd.Timedelta(hours=WINDOW_TO_H)
        g = g[(g["polled_utc"] >= lo) & (g["polled_utc"] <= hi)]
        if ev in live:
            g = g[g["polled_utc"] < live[ev]]
        if g.empty:
            continue
        snap_t = g["polled_utc"].max()
        s = g[g["polled_utc"] == snap_t]
        if s["ticker"].nunique() != 2 or s[["bid", "ask"]].isna().any().any():
            continue
        ls = s[s["bid"] <= LONGSHOT_BID]
        if len(ls) != 1:
            continue
        ls = ls.iloc[0]
        fav = s[s["ticker"] != ls["ticker"]].iloc[0]
        if ls["ask"] - ls["bid"] > MAX_SPREAD:
            continue
        no_price, fav_price = 1 - ls["bid"], fav["ask"]
        how, price = ("NO on long shot", no_price) if no_price <= fav_price else ("YES on favourite", fav_price)
        rows.append({"event_ticker": ev, "series": ls["series"], "start_date": st.isoformat(), "decided_utc": snap_t.isoformat(),
                     "longshot_ticker": ls["ticker"], "longshot_bid": ls["bid"], "longshot_ask": ls["ask"],
                     "favourite_ticker": fav["ticker"], "favourite_ask": fav["ask"], "bet": how, "price": round(price, 4),
                     "fee_per_contract": taker_fee_per_contract(price)})
    return pd.DataFrame(rows)


def settle(d: pd.DataFrame, prior: pd.DataFrame, get) -> pd.DataFrame:
    """Add the long shot's result (reusing results already known) and P&L per contract."""
    known = dict(zip(prior["longshot_ticker"], prior["result"])) if len(prior) and "result" in prior else {}
    res = []
    for t in d["longshot_ticker"]:
        r = known.get(t)
        if r not in ("yes", "no"):
            try:
                r = (get(f"/markets/{t}").get("market") or {}).get("result") or ""
            except (requests.RequestException, RuntimeError, ValueError):
                r = ""
        res.append(r)
    d = d.assign(result=res)
    won = d["result"] == "no"                                             # the long shot lost
    d["pnl_per_contract"] = np.where(d["result"].isin(["yes", "no"]),
                                     np.where(won, 1 - d["price"], -d["price"]) - d["fee_per_contract"], np.nan)
    return d


def summary(d: pd.DataFrame) -> dict:
    s = d[d["pnl_per_contract"].notna()] if len(d) else d
    out = {"registration": "docs/registrations/2026-11-03-kalshi-longshot-favourite.md", "decisions": int(len(d)),
           "settled": int(len(s)), "min_matches": MIN_MATCHES, "window_end": WINDOW_END}
    if len(s):
        x = s["pnl_per_contract"].to_numpy()
        g = np.random.default_rng(SEED)
        draws = [x[g.integers(0, len(x), len(x))].mean() for _ in range(2000)]
        lo, hi = np.percentile(draws, [2.5, 97.5])
        out.update({"cents_per_contract": round(100 * x.mean(), 3), "range_cents": [round(100 * lo, 3), round(100 * hi, 3)],
                    "favourite_won": round(float((s["result"] == "no").mean()), 4), "mean_price": round(float(s["price"].mean()), 4),
                    "dollars_at_100_contracts": round(float(100 * x.sum()), 2),
                    "status": ("PASS" if lo > 0 else "FAIL") if len(s) >= MIN_MATCHES else "running"})
    else:
        out["status"] = "running"
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--registered", default=REGISTERED_DEFAULT)
    args = ap.parse_args()
    registered = pd.Timestamp(args.registered)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{NAME}.csv"
    prior = pd.read_csv(path) if path.exists() else pd.DataFrame()
    d = decisions(load_quotes(), first_live(), registered)
    if len(d):
        sess = requests.Session()
        d = settle(d, prior, lambda p: sess.get(API + p, timeout=30).json())
        d.to_csv(path, index=False)
    s = summary(d)
    (OUT / f"{NAME}_summary.json").write_text(json.dumps(s, indent=1) + "\n")
    print(json.dumps(s))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
