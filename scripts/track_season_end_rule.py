"""Forward test of registration 2026-11-03 (docs/registrations/2026-11-03-season-end-motivation.md):
late in the season, back the opponent of a player ranked 31-90.

Usage:  python scripts/track_season_end_rule.py [--registered 2026-11-03T15:00:00Z] [--ranks PATH]

Paper only: no account, no key, no orders. Reads the server's 5-minute pre-match quotes and live log
(market_history/kalshi/live_scores/), player names from Kalshi's public market data, ranks from the
repo's daily ATP results (v5_results_ready/tennismylife_results.csv on origin/main, refreshed by the
ratings workflow), settles with Kalshi's results, and rewrites
market_history/kalshi/registrations/season_end_2026-11-03.csv and _summary.json.

The rule, exactly as registered:
- Series KXATPMATCH and KXATPCHALLENGERMATCH (ATP only: the ranks come from ATP results, and the
  historical effect was not clear on the WTA).
- Matches whose scheduled start (Kalshi milestone start_date) is after the registration time and
  falls between October 20 and December 31 (any year).
- Decision snapshot: as registration 2026-11-03 long shots: the latest 5-minute pre-match snapshot
  6 hours to 60 minutes before the scheduled start, before the match first appears in the live log;
  both markets quoted with bid and ask.
- Rank: each player's rank at their most recent ATP event in the results file dated on or before the
  decision day (names matched after removing accents, case, hyphens and spaces; a player not found
  means no bet).
- Flag: exactly one player ranked 31-90 (the other's rank known and outside 31-90).
- Bet: 100 contracts on the other player at the cheaper executable price of (a) YES on the other player
  at its ask and (b) NO on the flagged player at 1 - its YES bid; Kalshi taker fee rounded up to the
  cent per order.
- Result: the flagged player's market result; anything but yes / no is void.
- Pass: the 95% range of P&L per contract (2,000 resamples, seed 20261103) wholly above zero with at
  least 300 settled matches; window ends at 300 settled matches or 2027-12-31.
"""
from __future__ import annotations

import argparse
import io
import json
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd
import requests

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from scripts.track_longshot_rule import API, first_live, load_quotes, taker_fee_per_contract  # noqa: E402

OUT = BASE / "market_history" / "kalshi" / "registrations"
NAME = "season_end_2026-11-03"
SERIES = ("KXATPMATCH", "KXATPCHALLENGERMATCH")
REGISTERED_DEFAULT = "2026-11-03T15:00:00Z"
RANK_LO, RANK_HI = 31, 90
WINDOW_FROM_H, WINDOW_TO_H = 6.0, 1.0
MIN_MATCHES, WINDOW_END, SEED = 300, "2027-12-31", 20261103


def norm(s) -> str:
    return re.sub(r"[^a-z]", "", unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower())


def in_season(t: pd.Timestamp) -> bool:
    return (t.month, t.day) >= (10, 20)


def load_ranks(path: str | None) -> pd.DataFrame:
    """Rows (key, date, rank) from the ATP results: one per player per event."""
    if path:
        d = pd.read_csv(path, low_memory=False)
    else:
        subprocess.run(["git", "-C", str(BASE), "fetch", "-q", "origin", "main"], check=False, timeout=300)
        txt = subprocess.run(["git", "-C", str(BASE), "show", "origin/main:v5_results_ready/tennismylife_results.csv"],
                             capture_output=True, text=True, timeout=300).stdout
        d = pd.read_csv(io.StringIO(txt), low_memory=False)
    d["date"] = pd.to_datetime(d["tourney_date"].astype(str).str[:8], format="%Y%m%d", errors="coerce")
    parts = [pd.DataFrame({"key": d[f"{s}_name"].map(norm), "date": d["date"], "rank": pd.to_numeric(d[f"{s}_rank"], errors="coerce")})
             for s in ("winner", "loser")]
    r = pd.concat(parts, ignore_index=True).dropna()
    return r.sort_values("date")


def rank_on(ranks: pd.DataFrame, key: str, day: pd.Timestamp) -> float | None:
    x = ranks[(ranks["key"] == key) & (ranks["date"] <= day)]
    return None if x.empty else float(x["rank"].iloc[-1])


