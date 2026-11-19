"""Forward test of registration 2026-11-19 (docs/registrations/2026-11-19-inplay-maker.md): an in-play market
maker on Kalshi tennis, quoting around the score-based fair price, filled only by real trades.

Usage:  python scripts/track_inplay_maker.py [--registered 2026-11-20T00:00:00Z]

Paper only: no account, no key, no orders. For every finished match in the live log (score and both
players' best bid / ask every 10 s) it fetches the match's public trades from Kalshi, replays the quotes
below, settles with Kalshi's results, and rewrites market_history/kalshi/registrations/
inplay_maker_2026-11-19.csv (one row per market) and _summary.json.

The rule, exactly as registered (market-following maker; the user's points of 2026-11-19: the price moves with
every point and often reverses within a game, and faster traders may see points before this feed):
- Series: Challenger (KXATPCHALLENGERMATCH) and WTA 125 (KXWTACHALLENGERMATCH) match winners are scored
  (no maker fee). ATP and WTA match winners are replayed the same way and reported with the maker fee
  0.0175 x P x (1 - P) per contract, not scored.
- Quotes, on each of the two markets, at an in-play row of the live log (every 10 s) when ALL hold:
  both markets quoted; the market's spread is at least 3c; the point score is the same as at the
  previous row (no quoting on the row where a new point appears); and the next point is calm: the
  score-based fair price of the match (research_kit.inplay, serve probabilities from the last pre-match
  quote as in scripts/track_inplay_rules.py) moves by at most 4 points between winning and losing it.
  Then: a bid at the market's best bid + 1c and an ask at its best ask - 1c (first in the queue on
  both sides), 10 contracts each, only while the market's net position stays within +-50 contracts.
  Quotes live from the row's time until the next row (at most 30 s).
- Fills: a public trade in that interval with the taker SELLING YES (taker_side "no") at a YES price at or
  below our bid fills our bid; with the taker BUYING YES at or above our ask fills our ask; at our price,
  up to the trade's size and our remaining size.
- Result: positions held to settlement (yes = 1, no = 0; anything else void).
- Metric: P&L per match in dollars and cents per contract filled; scored on Challenger and WTA 125.
- Pass: the 95% range of the mean P&L per match (2,000 resamples of matches, seed 20261119) wholly above
  zero with at least 300 scored matches with a fill; ends at 300 or 2027-06-30.
- Reported: fills; the mark-out (mid 60 s after each fill minus the fill price, from our side); ATP / WTA
  with the maker fee; FEED LAG: for each new point seen in the log (with the same score at the two rows
  before it), the share of the price move (two rows before -> one row after) that happened between the
  two rows BEFORE the point appears in this feed, i.e. the market moving before our score feed shows it.
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
from research_kit import inplay as ip  # noqa: E402
from scripts.log_kalshi_live import read_log  # noqa: E402
from scripts.track_inplay_rules import (  # noqa: E402
    IN_PLAY, LEVEL, SLAMS, milestone_meta, p1_devig, quotes_ok, state,
)
from scripts.track_longshot_rule import API  # noqa: E402

LIVE = BASE / "market_history" / "kalshi" / "live_scores"
OUT = BASE / "market_history" / "kalshi" / "registrations"
NAME = "inplay_maker_2026-11-19"
MIN_SPREAD, MAX_SWING = 0.03, 0.04
REGISTERED_DEFAULT = "2026-11-20T00:00:00Z"
TOUR = {"KXATPMATCH": "ATP", "KXWTAMATCH": "WTA", "KXATPCHALLENGERMATCH": "CH", "KXWTACHALLENGERMATCH": "WTA"}
SCORED = ("KXATPCHALLENGERMATCH", "KXWTACHALLENGERMATCH")
MAKER_FEE = {"KXATPMATCH": 0.0175, "KXWTAMATCH": 0.0175}
HALF_WIDTH, SIZE, MAX_POS, MAX_GAP_S, MARKOUT_S = 0.02, 10.0, 50.0, 30.0, 60.0
MIN_MATCHES, WINDOW_END, SEED = 300, "2027-06-30", 20261119


def quotes_for(best_bid: float, best_ask: float, pos: float) -> tuple[float | None, float | None]:
    """Our bid and ask on one market: 1c inside the market on both sides (None = not quoting that side)."""
    if best_ask - best_bid < MIN_SPREAD - 1e-9:
        return None, None
    bid, ask = round(best_bid + 0.01, 2), round(best_ask - 0.01, 2)
    return (bid if pos + SIZE <= MAX_POS else None), (ask if pos - SIZE >= -MAX_POS else None)


def next_point_swing(pa, pb, st, bo, ftb) -> float:
    """How far the fair match price moves between winning and losing the next point."""
    s1, s2, g1, g2, p1, p2, c1_srv = st
    tb = g1 == 6 and g2 == 6

    def after(win1: bool):
        q1, q2 = (p1 + 1, p2) if win1 else (p1, p2 + 1)
        if tb:
            target = ftb if (s1 == s2 == (bo + 1) // 2 - 1) else 7
            if (q1 >= target and q1 - q2 >= 2) or (q2 >= target and q2 - q1 >= 2):
                return ip.p_match(pa, pb, (s1 + (q1 > q2), s2 + (q2 > q1)), (0, 0), (0, 0), not c1_srv, bo, ftb)
            k = p1 + p2                                                 # index of the point just played
            same = ip._tb_server_is_first(k) == ip._tb_server_is_first(k + 1)
            srv_next = c1_srv if same else not c1_srv
            return ip.p_match(pa, pb, (s1, s2), (g1, g2), (q1, q2), srv_next, bo, ftb)
        sv, rv = (q1, q2) if c1_srv else (q2, q1)
        if (sv >= 4 and sv - rv >= 2) or (rv >= 4 and rv - sv >= 2):        # game over: next game, other server
            w1 = (sv > rv) == c1_srv
            ng1, ng2 = g1 + w1, g2 + (not w1)
            if (ng1 >= 6 and ng1 - ng2 >= 2) or ng1 == 7 or (ng2 >= 6 and ng2 - ng1 >= 2) or ng2 == 7:
                return ip.p_match(pa, pb, (s1 + (ng1 > ng2), s2 + (ng2 > ng1)), (0, 0), (0, 0), not c1_srv, bo, ftb)
            return ip.p_match(pa, pb, (s1, s2), (ng1, ng2), (0, 0), not c1_srv, bo, ftb)
        if sv >= 3 and rv >= 3 and sv == rv:
            q1 = q2 = 3
        return ip.p_match(pa, pb, (s1, s2), (g1, g2), (q1, q2), c1_srv, bo, ftb)
    return abs(after(True) - after(False))


def fills_in(trades: pd.DataFrame, t0, t1, bid, ask, left_bid: float, left_ask: float) -> list[tuple]:
    """(side, price, contracts, time) of our fills from public trades in [t0, t1)."""
    out = []
    w = trades[(trades["t"] >= t0) & (trades["t"] < t1)]
    for tr in w.itertuples():
        if bid is not None and left_bid > 0 and tr.taker_side == "no" and tr.yes_price <= bid + 1e-9:
            q = min(tr.count, left_bid)
            left_bid -= q
            out.append(("buy", bid, q, tr.t))
        elif ask is not None and left_ask > 0 and tr.taker_side == "yes" and tr.yes_price >= ask - 1e-9:
            q = min(tr.count, left_ask)
            left_ask -= q
            out.append(("sell", ask, q, tr.t))
    return out


def trades_for(ticker: str, t_from: pd.Timestamp, t_to: pd.Timestamp, get) -> pd.DataFrame:
    rows, cursor = [], None
    for _ in range(50):
        params = {"ticker": ticker, "limit": 1000, "min_ts": int(t_from.timestamp()), "max_ts": int(t_to.timestamp())}
        if cursor:
            params["cursor"] = cursor
        page = get("/markets/trades", params)
        for tr in page.get("trades", []):
            rows.append({"t": pd.Timestamp(tr["created_time"]), "yes_price": float(tr["yes_price_dollars"]),
                         "count": float(tr["count_fp"]), "taker_side": tr["taker_side"]})
        cursor = page.get("cursor")
        if not cursor:
            break
    d = pd.DataFrame(rows, columns=["t", "yes_price", "count", "taker_side"])
    return d.sort_values("t").reset_index(drop=True)


def replay(ev: str, m: pd.DataFrame, meta: dict, trades: dict) -> list[dict] | None:
    """One row per market of the event, or None if the match cannot be priced."""
    series = str(m["series"].iloc[0])
    tour = TOUR[series]
    m = m.sort_values("t")
    c1 = str(m["competitor_1"].dropna().iloc[0])
    live = m[m["match_status"].isin(IN_PLAY)]
    pre = [r for r in m[m["t"] < live["t"].iloc[0]].itertuples() if quotes_ok(r)]
    if not pre:
        return None
    bo = int(meta.get("best_of") or 3)
    ftb = 10 if any(s in str(meta.get("tournament_name", "")).lower() for s in SLAMS) else 7
    try:
        pa, pb = ip.solve_serve(p1_devig(pre[-1]), LEVEL[tour], best_of=bo, final_set_tb=ftb)
    except ValueError:
        return None
    rows = list(live.itertuples())
    tick = {1: str(rows[0].ticker_1), 2: str(rows[0].ticker_2)}
    pos, fills = {1: 0.0, 2: 0.0}, {1: [], 2: []}
    mids = {1: [], 2: []}
    lag_pre, lag_all = [], []
    prev_pts = None
    for i, r in enumerate(rows):
        if quotes_ok(r):
            for k in (1, 2):
                mids[k].append((r.t, (float(getattr(r, f"bid_{k}")) + float(getattr(r, f"ask_{k}"))) / 2))
        st = state(r, c1)
        pts_now = None if st is None else st[:6]
        new_point = prev_pts is not None and pts_now is not None and pts_now != prev_pts
        # feed lag: did the price move BEFORE this feed showed the point? The move between the two rows
        # before the point appears (in the direction of the whole move, two rows before -> one row after),
        # as a share of the whole move. Score and quote are read together, so a feed as fast as the market
        # shows ~0 here; a slower feed shows the market moving first.
        if new_point and 1 < i < len(rows) - 1 and all(quotes_ok(q) for q in (rows[i - 2], rows[i - 1], r, rows[i + 1])) \
                and state(rows[i - 2], c1) is not None and state(rows[i - 2], c1)[:6] == state(rows[i - 1], c1)[:6]:
            m0, m1, m3 = p1_devig(rows[i - 2]), p1_devig(rows[i - 1]), p1_devig(rows[i + 1])
            if abs(m3 - m0) >= 0.01:
                lag_pre.append(np.sign(m3 - m0) * (m1 - m0))
                lag_all.append(abs(m3 - m0))
        calm_row = pts_now is not None and prev_pts is not None and pts_now == prev_pts
        prev_pts = pts_now if pts_now is not None else prev_pts
        if i + 1 >= len(rows) or not calm_row or not quotes_ok(r):
            continue
        t0, t1 = r.t, rows[i + 1].t
        if (t1 - t0).total_seconds() > MAX_GAP_S:
            continue
        if next_point_swing(pa, pb, st, bo, ftb) > MAX_SWING:
            continue
        for k in (1, 2):
            bid, ask = quotes_for(float(getattr(r, f"bid_{k}")), float(getattr(r, f"ask_{k}")), pos[k])
            if bid is None and ask is None:
                continue
            for side, price, q, t in fills_in(trades[tick[k]], t0, t1, bid, ask, SIZE, SIZE):
                pos[k] += q if side == "buy" else -q
                fills[k].append((side, price, q, t))
    out = []
    for k in (1, 2):
        mk = pd.DataFrame(mids[k], columns=["t", "mid"])
        mo, mo_q = [], 0.0
        for side, price, q, t in fills[k]:
            later = mk[mk["t"] >= t + pd.Timedelta(seconds=MARKOUT_S)]
            if len(later):
                mv = float(later["mid"].iloc[0]) - price
                mo.append((mv if side == "buy" else -mv) * q)
                mo_q += q
        contracts = sum(q for _, _, q, _ in fills[k])
        out.append({"event_ticker": ev, "series": series, "ticker": tick[k], "scored": series in SCORED,
                    "fills": len(fills[k]), "contracts": round(contracts, 2), "end_position": round(pos[k], 2),
                    "cash": round(sum((-price * q if side == "buy" else price * q) for side, price, q, _ in fills[k]), 4),
                    "maker_fee": round(sum(MAKER_FEE.get(series, 0.0) * q * price * (1 - price) for _, price, q, _ in fills[k]), 4),
                    "markout_60s": round(sum(mo), 4), "markout_contracts": round(mo_q, 2),
                    "lag_moved_before": round(float(np.sum(lag_pre)), 4) if k == 1 else 0.0,
                    "lag_moved_total": round(float(np.sum(lag_all)), 4) if k == 1 else 0.0,
                    "lag_points": len(lag_all) if k == 1 else 0})
    return out


def settle(rows: list[dict], get) -> list[dict]:
    for r in rows:
        if r.get("result") in ("yes", "no"):
            continue
        try:
            r["result"] = (get(f"/markets/{r['ticker']}").get("market") or {}).get("result") or ""
        except (requests.RequestException, RuntimeError, ValueError):
            r["result"] = ""
        if r["result"] in ("yes", "no"):
            value = 1.0 if r["result"] == "yes" else 0.0
            r["pnl"] = round(r["cash"] + r["end_position"] * value - r["maker_fee"], 4)
    return rows


def summary(d: pd.DataFrame) -> dict:
    out = {"registration": "docs/registrations/2026-11-19-inplay-maker.md", "min_matches": MIN_MATCHES, "window_end": WINDOW_END, "status": "running"}
    if d.empty or "pnl" not in d:
        out.update({"settled": 0, "note": "no settled matches yet"})
        return out
    s = d.dropna(subset=["pnl"])
    per = s.groupby(["event_ticker", "scored"]).agg(pnl=("pnl", "sum"), contracts=("contracts", "sum"), markout=("markout_60s", "sum")).reset_index()
    sc = per[per["scored"].astype(bool) & (per["contracts"] > 0)]
    out["settled"] = int(len(sc))
    if len(sc):
        x = sc["pnl"].to_numpy(float)
        g = np.random.default_rng(SEED)
        lo, hi = np.percentile([x[g.integers(0, len(x), len(x))].mean() for _ in range(2000)], [2.5, 97.5])
        out.update({"dollars_per_match": round(float(x.mean()), 3), "range_dollars_per_match": [round(float(lo), 3), round(float(hi), 3)],
                    "cents_per_contract": round(100 * float(x.sum() / sc["contracts"].sum()), 3),
                    "range_cents": [round(100 * float(lo * len(x) / sc["contracts"].sum()), 3), round(100 * float(hi * len(x) / sc["contracts"].sum()), 3)],
                    "markout_60s_cents_per_contract": round(100 * float(sc["markout"].sum() / max(s.loc[s["scored"].astype(bool), "markout_contracts"].sum(), 1e-9)), 3),
                    "status": ("PASS" if lo > 0 else "FAIL") if len(sc) >= MIN_MATCHES else "running"})
    rep = per[~per["scored"].astype(bool) & (per["contracts"] > 0)]
    if len(rep):
        out["reported, not scored (ATP / WTA, with maker fee)"] = {"matches": int(len(rep)), "dollars_per_match": round(float(rep["pnl"].mean()), 3),
                                                                  "cents_per_contract": round(100 * float(rep["pnl"].sum() / rep["contracts"].sum()), 3)}
    if "lag_moved_total" in s and s["lag_moved_total"].sum() > 0:
        out["feed lag: share of the price move made before this feed shows the point"] = round(float(s["lag_moved_before"].sum() / s["lag_moved_total"].sum()), 3)
        out["feed lag points"] = int(s["lag_points"].sum())
    out["note"] = f"{out['settled']} scored matches" + (f"; {out['cents_per_contract']}c per contract" if "cents_per_contract" in out else "")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--registered", default=REGISTERED_DEFAULT)
    args = ap.parse_args()
    registered = pd.Timestamp(args.registered)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{NAME}.csv"
    prior = pd.read_csv(path).to_dict("records") if path.exists() else []
    done = {r["event_ticker"] for r in prior}
    frames = []
    for p in sorted(LIVE.glob("*.csv*")):
        try:
            frames.append(read_log(p))
        except (OSError, ValueError):
            continue
    sess = requests.Session()
    get = lambda p, params=None: sess.get(API + p, params=params, timeout=30).json()  # noqa: E731
    rows = list(prior)
    if frames:
        d = pd.concat(frames, ignore_index=True)
        d = d[d["series"].isin(list(TOUR))].copy()
        d["t"] = pd.to_datetime(d["polled_utc"], utc=True, errors="coerce")
        d = d.dropna(subset=["t"])
        d["server"] = d["server"].astype(object).where(d["server"].notna(), None)
        finished = d.groupby("event_ticker")["match_status"].agg(lambda s: (s == "ended").any())
        evs = [e for e in finished[finished].index if e not in done]
        meta = milestone_meta(evs, OUT / "inplay_2026-11-18_milestones.json", get)
        for ev in evs:
            m = d[d["event_ticker"] == ev]
            live = m[m["match_status"].isin(IN_PLAY)]
            if live.empty or live["t"].iloc[0] <= registered or m["competitor_1"].dropna().empty:
                continue
            t_from, t_to = live["t"].iloc[0] - pd.Timedelta(minutes=1), live["t"].iloc[-1] + pd.Timedelta(minutes=1)
            try:
                tr = {str(t): trades_for(str(t), t_from, t_to, get) for t in (live["ticker_1"].iloc[0], live["ticker_2"].iloc[0])}
            except (requests.RequestException, ValueError, KeyError):
                continue
            res = replay(ev, m, meta.get(ev, {}), tr)
            if res:
                rows += res
    rows = settle(rows, get)
    out = pd.DataFrame(rows)
    if len(out):
        out.to_csv(path, index=False)
    s = summary(out)
    (OUT / f"{NAME}_summary.json").write_text(json.dumps(s, indent=1, default=str) + "\n")
    print(json.dumps(s, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
