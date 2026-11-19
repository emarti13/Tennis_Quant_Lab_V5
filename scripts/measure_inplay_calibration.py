"""Are Kalshi's prices right during matches? (research, asked by the user 2026-10-20)

Usage:  python scripts/measure_inplay_calibration.py --raw DIR [--out docs/experiments/data/inplay_calibration.json]

--raw holds the kalshi_*.jsonl.gz files of the market-raw releases (1-minute best bid/ask for
the whole life of each market, in play included).

For every Kalshi tennis market whose match started (true start from the OddsPapi registry)
before the sealed period (2026-10-13), the mid price is sampled every 5 minutes from the start
until the price first reaches 2c or 98c (the match is effectively over), plus one sample one
minute before the start. Per price band: the average price, how often that player actually won
(95% range, resampled by match so one long match does not count as many), and the return per
dollar of buying at the ask there and holding (taker fee included).

Two cases the user described:
- "flip": the player was the underdog one minute before the start (mid under 45c) and is now
  the favourite in play (mid 55c or more), e.g. after winning the first set;
- "favourite in trouble": the pre-match favourite (55c+) now under 45c in play.
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
from v5_devig import kalshi_fee  # noqa: E402
from v5_kalshi_history import rebuild_fixture_map  # noqa: E402
from scripts.simulate_kalshi_making import load_raw  # noqa: E402

SEALED_FROM = pd.Timestamp("2026-10-13", tz="UTC")
STEP_MIN = 5
BANDS = [0.02, 0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 0.98]
BOOTSTRAP = 1000


def samples(raw: dict, base: Path) -> pd.DataFrame:
    mk = pd.concat([pd.read_csv(p, dtype=str, keep_default_na=False) for p in sorted((base / "market_history" / "kalshi" / "markets").glob("*.csv"))]).drop_duplicates("ticker")
    reg = pd.read_csv(base / "oddspapi_registry" / "fixtures.csv", dtype=str, keep_default_na=False)
    fmap = rebuild_fixture_map(mk, reg)
    fmap = fmap[fmap["match_method"] == "names"].merge(mk[["ticker", "family"]], on="ticker")
    starts = reg.drop_duplicates("fixture_id").set_index("fixture_id")
    rows = []
    for r in fmap.itertuples():
        m = raw.get(r.ticker)
        if m is None or m["result"] not in ("yes", "no") or r.fixture_id not in starts.index:
            continue
        ts = starts.loc[r.fixture_id, "true_start_time_utc"]
        if not ts:
            continue
        start = pd.Timestamp(ts)
        if start >= SEALED_FROM:
            continue
        won = 1 if m["result"] == "yes" else 0
        book = [(t, b, a) for t, b, a in sorted(m["candles"]) if b is not None and a is not None and 0 < b < a < 1 and a - b <= 0.10]
        pre = [x for x in book if x[0] <= start - pd.Timedelta(minutes=1)]
        if not pre:
            continue
        pre_mid = (pre[-1][1] + pre[-1][2]) / 2
        rows.append({"ticker": r.ticker, "family": r.family, "minute": -1, "mid": pre_mid, "ask": pre[-1][2], "won": won, "pre_mid": pre_mid})
        nxt = start
        for t, b, a in book:
            if t <= start:
                continue
            mid = (b + a) / 2
            if mid <= 0.02 or mid >= 0.98:
                break
            if t >= nxt:
                rows.append({"ticker": r.ticker, "family": r.family, "minute": int((t - start).total_seconds() // 60),
                             "mid": mid, "ask": a, "won": won, "pre_mid": pre_mid})
                nxt = t + pd.Timedelta(minutes=STEP_MIN)
    d = pd.DataFrame(rows)
    d["ret"] = (d["won"] - d["ask"] - [kalshi_fee(a, 100) / 100 for a in d["ask"]]) / (d["ask"] + [kalshi_fee(a, 100) / 100 for a in d["ask"]])
    return d


def by_match_boot(g: pd.DataFrame, col: str, rng) -> list[float]:
    """95% range of the mean of `col`, resampling whole matches (tickers)."""
    per = g.groupby("ticker")[col].agg(["sum", "count"])
    s, c = per["sum"].to_numpy(), per["count"].to_numpy()
    idx = rng.integers(0, len(per), size=(BOOTSTRAP, len(per)))
    means = s[idx].sum(axis=1) / c[idx].sum(axis=1)
    return [round(float(np.percentile(means, 2.5)), 4), round(float(np.percentile(means, 97.5)), 4)]


def table(d: pd.DataFrame, rng) -> dict:
    d = d.assign(band=pd.cut(d["mid"], BANDS))
    out = {}
    for band, g in d.groupby("band", observed=True):
        if g["ticker"].nunique() < 30:
            continue
        out[str(band)] = {"samples": int(len(g)), "matches": int(g["ticker"].nunique()), "price": round(float(g["mid"].mean()), 4),
                          "won": round(float(g["won"].mean()), 4), "won_ci95": by_match_boot(g, "won", rng),
                          "buy_at_ask_return": round(float(g["ret"].mean()), 4), "return_ci95": by_match_boot(g, "ret", rng)}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", required=True)
    ap.add_argument("--out", default="docs/experiments/data/inplay_calibration.json")
    args = ap.parse_args()
    rng = np.random.default_rng(20261020)
    d = samples(load_raw(Path(args.raw)), BASE)
    live = d[d["minute"] >= 0]
    report = {"markets": int(d["ticker"].nunique()), "inplay_samples": int(len(live)),
              "pre_match": table(d[d["minute"] < 0], rng), "in_play": table(live, rng),
              "in_play_by_family": {f: table(g, rng) for f, g in live.groupby("family") if g["ticker"].nunique() > 200}}
    flip = live[(live["pre_mid"] < 0.45) & (live["mid"] >= 0.55)]
    trouble = live[(live["pre_mid"] >= 0.55) & (live["mid"] < 0.45)]
    report["flip_underdog_now_favourite"] = table(flip, rng)
    report["favourite_now_underdog"] = table(trouble, rng)
    out = BASE / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
