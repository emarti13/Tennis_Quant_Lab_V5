"""Do Kalshi tennis takers who BUY YES overpay? (the paper trader's "hold" profit, tested on trades)

Usage:  python research_tests/kalshi_takers/run_taker_side.py KALSHI_RAW_PKL MARKETS_DIR OUT_JSON

KALSHI_RAW_PKL  {ticker: {"trades": [(time, yes_price, contracts, taker_side)], "result", ...}}
                (pre-start trades pulled from Kalshi's public API, Aug-Oct 2026; see
                scripts/simulate_kalshi_making.py load_raw)
MARKETS_DIR     market_history/kalshi/markets (series, event, result, true start)

Pre-registered 2026-11-03, before any result was seen. Data before 2026-11-01 is open for
exploration (docs/superpowers/specs/2026-11-01-rolling-forward-test-amendment.md); a finding
here becomes a registered forward test, not a decision.

  UNIT      one pre-start trade: taker side (yes/no), YES price p, contracts c, result y.
  MAKER     the side the paper trader takes: it sells YES to a YES-buying taker (and buys YES
            from a NO-buying one). Maker P&L per contract: YES-taker trade p - y; NO-taker trade
            y - p; minus Kalshi's maker fee 0.0175 * p * (1 - p) (assumed for tennis, unconfirmed).
  PRIMARY   maker side of YES-taker trades, all series, contract-weighted mean P&L per contract,
            95% range resampling whole matches (all trades in a match share its outcome).
  SECONDARY NO-taker trades; by series (ATP, Challenger, WTA); by price band; by time before the
            start; by trade size; the taker's side after the taker fee 0.07 * p * (1 - p).
  CHECKS    market null (results drawn from each trade's own price: maker P&L must be about
            minus the fee); planted shift (YES wins 3 points less than priced: must be found);
            orientation: each match has two mirrored markets, so YES-taker on one player and
            NO-taker on the other must give the same sign of result (reported).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research_kit import provenance  # noqa: E402

SEED = 20261103
MAKER_FEE, TAKER_FEE = 0.0175, 0.07


def load(raw_pkl: str, markets_dir: str) -> pd.DataFrame:
    raw = pd.read_pickle(raw_pkl)
    mk = pd.concat([pd.read_csv(p) for p in sorted(Path(markets_dir).glob("*.csv"))], ignore_index=True)
    mk = mk.drop_duplicates("ticker", keep="last").set_index("ticker")
    rows = []
    for t, v in raw.items():
        res = v.get("result")
        if res not in ("yes", "no") or t not in mk.index:
            continue
        m = mk.loc[t]
        start = pd.to_datetime(m.get("cutoff_utc"), utc=True, errors="coerce")
        for ts, p, c, side in v.get("trades") or []:
            rows.append((t, m["event_ticker"], m["series"], ts, float(p), float(c), side, 1 if res == "yes" else 0, start))
    df = pd.DataFrame(rows, columns=["ticker", "event", "series", "time", "p", "c", "side", "y", "start"])
    df["time"] = pd.to_datetime(df["time"], utc=True, errors="coerce")
    df = df[(df["p"] > 0) & (df["p"] < 1) & (df["c"] > 0) & df["side"].isin(["yes", "no"])]
    # pre-start only (the pull is pre-start already; this drops anything at or after the true start)
    df = df[df["start"].isna() | (df["time"] < df["start"])].reset_index(drop=True)
    df["hours_before"] = (df["start"] - df["time"]).dt.total_seconds() / 3600
    return df


def maker_pnl(df: pd.DataFrame, y=None) -> np.ndarray:
    yy = df["y"].to_numpy() if y is None else y
    p = df["p"].to_numpy()
    raw = np.where(df["side"].to_numpy() == "yes", p - yy, yy - p)
    return raw - MAKER_FEE * p * (1 - p)


def taker_pnl(df: pd.DataFrame) -> np.ndarray:
    p, y = df["p"].to_numpy(), df["y"].to_numpy()
    raw = np.where(df["side"].to_numpy() == "yes", y - p, p - y)
    return raw - TAKER_FEE * p * (1 - p)


def weighted(df: pd.DataFrame, pnl: np.ndarray, n: int = 2000) -> dict:
    """Contract-weighted mean per contract, 95% range resampling matches."""
    if len(df) == 0:
        return {"n_trades": 0}
    w = df["c"].to_numpy()
    codes, uniq = pd.factorize(df["event"])
    num, den = np.bincount(codes, weights=pnl * w), np.bincount(codes, weights=w)
    g = np.random.default_rng(SEED)
    draws = [num[i].sum() / den[i].sum() for i in (g.integers(0, len(uniq), len(uniq)) for _ in range(n))]
    lo, hi = np.percentile(draws, [2.5, 97.5])
    return {"cents_per_contract": round(100 * num.sum() / den.sum(), 3), "range_cents": [round(100 * lo, 3), round(100 * hi, 3)],
            "n_trades": int(len(df)), "contracts": round(float(w.sum())), "matches": int(len(uniq))}


def main() -> int:
    raw_pkl, markets_dir, out_json = sys.argv[1:4]
    df = load(raw_pkl, markets_dir)
    res = {"manifest": provenance.manifest({"kalshi_raw": raw_pkl, "markets": markets_dir}, {"bootstrap": SEED}, " ".join(["python"] + sys.argv)),
           "data": {"trades": len(df), "markets": int(df["ticker"].nunique()), "matches": int(df["event"].nunique()),
                    "first": str(df["time"].min()), "last": str(df["time"].max()),
                    "taker_yes_share_of_contracts": round(float(df.loc[df.side == "yes", "c"].sum() / df["c"].sum()), 3)},
           "results": {}}
    R = res["results"]
    yes, no = df["side"] == "yes", df["side"] == "no"
    mk = maker_pnl(df)
    R["PRIMARY maker vs YES-buying takers, all series (after maker fee)"] = weighted(df[yes], mk[yes])
    R["maker vs NO-buying takers"] = weighted(df[no], mk[no])
    R["maker vs all takers"] = weighted(df, mk)
    tk = taker_pnl(df)
    R["taker YES buyers, after taker fee"] = weighted(df[yes], tk[yes])
    R["taker NO buyers, after taker fee"] = weighted(df[no], tk[no])
    for s in sorted(df["series"].dropna().unique()):
        m = (df["series"] == s).to_numpy()
        R[f"maker vs YES takers, {s}"] = weighted(df[m & yes.to_numpy()], mk[m & yes.to_numpy()])
        R[f"maker vs NO takers, {s}"] = weighted(df[m & no.to_numpy()], mk[m & no.to_numpy()])
    band = pd.cut(df["p"], [0, 0.2, 0.4, 0.6, 0.8, 1.0])
    R["maker vs YES takers by YES price"] = {str(b): weighted(df[(band == b) & yes], mk[((band == b) & yes).to_numpy()]) for b in band.cat.categories}
    R["maker vs NO takers by YES price"] = {str(b): weighted(df[(band == b) & no], mk[((band == b) & no).to_numpy()]) for b in band.cat.categories}
    hb = pd.cut(df["hours_before"], [0, 1, 6, 24, 1e4], right=False)
    R["maker vs YES takers by hours before start"] = {str(b): weighted(df[(hb == b) & yes], mk[((hb == b) & yes).to_numpy()]) for b in hb.cat.categories}
    sz = pd.cut(df["c"], [0, 10, 100, 1000, 1e9])
    R["maker vs YES takers by trade size (contracts)"] = {str(b): weighted(df[(sz == b) & yes], mk[((sz == b) & yes).to_numpy()]) for b in sz.cat.categories}

    # checks
    g = np.random.default_rng(SEED)
    p = df["p"].to_numpy()
    y_null = (g.random(len(df)) < p).astype(int)
    null = weighted(df[yes], maker_pnl(df, y_null)[yes])
    fee = float(np.average(MAKER_FEE * p[yes] * (1 - p[yes]), weights=df.loc[yes, "c"]))
    ok_null = null["range_cents"][0] <= -100 * fee <= null["range_cents"][1]
    y_pl = (g.random(len(df)) < np.clip(p - 0.03, 0.001, 0.999)).astype(int)
    planted = weighted(df[yes], maker_pnl(df, y_pl)[yes])
    ok_planted = planted["range_cents"][0] > 0 and abs(planted["cents_per_contract"] - (3 - 100 * fee)) < 1.5
    by_market = df.assign(m=mk).groupby(["event", "ticker"]).apply(lambda x: np.average(x["m"], weights=x["c"]), include_groups=False)
    res["checks"] = {
        "market_null": {"pass": bool(ok_null), "found": null, "expected_cents": round(-100 * fee, 3)},
        "planted_shift_3pts": {"pass": bool(ok_planted), "found": planted, "expected_cents": round(3 - 100 * fee, 3)},
        "events_with_two_markets": int((df.groupby("event")["ticker"].nunique() == 2).sum()),
        "per_market_maker_pnl_mean_cents": round(100 * float(by_market.mean()), 3),
    }
    res["checks_passed"] = bool(ok_null and ok_planted)
    Path(out_json).write_text(json.dumps(res, indent=1, default=str) + "\n")
    print(json.dumps({k: res[k] for k in ("data", "results", "checks", "checks_passed")}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
