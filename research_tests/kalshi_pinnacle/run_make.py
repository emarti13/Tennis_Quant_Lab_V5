"""Test M of docs/experiments/2026-10-30-prereg-kalshi-vs-pinnacle.md: quote Kalshi at Pinnacle's
no-vig fair ± h (h = 0.03, 0.05) from each checkpoint to the next, cancelling at the start and
whenever Kalshi's mid is more than 0.10 from the fair. Fill rules, quote rounding, size and
position limit are those of scripts/simulate_kalshi_making.py (imported, unchanged).

python research_tests/kalshi_pinnacle/run_make.py --data <main checkout> --raw <dir of kalshi_*.jsonl.gz>
-> results_make.json, qa_kalshi_pinnacle_make.json
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
from qa import QA  # noqa: E402

SEAL = pd.Timestamp("2026-10-13", tz="UTC")
CPS = [24, 12, 6, 1]
HS = (0.03, 0.05)
MAX_GAP, MIN_CONTRACTS = 0.10, 1000
RNG = np.random.default_rng(20261030)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--raw", required=True)
    a = ap.parse_args()
    sys.path.insert(0, a.data)
    sys.path.insert(0, os.path.join(HERE, "..", "..", "scripts"))     # replay rules from this branch
    import simulate_kalshi_making as sk
    from v5_devig import book_lam, devig
    from v5_market_results import load_fixture_winners

    qa = QA("kalshi_pinnacle_make")
    rd = lambda pat: pd.concat([pd.read_csv(f, dtype=str) for f in sorted(glob.glob(os.path.join(a.data, pat)))])
    fx = rd("market_history/fixtures/*.csv")
    fx = fx[fx.resolution == "ok"].drop_duplicates("fixture_id", keep="last").set_index("fixture_id")
    fx["start"] = pd.to_datetime(fx.cutoff_utc, utc=True, format="ISO8601")
    kp = rd("market_history/kalshi/price_points/*.csv")
    kp = kp[kp.fixture_id.notna() & kp.side.isin(["p1", "p2"])].drop_duplicates("ticker", keep="last")
    pp = rd("market_history/price_points/*.csv")
    pin = pp[(pp.bookmaker == "pinnacle") & (pp.market_group == "moneyline") & pp.side.isin(["p1", "p2"])]
    pin = pin.drop_duplicates(["fixture_id", "side"], keep="last")
    lam = book_lam("pinnacle")

    def nv(row1, row2, col):
        x, y = pd.to_numeric(row1[col], errors="coerce"), pd.to_numeric(row2[col], errors="coerce")
        return devig([x, y], lam)[0] if (np.isfinite(x) and np.isfinite(y) and x > 1 and y > 1) else None

    paths, closes = {}, {}
    for fid, g in pin.groupby("fixture_id"):
        if fid not in fx.index or set(g.side) != {"p1", "p2"} or fx.at[fid, "start"] < SEAL:
            continue
        r1, r2 = g[g.side == "p1"].iloc[0], g[g.side == "p2"].iloc[0]
        start = fx.at[fid, "start"]
        path = [(start - pd.Timedelta(hours=h), nv(r1, r2, f"t{h}h_price")) for h in CPS]
        paths[fid] = [(t, p) for t, p in path if p is not None]
        if str(r1.close_stale) != "True" and str(r2.close_stale) != "True":
            closes[fid] = nv(r1, r2, "close_price")

    raw = sk.load_raw(Path(a.raw))
    qa.count("Kalshi markets in the raw files", len(raw))
    kp = kp[kp.fixture_id.isin(paths.keys()) & kp.ticker.isin(raw.keys())]
    qa.count("sealed Kalshi markets with a Pinnacle path and a trade tape", len(kp))
    w = load_fixture_winners(fx.loc[sorted(set(kp.fixture_id))].reset_index(), base=a.data).drop_duplicates("fixture_id").set_index("fixture_id")

    def replay(market, fair_path, start, h):
        """sk.replay with the pre-registered extras: no quote before the first checkpoint, and
        no quote while Kalshi's mid is more than MAX_GAP from the fair."""
        stop = start - pd.Timedelta(minutes=1)
        candles = [c for c in market["candles"] if c[0] <= stop]
        fills, pos, ci, cancelled = [], 0.0, -1, 0
        for ts, x, count, taker in sorted(t for t in market["trades"] if t[0] <= stop):
            while ci + 1 < len(candles) and candles[ci + 1][0] <= ts:
                ci += 1
            best_bid, best_ask = (candles[ci][1], candles[ci][2]) if ci >= 0 else (None, None)
            fair = sk.fair_at(fair_path, ts)
            if fair is None:
                continue
            mid = sk.mid_fair(best_bid, best_ask)
            if mid is None or abs(mid - fair) > MAX_GAP:
                cancelled += 1
                continue
            bid, ask = sk.quotes(fair, h, best_bid, best_ask)
            got = sk.fill(taker, x, count, bid, ask, best_bid, best_ask, pos)
            if got:
                fills.append(got)
                pos += got[2] if got[0] == "buy" else -got[2]
        return fills, cancelled

    R = {"rules": {"half_widths": HS, "max_gap": MAX_GAP, "size": sk.SIZE, "limit": sk.LIMIT,
                   "maker_fee_rate": sk.MAKER_FEE_RATE, "min_contracts": MIN_CONTRACTS}}
    gaps = []
    for h in HS:
        per_fx = {}
        n_cancel = 0
        held = []
        for _, r in kp.iterrows():
            fid, side = r.fixture_id, r.side
            flip = (lambda p: p) if side == "p1" else (lambda p: 1 - p)
            path = [(t, flip(p)) for t, p in paths[fid]]
            if not path or fid not in closes or closes[fid] is None:
                continue
            fills, nc = replay(raw[r.ticker], path, fx.at[fid, "start"], h)
            n_cancel += nc
            mark = flip(closes[fid])
            prof, vol, pos = sk.pnl(fills, mark, maker_fee=True)
            acc = per_fx.setdefault(fid, [0.0, 0.0])
            acc[0] += prof
            acc[1] += vol
            if fid in w.index and not bool(w.at[fid, "void_for_measurement"]) and vol:
                won = float(w.at[fid, "winner_side"] == side)
                held.append(sk.pnl(fills, won, maker_fee=True)[0])
            if h == HS[0]:
                for t, p in path:
                    c = [cc for cc in raw[r.ticker]["candles"] if cc[0] <= t and cc[1] and cc[2]]
                    if c:
                        gaps.append(abs((c[-1][1] + c[-1][2]) / 2 - p))
        P = np.array([v[0] for v in per_fx.values()])
        V = np.array([v[1] for v in per_fx.values()])
        idx = RNG.integers(0, len(P), (2000, len(P)))
        cpc = (P[idx].sum(1) / np.maximum(V[idx].sum(1), 1)) * 100
        est = P.sum() / max(V.sum(), 1) * 100
        R[f"h={h}"] = {"fixtures": int(len(P)), "fixtures_with_fills": int((V > 0).sum()), "contracts": float(V.sum()),
                       "marked_at_pinnacle_close_usd": round(float(P.sum()), 2),
                       "cents_per_contract": round(float(est), 3),
                       "lo": round(float(np.percentile(cpc, 2.5)), 3), "hi": round(float(np.percentile(cpc, 97.5)), 3),
                       "held_to_result_usd": round(float(np.sum(held)), 2),
                       "trades_skipped_cant_price": int(n_cancel)}
        R[f"h={h}"]["pass"] = bool(V.sum() >= MIN_CONTRACTS and R[f"h={h}"]["lo"] > 0)
    qa.check("median |Kalshi mid - Pinnacle fair| at checkpoints", float(np.median(gaps)) if gaps else np.nan, 0.0, 0.05)
    qa.save(HERE)
    json.dump(R, open(os.path.join(HERE, "results_make.json"), "w"), indent=1)
    print(json.dumps(R, indent=1))


if __name__ == "__main__":
    main()
