"""Does the underdog's price rise before the match, and can buying it early and selling before
the start make money? (research)

Usage:  python scripts/measure_underdog_drift.py --raw DIR [--out docs/experiments/data/underdog_drift.json]

--raw holds the kalshi_*.jsonl.gz files of the market-raw releases (1-minute best bid/ask and
every pre-start trade per Kalshi market).

1) Pinnacle (the price store, 2026 before the sealed period): the underdog's de-vigged price at
   the open and at the close, by opening price band: the mean move (probability points, 95%
   bootstrap range) and the share of matches where it rose.
2) Kalshi (August to before the sealed period), the trade as a person would place it, per
   underdog market (YES price below 0.50 at entry):
   - entry: buy at the best ask standing at T-12h, T-6h or T-2h before the start (fee included);
   - exit A: sell at the best bid standing one minute before the start (fee included);
   - exit B: a resting sell 4c above the entry price, filled when a later pre-start trade
     bought YES at that price or higher (no taker fee); if never filled, exit A;
   - exit C: hold to the result.
   Return per dollar staked, 95% bootstrap range, by entry price band. Taker fee:
   v5_devig.kalshi_fee on 100-contract orders; maker fee: none (not confirmed for tennis).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from v5_devig import book_lam, devig, kalshi_fee  # noqa: E402
from v5_kalshi_history import rebuild_fixture_map  # noqa: E402
from scripts.simulate_kalshi_making import load_raw  # noqa: E402

SEALED_FROM = pd.Timestamp("2026-10-13", tz="UTC")
ENTRY_HOURS = (12, 6, 2)
TARGET = 0.04
CONTRACTS = 100
BANDS = [0.0, 0.30, 0.40, 0.46, 0.50]
LABELS = ["under 30c", "30-40c", "40-46c", "46-50c"]
BOOTSTRAP = 2000


def boot(x, rng) -> dict:
    x = np.asarray(x, float)
    if len(x) == 0:
        return {"n": 0}
    b = x[rng.integers(0, len(x), size=(BOOTSTRAP, len(x)))].mean(axis=1)
    return {"n": int(len(x)), "mean": round(float(x.mean()), 4),
            "ci95": [round(float(np.percentile(b, 2.5)), 4), round(float(np.percentile(b, 97.5)), 4)]}


def pinnacle_drift(base: Path, rng) -> dict:
    fx = pd.concat([pd.read_csv(p, dtype=str, keep_default_na=False) for p in sorted((base / "market_history" / "fixtures").glob("*.csv"))])
    fx = fx.drop_duplicates("fixture_id")
    early = set(fx[pd.to_datetime(fx["cutoff_utc"], utc=True) < SEALED_FROM]["fixture_id"])
    pts = pd.concat([pd.read_csv(p, dtype={"fixture_id": str}) for p in sorted((base / "market_history" / "price_points").glob("*.csv"))])
    pts = pts[(pts["market_group"] == "moneyline") & (pts["bookmaker"] == "pinnacle") & (pts["close_stale"].astype(str) != "True")
              & pts["fixture_id"].isin(early)]
    w = pts.pivot_table(index="fixture_id", columns="side", values=["open_price", "close_price"], aggfunc="first").dropna()
    w = w[(w > 1).all(axis=1)]
    lam = book_lam("pinnacle")
    o = np.array([devig([a, b], lam)[0] for a, b in zip(w[("open_price", "p1")], w[("open_price", "p2")])])
    c = np.array([devig([a, b], lam)[0] for a, b in zip(w[("close_price", "p1")], w[("close_price", "p2")])])
    dog_open = np.minimum(o, 1 - o)
    dog_close = np.where(o < 0.5, c, 1 - c)
    move = dog_close - dog_open
    band = pd.cut(dog_open, BANDS, labels=LABELS, right=False)
    out = {"all": {**boot(move, rng), "share_rose": round(float((move > 0).mean()), 4)}}
    for b in LABELS:
        m = move[band == b]
        out[b] = {**boot(m, rng), "share_rose": round(float((m > 0).mean()), 4) if len(m) else None}
    return out


def standing(candles, at):
    """(bid, ask) of the last 1-minute candle ending at or before `at`, two-sided only."""
    best = None
    for ts, bid, ask in candles:
        if ts > at:
            break
        if bid and ask and 0 < bid < ask < 1:
            best = (bid, ask)
    return best


def kalshi_trades(base: Path, raw_dir: Path, rng) -> dict:
    raw = load_raw(raw_dir)
    mk = pd.concat([pd.read_csv(p, dtype=str, keep_default_na=False) for p in sorted((base / "market_history" / "kalshi" / "markets").glob("*.csv"))]).drop_duplicates("ticker")
    reg = pd.read_csv(base / "oddspapi_registry" / "fixtures.csv", dtype=str, keep_default_na=False)
    fmap = rebuild_fixture_map(mk, reg)
    fmap = fmap[fmap["match_method"] == "names"].merge(mk[["ticker", "family"]], on="ticker")
    starts = reg.drop_duplicates("fixture_id").set_index("fixture_id")
    fee = lambda p: kalshi_fee(p, CONTRACTS) / CONTRACTS  # noqa: E731
    rows = []
    for r in fmap.itertuples():
        m = raw.get(r.ticker)
        if m is None or m["result"] not in ("yes", "no") or r.fixture_id not in starts.index:
            continue
        f = starts.loc[r.fixture_id]
        start = pd.to_datetime(f["true_start_time_utc"] or f["start_time_utc"], utc=True)
        if start >= SEALED_FROM:
            continue
        stop = start - pd.Timedelta(minutes=1)
        candles = sorted(c for c in m["candles"] if c[0] <= stop)
        trades = sorted(t for t in m["trades"] if t[0] <= stop)
        last = standing(candles, stop)
        won = 1.0 if m["result"] == "yes" else 0.0
        for h in ENTRY_HOURS:
            at = start - pd.Timedelta(hours=h)
            q = standing(candles, at)
            if q is None or last is None or q[1] - q[0] > 0.05 or q[1] >= 0.50:
                continue
            entry = q[1]
            cost = entry + fee(entry)
            exit_a = last[0] - fee(last[0])
            target = round(entry + TARGET, 2)
            hit = any(ts > at and taker == "yes" and x >= target for ts, x, _, taker in trades)
            exit_b = target if hit else exit_a
            rows.append({"ticker": r.ticker, "family": r.family, "hours": h, "entry": entry,
                         "ret_close": exit_a / cost - 1, "ret_target": exit_b / cost - 1, "ret_hold": won / cost - 1,
                         "hit_target": hit, "mid_move": (last[0] + last[1]) / 2 - (q[0] + q[1]) / 2})
    d = pd.DataFrame(rows)
    d["band"] = pd.cut(d["entry"], BANDS, labels=LABELS, right=False)
    out = {"markets": int(d["ticker"].nunique())}
    for h, g in d.groupby("hours"):
        part = {}
        for b, gb in [("all", g)] + [(b, g[g["band"] == b]) for b in LABELS]:
            part[b] = {"n": int(len(gb)), "mid_move": boot(gb["mid_move"], rng), "hit_target_share": round(float(gb["hit_target"].mean()), 4) if len(gb) else None,
                       "sell_at_close": boot(gb["ret_close"], rng), "resting_sell_+4c": boot(gb["ret_target"], rng), "hold_to_result": boot(gb["ret_hold"], rng)}
        part["by_family_resting_sell_+4c"] = {f: boot(gf["ret_target"], rng) for f, gf in g.groupby("family")}
        out[f"T-{h}h"] = part
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", required=True)
    ap.add_argument("--out", default="docs/experiments/data/underdog_drift.json")
    args = ap.parse_args()
    rng = np.random.default_rng(20261019)
    report = {"pinnacle_open_to_close": pinnacle_drift(BASE, rng), "kalshi": kalshi_trades(BASE, Path(args.raw), rng)}
    out = BASE / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