def decisions(q: pd.DataFrame, live: dict, registered: pd.Timestamp, names: dict, ranks: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    rows, skipped = [], {"no_name": 0, "no_rank": 0, "not_flagged": 0}
    if q.empty:
        return pd.DataFrame(), skipped
    q = q[q["series"].isin(SERIES)]
    start = q.groupby("event_ticker")["start_date"].max()
    for ev, g in q.groupby("event_ticker"):
        st = start.get(ev)
        if pd.isna(st) or st <= registered or not in_season(st):
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
        r = []
        for m in s.itertuples():
            nm = names.get(m.ticker)
            if not nm:
                skipped["no_name"] += 1
                break
            rk = rank_on(ranks, norm(nm), snap_t.normalize().tz_localize(None))
            if rk is None:
                skipped["no_rank"] += 1
                break
            r.append((m, nm, rk))
        if len(r) != 2:
            continue
        flagged = [x for x in r if RANK_LO <= x[2] <= RANK_HI]
        if len(flagged) != 1:
            skipped["not_flagged"] += 1
            continue
        f, o = flagged[0], [x for x in r if x is not flagged[0]][0]
        yes_other, no_flagged = o[0].ask, 1 - f[0].bid
        how, price = ("YES on opponent", yes_other) if yes_other <= no_flagged else ("NO on flagged", no_flagged)
        rows.append({"event_ticker": ev, "series": f[0].series, "start_date": st.isoformat(), "decided_utc": snap_t.isoformat(),
                     "flagged_ticker": f[0].ticker, "flagged_name": f[1], "flagged_rank": f[2],
                     "opponent_ticker": o[0].ticker, "opponent_name": o[1], "opponent_rank": o[2],
                     "bet": how, "price": round(float(price), 4), "fee_per_contract": taker_fee_per_contract(float(price))})
    return pd.DataFrame(rows), skipped


def settle(d: pd.DataFrame, prior: pd.DataFrame, get) -> pd.DataFrame:
    known = dict(zip(prior["flagged_ticker"], prior["result"])) if len(prior) and "result" in prior else {}
    res = []
    for t in d["flagged_ticker"]:
        r = known.get(t)
        if r not in ("yes", "no"):
            try:
                r = (get(f"/markets/{t}").get("market") or {}).get("result") or ""
            except (requests.RequestException, RuntimeError, ValueError):
                r = ""
        res.append(r)
    d = d.assign(result=res)
    won = d["result"] == "no"                                             # the flagged player lost
    d["pnl_per_contract"] = np.where(d["result"].isin(["yes", "no"]),
                                     np.where(won, 1 - d["price"], -d["price"]) - d["fee_per_contract"], np.nan)
    return d


def summary(d: pd.DataFrame, skipped: dict) -> dict:
    s = d[d["pnl_per_contract"].notna()] if len(d) else d
    out = {"registration": "docs/registrations/2026-11-03-season-end-motivation.md", "decisions": int(len(d)), "settled": int(len(s)),
           "min_matches": MIN_MATCHES, "window_end": WINDOW_END, "skipped": skipped}
    if len(s):
        x = s["pnl_per_contract"].to_numpy()
        g = np.random.default_rng(SEED)
        lo, hi = np.percentile([x[g.integers(0, len(x), len(x))].mean() for _ in range(2000)], [2.5, 97.5])
        out.update({"cents_per_contract": round(100 * float(x.mean()), 3), "range_cents": [round(100 * lo, 3), round(100 * hi, 3)],
                    "favourite_won": round(float((s["result"] == "no").mean()), 4), "mean_price": round(float(s["price"].mean()), 4),
                    "dollars_at_100_contracts": round(float(100 * x.sum()), 2),
                    "status": ("PASS" if lo > 0 else "FAIL") if len(s) >= MIN_MATCHES else "running"})
    else:
        out["status"] = "running"
    return out


def names_for(tickers, prior: pd.DataFrame, get) -> dict:
    """Player name per Kalshi market (yes_sub_title), reusing names already stored."""
    names = {}
    if len(prior):
        names.update(dict(zip(prior["flagged_ticker"], prior["flagged_name"])))
        names.update(dict(zip(prior["opponent_ticker"], prior["opponent_name"])))
    cache = OUT / f"{NAME}_names.json"
    if cache.exists():
        names.update(json.loads(cache.read_text()))
    for t in tickers:
        if t in names:
            continue
        try:
            m = get(f"/markets/{t}").get("market") or {}
            nm = m.get("yes_sub_title") or re.sub(r"\s+wins$", "", m.get("title") or "")
            if nm:
                names[t] = nm
        except (requests.RequestException, RuntimeError, ValueError):
            pass
    cache.write_text(json.dumps(names, indent=0, sort_keys=True))
    return names


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--registered", default=REGISTERED_DEFAULT)
    ap.add_argument("--ranks", default=None)
    args = ap.parse_args()
    registered = pd.Timestamp(args.registered)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{NAME}.csv"
    prior = pd.read_csv(path) if path.exists() else pd.DataFrame()
    q = load_quotes()
    sess = requests.Session()
    get = lambda p: sess.get(API + p, timeout=30).json()  # noqa: E731
    skipped = {}
    d = pd.DataFrame()
    if not q.empty:
        q = q[q["series"].isin(SERIES)]
        st = q.groupby("event_ticker")["start_date"].max()
        live_events = st[(st > registered) & st.map(lambda t: not pd.isna(t) and in_season(t))].index
        cand = q[q["event_ticker"].isin(live_events)]
        names = names_for(sorted(cand["ticker"].unique()), prior, get)
        d, skipped = decisions(cand, first_live(), registered, names, load_ranks(args.ranks))
        if len(d):
            d = settle(d, prior, get)
            d.to_csv(path, index=False)
    s = summary(d, skipped)
    (OUT / f"{NAME}_summary.json").write_text(json.dumps(s, indent=1) + "\n")
    print(json.dumps(s))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
