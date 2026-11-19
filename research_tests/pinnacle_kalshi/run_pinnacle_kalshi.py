"""Pinnacle as information, Kalshi as the venue: when Pinnacle's fair price is away from Kalshi's
executable price, does buying on Kalshi make money after Kalshi's fee?

Usage:  python research_tests/pinnacle_kalshi/run_pinnacle_kalshi.py KALSHI_RAW_PKL KMARKETS_DIR PRICE_POINTS_DIR OUT_JSON

KALSHI_RAW_PKL    {ticker: {"candles": [(unix_ts, yes_bid, yes_ask) per minute]}}, Aug-Oct 2026
KMARKETS_DIR      market_history/kalshi/markets (ticker, event, fixture_id, side p1/p2, result, true start)
PRICE_POINTS_DIR  market_history/price_points (Pinnacle moneyline price standing at t12h, t6h, t1h and
                  the close, each with the time of the quote)

Pre-registered 2026-11-03, before any result was seen (data before 2026-11-01, open for exploration;
a finding becomes a registered forward test). CLAUDE.md: Pinnacle is information, Kalshi is execution.

  FAIR      Pinnacle's de-vigged chance for each player (multiplicative), at a checkpoint.
  WHEN      the checkpoint's decision time: start - 12 h, - 6 h, - 1 h; for the close, one minute
            after Pinnacle's last pre-start quote. Pinnacle's quote must be dated at or before it.
  KALSHI    the latest minute candle at or before the decision time, at most 30 minutes old, with
            a YES spread of at most 0.05, in each of the match's two markets.
  BET       the best of the four Kalshi options (YES or NO in either player's market) by edge =
            Pinnacle fair chance of that outcome - price paid - taker fee 0.07 * P * (1 - P); bet
            it if the edge is at least the threshold; one bet per match; hold to settlement.
  PRIMARY   checkpoint t1h, threshold 2 points: mean P&L per contract after the fee, 95% range
            resampling matches.
  SECONDARY other checkpoints (t12h, t6h, close) and thresholds (0, 4 points); by series; does
            Kalshi's mid move toward Pinnacle's fair before the start (slope of the move on the gap)?
  CHECKS    outcomes drawn from Kalshi's mid (Kalshi is right): the rule must lose about the cost;
            outcomes drawn from Pinnacle's fair (Pinnacle is right): the rule must earn about its
            mean edge. The real result shows which of the two the outcomes side with.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research_kit import provenance  # noqa: E402
from research_kit.core import boot_mean, devig  # noqa: E402

SEED = 20261103
FEE = 0.07
CHECKPOINTS = {"t12h": 12.0, "t6h": 6.0, "t1h": 1.0, "close": None}


def fee(p):
    p = np.asarray(p, float)
    return FEE * p * (1 - p)


def load(raw_pkl, kmarkets, points_dir):
    raw = pd.read_pickle(raw_pkl)
    km = pd.concat([pd.read_csv(p) for p in sorted(Path(kmarkets).glob("*.csv"))], ignore_index=True).drop_duplicates("ticker", keep="last")
    km = km[km["fixture_id"].notna() & km["side"].isin(["p1", "p2"]) & km["result"].isin(["yes", "no"])]
    km["start"] = pd.to_datetime(km["cutoff_utc"], utc=True, errors="coerce")
    pts = pd.concat([pd.read_csv(p, low_memory=False) for p in sorted(Path(points_dir).glob("*.csv"))], ignore_index=True)
    pts = pts[(pts["bookmaker"] == "pinnacle") & (pts["market_group"] == "moneyline") & pts["side"].isin(["p1", "p2"])]
    pts = pts[pts["fixture_id"].isin(set(km["fixture_id"]))].drop_duplicates(["fixture_id", "side"], keep="last")
    return raw, km, pts


def candles(raw, t):
    c = (raw.get(t) or {}).get("candles") or []
    if not c:
        return None
    d = pd.DataFrame(c, columns=["t", "bid", "ask"])
    d["t"] = pd.to_datetime(d["t"], unit="s", utc=True)
    return d[(d["bid"] > 0) & (d["ask"] < 1) & (d["ask"] > d["bid"]) & (d["ask"] - d["bid"] <= 0.05)].sort_values("t")


def quote_at(c, t):
    if c is None:
        return None
    x = c[(c["t"] <= t) & (c["t"] >= t - pd.Timedelta(minutes=30))]
    return None if x.empty else x.iloc[-1]


def build(raw, km, pts):
    rows, skipped = [], {"no_two_markets": 0, "no_pinnacle_both": 0}
    pin = {(r.fixture_id, r.side): r for r in pts.itertuples()}
    for ev, g in km.groupby("event_ticker"):
        if len(g) != 2 or set(g["side"]) != {"p1", "p2"}:
            skipped["no_two_markets"] += 1
            continue
        m1, m2 = g[g["side"] == "p1"].iloc[0], g[g["side"] == "p2"].iloc[0]
        fx, start = m1["fixture_id"], m1["start"]
        if (fx, "p1") not in pin or (fx, "p2") not in pin or pd.isna(start):
            skipped["no_pinnacle_both"] += 1
            continue
        c1, c2 = candles(raw, m1["ticker"]), candles(raw, m2["ticker"])
        last1 = None if c1 is None else c1[c1["t"] < start]
        y1 = 1 if m1["result"] == "yes" else 0
        for cp, hours in CHECKPOINTS.items():
            a, b = pin[(fx, "p1")], pin[(fx, "p2")]
            pa, pb = getattr(a, f"{cp}_price"), getattr(b, f"{cp}_price")
            ta, tb = getattr(a, f"{cp}_utc"), getattr(b, f"{cp}_utc")
            if pd.isna(pa) or pd.isna(pb) or pd.isna(ta) or pd.isna(tb):
                continue
            qt = max(pd.Timestamp(ta), pd.Timestamp(tb))
            when = qt + pd.Timedelta(minutes=1) if hours is None else start - pd.Timedelta(hours=hours)
            if qt > when or when >= start:
                continue
            k1, k2 = quote_at(c1, when), quote_at(c2, when)
            if k1 is None or k2 is None:
                continue
            fair1 = float(devig(pa, pb))
            # four options: (price paid, fair chance it wins, wins?)
            opts = [(k1["ask"], fair1, y1), (1 - k1["bid"], 1 - fair1, 1 - y1),
                    (k2["ask"], 1 - fair1, 1 - y1), (1 - k2["bid"], fair1, y1)]
            edges = [f - p - FEE * p * (1 - p) for p, f, _ in opts]
            best = int(np.argmax(edges))
            price, fair, won = opts[best]
            mid1 = (k1["bid"] + k1["ask"]) / 2
            end_mid = None
            if last1 is not None and len(last1):
                end_mid = float((last1.iloc[-1]["bid"] + last1.iloc[-1]["ask"]) / 2)
            rows.append({"event": ev, "series": m1["series"], "checkpoint": cp, "edge": edges[best], "price": price,
                         "fair": fair, "won": won, "fair1": fair1, "kalshi_mid1": mid1, "kalshi_end_mid1": end_mid,
                         "hours_before": (start - when).total_seconds() / 3600})
    return pd.DataFrame(rows), skipped


def pnl(d, won=None):
    w = d["won"].to_numpy() if won is None else won
    p = d["price"].to_numpy()
    return np.where(w == 1, 1 - p, -p) - fee(p)


def cell(d):
    if len(d) == 0:
        return {"n": 0}
    m, lo, hi = boot_mean(pnl(d), seed=SEED)
    return {"n": int(len(d)), "cents_per_contract": round(100 * m, 2), "range": [round(100 * lo, 2), round(100 * hi, 2)],
            "mean_edge_cents": round(100 * float(d["edge"].mean()), 2), "mean_price": round(float(d["price"].mean()), 3)}


def main():
    raw_pkl, kmarkets, points_dir, out_json = sys.argv[1:5]
    raw, km, pts = load(raw_pkl, kmarkets, points_dir)
    d, skipped = build(raw, km, pts)
    res = {"manifest": provenance.manifest({"kalshi_raw": raw_pkl, "kalshi_markets": kmarkets, "price_points": points_dir}, {"bootstrap": SEED},
                                          " ".join(["python"] + sys.argv)),
           "matches_with_any_checkpoint": int(d["event"].nunique()) if len(d) else 0, "skipped": skipped, "results": {}}
    R = res["results"]
    for cp in CHECKPOINTS:
        x = d[d["checkpoint"] == cp]
        R[f"{cp}: matches compared"] = int(len(x))
        if len(x):
            gap = x["fair1"] - x["kalshi_mid1"]
            R[f"{cp}: mean |Pinnacle fair - Kalshi mid| (pts)"] = round(100 * float(gap.abs().mean()), 2)
            mv = (x["kalshi_end_mid1"] - x["kalshi_mid1"]).to_numpy(float)
            ok = np.isfinite(mv)
            if ok.sum() > 10:
                slope = float(np.polyfit(gap.to_numpy()[ok], mv[ok], 1)[0])
                R[f"{cp}: Kalshi mid moves toward Pinnacle by this share of the gap before the start"] = round(slope, 3)
        for thr in (0.0, 0.02, 0.04):
            key = f"{cp}, edge >= {int(100 * thr)} pts"
            if cp == "t1h" and thr == 0.02:
                key = "PRIMARY " + key
            R[key] = cell(x[x["edge"] >= thr])
    prim = d[(d["checkpoint"] == "t1h") & (d["edge"] >= 0.02)]
    for s in sorted(prim["series"].unique()) if len(prim) else []:
        R[f"PRIMARY by series: {s}"] = cell(prim[prim["series"] == s])
    if len(prim):
        g = np.random.default_rng(SEED)
        # Kalshi's own chance for the bet outcome: the mid of that market (YES) or 1 - mid (NO)
        k_chance = np.clip(prim["price"].to_numpy() - 0.005, 0.001, 0.999)          # about the mid: half of a 1c spread below the price paid
        y_k = (g.random(len(prim)) < k_chance).astype(int)
        y_p = (g.random(len(prim)) < prim["fair"].to_numpy()).astype(int)
        mk, mp = boot_mean(pnl(prim, y_k), seed=SEED), boot_mean(pnl(prim, y_p), seed=SEED)
        cost = float(np.mean(0.005 + fee(prim["price"])))
        res["checks"] = {
            "kalshi_is_right": {"pass": bool(mk[1] <= -cost <= mk[2]), "found_cents": [round(100 * v, 2) for v in mk], "expected_cents": round(-100 * cost, 2)},
            "pinnacle_is_right": {"pass": bool(mp[1] <= float(prim["edge"].mean()) <= mp[2]), "found_cents": [round(100 * v, 2) for v in mp],
                                  "expected_cents": round(100 * float(prim["edge"].mean()), 2)}}
        res["checks_passed"] = all(c["pass"] for c in res["checks"].values())
    Path(out_json).write_text(json.dumps(res, indent=1, default=str) + "\n")
    print(json.dumps({k: v for k, v in res.items() if k != "manifest"}, indent=1, default=str))


if __name__ == "__main__":
    main()
