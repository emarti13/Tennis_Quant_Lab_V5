"""Buy the underdog before the match, sell when its price rises: how often does it fill, and does it pay?

Usage:  python research_tests/inplay_model/run_take_profit.py RAW_DIR REPO_ROOT OUT_JSON

RAW_DIR    the kalshi_*.jsonl.gz files of the market-raw releases (1-minute best bid / ask over each
           market's life, in play included)
REPO_ROOT  a checkout of main (market_history/kalshi/markets/*.csv, oddspapi_registry/fixtures.csv for
           the true start, v5_kalshi_history.rebuild_fixture_map, v5_devig.kalshi_fee)

Written 2026-11-14, before any result (the user asked: "the underdog starts at $0.30, we buy pre-match
and set an ask for $0.50 and it fills, or something similar"). Exploratory: only matches that started
before 2026-11-01 (rolling forward-test amendment); November is kept for registered tests.

  MATCHES   Kalshi match-winner markets of all four families (ATP, WTA, Challenger, WTA 125) tied to an
            OddsPapi fixture with a true start, result yes / no.
  ENTRY     buy YES on the player whose mid one minute before the true start is in an entry band
            (10-20, 20-30, 30-40, 40-50c) at that minute's ask (spread at most 10c), plus the taker fee
            (Kalshi formula, rounded up to the cent on 100 contracts).
  EXIT      a resting sell order (ask) at a target price, placed at the start. It counts as filled at
            the first in-play minute whose closing best BID is at or above the target (conservative: a
            resting ask can fill earlier, on a trade through it). Maker fee on the sale where the series
            charges makers (ATP and WTA match winner: 0.0175 x P x (1 - P) per contract; Challenger and
            WTA 125: none). Unfilled: held to settlement (1 or 0).
  TARGETS   entry + 10c, + 20c, + 30c; 50c; 60c; double the entry price (capped at 95c).
  REPORT    per band and target: matches, fill rate, mean P&L per contract (95% range resampling
            matches), and holding to the end without a target. Also, per band, how often the player's
            in-play bid ever reached entry + 10 / + 20 / + 30c ("gained enough").
  READING   if prices are fair, a take-profit target cannot change the expected P&L, only its spread:
            any profit must come from prices that are wrong somewhere along the path. So each target is
            read against holding, and the many targets x bands are exploratory (no single one is picked).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

RAW, ROOT, OUT = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
sys.path.insert(0, str(ROOT))
from scripts.simulate_kalshi_making import load_raw  # noqa: E402
from v5_devig import kalshi_fee  # noqa: E402
from v5_kalshi_history import rebuild_fixture_map  # noqa: E402

CUTOFF = pd.Timestamp("2026-11-01", tz="UTC")
BANDS = [(0.10, 0.20), (0.20, 0.30), (0.30, 0.40), (0.40, 0.50)]
MAKER_FEE_FAMILIES = {"ATP", "WTA"}
SEED, BOOT = 20261114, 2000


def taker(p: float) -> float:
    return kalshi_fee(p, 100) / 100


def maker(p: float, family: str) -> float:
    return 0.0175 * p * (1 - p) if family in MAKER_FEE_FAMILIES else 0.0


def boot(x, cl) -> list:
    x = np.asarray(x, float)
    if len(x) == 0:
        return [None, None, None]
    codes, uniq = pd.factorize(pd.Series(cl))
    s, c = np.bincount(codes, weights=x), np.bincount(codes).astype(float)
    g = np.random.default_rng(SEED)
    m = [s[i].sum() / c[i].sum() for i in (g.integers(0, len(uniq), len(uniq)) for _ in range(BOOT))]
    lo, hi = np.percentile(m, [2.5, 97.5])
    return [round(100 * float(x.mean()), 2), round(100 * float(lo), 2), round(100 * float(hi), 2)]


def main() -> int:
    raw = load_raw(RAW)
    mk = pd.concat([pd.read_csv(p, dtype=str, keep_default_na=False) for p in sorted((ROOT / "market_history" / "kalshi" / "markets").glob("*.csv"))]).drop_duplicates("ticker")
    reg = pd.read_csv(ROOT / "oddspapi_registry" / "fixtures.csv", dtype=str, keep_default_na=False)
    fmap = rebuild_fixture_map(mk, reg)
    fmap = fmap[fmap["match_method"] == "names"].merge(mk[["ticker", "family"]], on="ticker")
    starts = reg.drop_duplicates("fixture_id").set_index("fixture_id")["true_start_time_utc"]
    rows = []
    for r in fmap.itertuples():
        m = raw.get(r.ticker)
        if m is None or m["result"] not in ("yes", "no") or r.fixture_id not in starts.index or not starts.loc[r.fixture_id]:
            continue
        st = pd.Timestamp(starts.loc[r.fixture_id])
        if st >= CUTOFF:
            continue
        book = [(t, b, a) for t, b, a in sorted(m["candles"]) if b is not None and a is not None and 0 < b < a < 1]
        pre = [x for x in book if x[0] <= st - pd.Timedelta(minutes=1)]
        if not pre or pre[-1][2] - pre[-1][1] > 0.10:
            continue
        _, b0, a0 = pre[-1]
        mid0 = (b0 + a0) / 2
        band = next((f"{int(100 * lo)}-{int(100 * hi)}c" for lo, hi in BANDS if lo <= mid0 < hi), None)
        if band is None:
            continue
        inplay = [(t, b) for t, b, _ in book if t > st]
        if not inplay:
            continue
        max_bid = max(b for _, b in inplay)
        rows.append({"ticker": r.ticker, "family": r.family, "band": band, "entry": a0, "entry_fee": taker(a0),
                     "won": 1 if m["result"] == "yes" else 0, "max_bid": max_bid, "bids": [b for _, b in inplay]})
    d = pd.DataFrame(rows)
    res = {"matches": int(len(d)), "by_family": d["family"].value_counts().to_dict(), "by_band": d["band"].value_counts().to_dict(),
           "start_before": str(CUTOFF.date()), "results": {}}
    R = res["results"]
    for band, g in d.groupby("band"):
        cost = g["entry"] + g["entry_fee"]
        hold = g["won"] - cost
        out = {"matches": int(len(g)), "mean_entry_price": round(float(g["entry"].mean()), 3),
               "won_share": round(float(g["won"].mean()), 3),
               "HOLD to the end: P&L cents per contract [mean, 95% range]": boot(hold, g["ticker"]),
               "gained enough: share whose in-play bid ever reached": {f"+{k}c": round(float((g["max_bid"] >= g["entry"] + k / 100 - 1e-9).mean()), 3) for k in (10, 20, 30)}}
        for name, fn in (("entry+10c", lambda e: e + 0.10), ("entry+20c", lambda e: e + 0.20), ("entry+30c", lambda e: e + 0.30),
                         ("50c", lambda e: 0.50), ("60c", lambda e: 0.60), ("double", lambda e: min(2 * e, 0.95))):
            pnl, fills = [], []
            for x in g.itertuples():
                tgt = round(fn(x.entry), 4)
                if tgt <= x.entry:
                    pnl.append(np.nan)
                    fills.append(np.nan)
                    continue
                hit = any(b >= tgt - 1e-9 for b in x.bids)
                exit_val = tgt - maker(tgt, x.family) if hit else x.won
                pnl.append(exit_val - x.entry - x.entry_fee)
                fills.append(1.0 if hit else 0.0)
            pnl, fills = np.array(pnl), np.array(fills)
            ok = np.isfinite(pnl)
            out[f"SELL at {name}"] = {"n": int(ok.sum()), "fill_rate": round(float(np.nanmean(fills)), 3) if ok.any() else None,
                                      "P&L cents per contract": boot(pnl[ok], g["ticker"].to_numpy()[ok])}
        R[band] = out
    OUT.write_text(json.dumps(res, indent=1, default=str) + "\n")
    print(json.dumps(res, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
