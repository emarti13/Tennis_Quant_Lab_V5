"""Forward test of registration 2026-11-21 (docs/registrations/2026-11-21-orderbook-wall.md): back the side a
dominant resting order ("wall") is holding on a Kalshi tennis market, before the start.

Usage:  python scripts/track_wall_rule.py [--registered 2026-11-22T00:00:00Z]

Paper only: no account, no key, no orders. Reads the server's order-book log
(market_history/kalshi/live_scores/orderbook/: the 10 price levels nearest the best price on each side,
YES bids and NO bids, every 5 minutes, a row only when the book changed), each match's scheduled start
from Kalshi's public milestones, settles with Kalshi's results, and rewrites
market_history/kalshi/registrations/wall_2026-11-21.csv and _summary.json.

The rule, exactly as registered (adapted from the r/algobetting post the user shared on 2026-11-05):
- Markets: every logged Kalshi tennis market: match winners (ATP, WTA, Challenger, WTA 125), ATP game
  spreads, ATP and WTA total games, ATP and WTA set winners.
- Book rows from the registration time until 60 minutes before the match's scheduled start (milestone
  start_date of the match-winner event with the same match code).
- Wall on one side (YES bids, or NO bids), over the 10 logged levels of that side: the largest level is
  at least 55% of the side's size and at least 3 times the next largest; the side's size is at least
  twice the other side's; the wall is worth at least $600 (contracts x its price).
- The wall's side: a YES-bid wall wants YES; a NO-bid wall wants NO.
- Decision: the first such row per market. Buy the wall's side at its ask (YES ask = 1 - best NO bid;
  NO ask = 1 - best YES bid) only if that ask is at most 3c above the wall's price; Kalshi taker fee
  rounded up to the cent on 100 contracts; 100 contracts. One decision per market.
- Close: the last book row before the scheduled start; p_close of the side = mid of the two best prices.
- PRIMARY metric: CLV per contract = p_close(side) - price - fee. Pass: the 95% range (2,000 resamples of
  matches, seed 20261121) wholly above zero with at least 300 bets. Ends at 300 or 2027-06-30.
- Reported: P&L at settlement (the market's result: yes / no; anything else void), by market type, the
  share of bets whose close is better than the price.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import requests

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from scripts.log_kalshi_live import read_log  # noqa: E402
from scripts.track_longshot_rule import API, taker_fee_per_contract  # noqa: E402

BOOKS = BASE / "market_history" / "kalshi" / "live_scores" / "orderbook"
OUT = BASE / "market_history" / "kalshi" / "registrations"
NAME = "wall_2026-11-21"
REGISTERED_DEFAULT = "2026-11-22T00:00:00Z"
WINNER_SERIES = {"KXATPMATCH": "KXATPMATCH", "KXATPGSPREAD": "KXATPMATCH", "KXATPGTOTAL": "KXATPMATCH", "KXATPSETWINNER": "KXATPMATCH",
                 "KXWTAMATCH": "KXWTAMATCH", "KXWTAGSPREAD": "KXWTAMATCH", "KXWTAGTOTAL": "KXWTAMATCH", "KXWTASETWINNER": "KXWTAMATCH",
                 "KXATPCHALLENGERMATCH": "KXATPCHALLENGERMATCH", "KXWTACHALLENGERMATCH": "KXWTACHALLENGERMATCH"}
SHARE, RATIO, SIDE_RATIO, MIN_DOLLARS, MAX_ABOVE, LEAD_MIN = 0.55, 3.0, 2.0, 600.0, 0.03, 60
MIN_BETS, WINDOW_END, SEED = 300, "2027-06-30", 20261121


def levels(s) -> list[tuple[float, float]]:
    out = []
    for part in str(s).split(";") if isinstance(s, str) and s else []:
        p, _, q = part.partition(":")
        try:
            out.append((float(p), float(q)))
        except ValueError:
            continue
    return out


def wall(row) -> dict | None:
    """The wall on this book row, if any: side ('yes' or 'no'), price, contracts."""
    y, n = levels(row.yes_levels), levels(row.no_levels)
    size = {"yes": sum(q for _, q in y), "no": sum(q for _, q in n)}
    for side, lv, other in (("yes", y, "no"), ("no", n, "yes")):
        if len(lv) < 2 or size[side] <= 0:
            continue
        top = sorted(lv, key=lambda x: -x[1])
        (p1, q1), (_, q2) = top[0], top[1]
        if q1 >= SHARE * size[side] and q1 >= RATIO * q2 and size[side] >= SIDE_RATIO * size[other] and q1 * p1 >= MIN_DOLLARS:
            return {"side": side, "wall_price": p1, "wall_contracts": q1}
    return None


def mid_yes(row) -> float | None:
    b, nb = row.best_yes_bid, row.best_no_bid
    if pd.isna(b) or pd.isna(nb):
        return None
    return (float(b) + (1 - float(nb))) / 2


def decide(g: pd.DataFrame, start: pd.Timestamp, registered: pd.Timestamp) -> dict | None:
    g = g.sort_values("t")
    pre = g[(g["t"] >= registered) & (g["t"] <= start - pd.Timedelta(minutes=LEAD_MIN))]
    for r in pre.itertuples():
        w = wall(r)
        if w is None:
            continue
        if w["side"] == "yes":
            if pd.isna(r.best_no_bid):
                return None
            ask = round(1 - float(r.best_no_bid), 4)
        else:
            if pd.isna(r.best_yes_bid):
                return None
            ask = round(1 - float(r.best_yes_bid), 4)
        if ask > w["wall_price"] + MAX_ABOVE + 1e-9 or not 0 < ask < 1:
            return None                                                  # first wall only; too far from it: no bet
        before = g[g["t"] < start]
        close = before.iloc[-1] if len(before) else None
        mc = None if close is None else mid_yes(close)
        p_close = None if mc is None else (mc if w["side"] == "yes" else 1 - mc)
        fee = taker_fee_per_contract(ask)
        return {"decided_utc": r.t.isoformat(), **w, "price": ask, "fee_per_contract": fee,
                "p_close": None if p_close is None else round(p_close, 4),
                "clv_per_contract": None if p_close is None else round(p_close - ask - fee, 4)}
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--registered", default=REGISTERED_DEFAULT)
    args = ap.parse_args()
    registered = pd.Timestamp(args.registered)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{NAME}.csv"
    prior = pd.read_csv(path) if path.exists() else pd.DataFrame()
    done = set(prior["ticker"]) if len(prior) else set()
    frames = []
    for p in sorted(BOOKS.glob("*.csv*")):
        try:
            frames.append(read_log(p))
        except (OSError, ValueError):
            continue
    rows = [] if prior.empty else prior.to_dict("records")
    sess = requests.Session()
    get = lambda p, params=None: sess.get(API + p, params=params, timeout=30).json()  # noqa: E731
    cache_p = OUT / f"{NAME}_starts.json"
    starts = json.loads(cache_p.read_text()) if cache_p.exists() else {}
    if frames:
        d = pd.concat(frames, ignore_index=True)
        d = d[d["series"].isin(list(WINNER_SERIES))].copy()
        d["t"] = pd.to_datetime(d["polled_utc"], utc=True, errors="coerce")
        d = d.dropna(subset=["t"])
        now = pd.Timestamp.now(tz="UTC")
        for (series, ticker), g in d.groupby(["series", "ticker"]):
            if ticker in done:
                continue
            ev = f"{WINNER_SERIES[series]}-{g['match_suffix'].iloc[0]}"
            if ev not in starts:
                try:
                    ms = get("/milestones", {"related_event_ticker": ev, "limit": 5}).get("milestones", [])
                    ms = [x for x in ms if ev in (x.get("primary_event_tickers") or [])] or ms
                    starts[ev] = ms[0].get("start_date") if ms else None
                except (requests.RequestException, ValueError):
                    continue
            if not starts.get(ev):
                continue
            st = pd.Timestamp(starts[ev])
            if st <= registered or st > now:
                continue                                                  # wait until the match has started
            dec = decide(g, st, registered)
            if dec:
                rows.append({"ticker": ticker, "series": series, "match_event": ev, "start_utc": st.isoformat(), **dec})
    cache_p.write_text(json.dumps(starts, indent=0, sort_keys=True))
    out = pd.DataFrame(rows)
    if len(out):
        res = []
        known = dict(zip(prior["ticker"], prior["result"])) if len(prior) and "result" in prior else {}
        for t in out["ticker"]:
            r = known.get(t)
            if r not in ("yes", "no"):
                try:
                    r = (get(f"/markets/{t}").get("market") or {}).get("result") or ""
                except (requests.RequestException, ValueError):
                    r = ""
            res.append(r)
        out["result"] = res
        ok = out["result"].isin(["yes", "no"])
        won = np.where(out["side"] == "yes", out["result"] == "yes", out["result"] == "no")
        out["pnl_per_contract"] = np.where(ok, np.where(won, 1 - out["price"], -out["price"]) - out["fee_per_contract"], np.nan)
        out.to_csv(path, index=False)
    s = {"registration": "docs/registrations/2026-11-21-orderbook-wall.md", "bets": int(len(out)), "min_matches": MIN_BETS,
         "window_end": WINDOW_END, "status": "running", "metric": "CLV cents per contract against the Kalshi close"}
    c = out.dropna(subset=["clv_per_contract"]) if len(out) else out
    s["settled"] = int(len(c))
    if len(c):
        cl = c["match_event"].to_numpy()
        codes, uniq = pd.factorize(pd.Series(cl))
        x = c["clv_per_contract"].to_numpy(float)
        sums, cnts = np.bincount(codes, weights=x), np.bincount(codes).astype(float)
        g = np.random.default_rng(SEED)
        bs = [sums[i].sum() / cnts[i].sum() for i in (g.integers(0, len(uniq), len(uniq)) for _ in range(2000))]
        lo, hi = np.percentile(bs, [2.5, 97.5])
        pnl = c["pnl_per_contract"].dropna()
        s.update({"cents_per_contract": round(100 * float(x.mean()), 3), "range_cents": [round(100 * lo, 3), round(100 * hi, 3)],
                  "beat_the_close": round(float((c["p_close"] > c["price"]).mean()), 3),
                  "pnl_cents_per_contract": round(100 * float(pnl.mean()), 3) if len(pnl) else None,
                  "by_series": {k: int(v) for k, v in c["series"].value_counts().items()},
                  "status": ("PASS" if lo > 0 else "FAIL") if len(c) >= MIN_BETS else "running"})
        s["note"] = f"beat the close {s['beat_the_close']}; P&L {s['pnl_cents_per_contract']}c"
    (OUT / f"{NAME}_summary.json").write_text(json.dumps(s, indent=1, default=str) + "\n")
    print(json.dumps(s, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
