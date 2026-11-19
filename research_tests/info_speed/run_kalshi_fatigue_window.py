"""Fatigue window on Kalshi: after a long match ends, how fast does the next match's price move,
and is there anything left to take after the fee?

Usage:  python research_tests/info_speed/run_kalshi_fatigue_window.py KALSHI_RAW_PKL MARKETS_DIR OUT_JSON

KALSHI_RAW_PKL  {ticker: {"candles": [(unix_ts, yes_bid, yes_ask) per minute], "result", ...}}, Aug-Oct 2026
MARKETS_DIR     market_history/kalshi/markets (event, player, true start = cutoff_utc, close_utc)

Pre-registered 2026-11-03, before any result was seen (data before 2026-11-01, open for exploration;
a finding becomes a registered forward test).

  MATCH LENGTH  a player's previous Kalshi market in the 48 hours before this match: its close time
                (Kalshi closes a match market when the result is in) minus its true start. Kept if
                30 to 400 minutes.
  SHOCK         both players have a previous match; gap = tired player's length - fresh player's.
                PRIMARY set: gap >= 45 minutes (as in the bookmaker test,
                docs/experiments/2026-10-31-fatigue-shock.md). Control: gap < 10.
  CLOCK         T0 = the tired player's previous market close (the moment its length is known).
                ENTRY = the first minute candle at or after T0 + 15 min and before the start whose
                YES spread is at most 0.05 (v3: placeholder quotes right after listing). (v2:
                Kalshi often lists the next match only after the previous one ends, so a quote at
                T0 + 15 min usually does not exist; v1 required one and kept 37 matches, without
                any result read). Tired player's YES mid (bid+ask)/2 at T0 (if listed), at entry,
                entry + 1 h, + 3 h, and the last candle before this match's start.
  PRIMARY       drift = last pre-start mid - mid at T0 + 15 min (points). Negative = the price kept
                moving against the tired player after the length was public.
  MONEY         at ENTRY, buy the fresh player at the ask (YES ask of the fresh player's market,
                or 1 - tired player's YES bid, whichever is cheaper) with Kalshi's taker fee
                0.07 * P * (1 - P); hold to settlement. Mean P&L per contract, 95% range by match.
  CHECKS        market null (results drawn from the entry price: P&L about minus the fee);
                planted shift (the fresh player wins 3 points more than the entry price: found);
                the same measures on the control set.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research_kit import provenance  # noqa: E402
from research_kit.core import boot_mean  # noqa: E402

SEED = 20261103
TAKER_FEE = 0.07


def load(raw_pkl: str, markets_dir: str):
    raw = pd.read_pickle(raw_pkl)
    mk = pd.concat([pd.read_csv(p) for p in sorted(Path(markets_dir).glob("*.csv"))], ignore_index=True)
    mk = mk.drop_duplicates("ticker", keep="last")
    mk["start"] = pd.to_datetime(mk["cutoff_utc"], utc=True, errors="coerce")
    mk["close"] = pd.to_datetime(mk["close_utc"], utc=True, errors="coerce")
    mk = mk.dropna(subset=["player_name", "start", "close", "event_ticker"])
    mk["length"] = (mk["close"] - mk["start"]).dt.total_seconds() / 60
    return raw, mk


def previous(mk: pd.DataFrame) -> pd.DataFrame:
    """Each market's player's previous market (by true start), if it closed in the 48 h before."""
    m = mk.sort_values("start").copy()
    g = m.groupby("player_name")
    m["prev_close"], m["prev_length"] = g["close"].shift(1), g["length"].shift(1)
    gap_h = (m["start"] - m["prev_close"]).dt.total_seconds() / 3600
    ok = (gap_h > 0) & (gap_h < 48) & m["prev_length"].between(30, 400)
    m.loc[~ok, ["prev_close", "prev_length"]] = [pd.NaT, np.nan]
    return m


def candles(raw: dict, ticker: str) -> pd.DataFrame:
    c = (raw.get(ticker) or {}).get("candles") or []
    if not c:
        return pd.DataFrame(columns=["t", "bid", "ask"])
    d = pd.DataFrame(c, columns=["t", "bid", "ask"])
    d["t"] = pd.to_datetime(d["t"], unit="s", utc=True)
    d = d[(d["bid"] > 0) & (d["ask"] < 1) & (d["ask"] > d["bid"])]
    return d.sort_values("t")


def at(c: pd.DataFrame, t) -> pd.Series | None:
    x = c[c["t"] <= t]
    return None if x.empty else x.iloc[-1]


def build(raw: dict, mk: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    m = previous(mk)
    rows, skipped = [], {"no_both_previous": 0, "no_quote_by_entry": 0, "result_not_settled": 0}
    for ev, g in m.groupby("event_ticker"):
        if len(g) != 2 or g["prev_length"].isna().any():
            skipped["no_both_previous"] += 1
            continue
        g = g.sort_values("prev_length", ascending=False)
        tired, fresh = g.iloc[0], g.iloc[1]
        res = tired.get("result")                                # the market list has every result (v2)
        if res not in ("yes", "no"):
            skipped["result_not_settled"] += 1
            continue
        ct, cf = candles(raw, tired["ticker"]), candles(raw, fresh["ticker"])
        t0, start = tired["prev_close"], tired["start"]
        entry_t = t0 + pd.Timedelta(minutes=15)
        if entry_t >= start:
            skipped["no_quote_by_entry"] += 1
            continue
        # v3: the first quotes after a market is listed are placeholders (e.g. bid 0.02 / ask 0.36);
        # v2 entered on them and lost about 31 cents everywhere, control included (planted check
        # failed). Entry needs a real book: YES spread at most 0.05.
        after = ct[(ct["t"] >= entry_t) & (ct["t"] < start) & (ct["ask"] - ct["bid"] <= 0.05)]
        if after.empty:
            skipped["no_quote_by_entry"] += 1
            continue
        e_t = after.iloc[0]
        entry_t = e_t["t"]
        e_f = at(cf[(cf["t"] < start) & (cf["ask"] - cf["bid"] <= 0.05)], entry_t)
        mid = lambda r: None if r is None else (r["bid"] + r["ask"]) / 2  # noqa: E731
        pre = ct[ct["t"] < start]
        price_fresh = 1 - e_t["bid"]
        if e_f is not None:
            price_fresh = min(price_fresh, e_f["ask"])
        rows.append({"event": ev, "series": tired["series"], "gap": tired["prev_length"] - fresh["prev_length"],
                     "tired_won": 1 if res == "yes" else 0, "hours_to_start": (start - entry_t).total_seconds() / 3600,
                     "listing_lag_h": (entry_t - t0).total_seconds() / 3600,
                     "mid_t0": mid(at(ct, t0)), "mid_entry": mid(e_t), "mid_1h": mid(at(pre, entry_t + pd.Timedelta(hours=1))),
                     "mid_3h": mid(at(pre, entry_t + pd.Timedelta(hours=3))), "mid_last": mid(pre.iloc[-1]),
                     "price_fresh": price_fresh})
    return pd.DataFrame(rows), skipped


def money(d: pd.DataFrame, y_fresh=None) -> np.ndarray:
    p = d["price_fresh"].to_numpy()
    yf = (1 - d["tired_won"].to_numpy()) if y_fresh is None else y_fresh
    return np.where(yf == 1, 1 - p, -p) - TAKER_FEE * p * (1 - p)


def summarise(d: pd.DataFrame) -> dict:
    if d.empty:
        return {"n": 0}
    r = lambda v: [round(x, 3) for x in v]  # noqa: E731
    out = {"n": int(len(d)),
           "PRIMARY drift last pre-start minus entry (pts)": r([100 * x for x in boot_mean((d["mid_last"] - d["mid_entry"]).to_numpy(), seed=SEED)]),
           "move t0 to entry (pts)": r([100 * x for x in boot_mean((d["mid_entry"] - d["mid_t0"]).dropna().to_numpy(), seed=SEED)]),
           "MONEY back fresh at entry, after fee (cents per contract)": r([100 * x for x in boot_mean(money(d), seed=SEED)]),
           "tired won vs entry mid (pts)": r([100 * x for x in boot_mean((d["tired_won"] - d["mid_entry"]).to_numpy(), seed=SEED)]),
           "tired won vs last pre-start mid (pts)": r([100 * x for x in boot_mean((d["tired_won"] - d["mid_last"]).to_numpy(), seed=SEED)]),
           "median hours entry to start": round(float(d["hours_to_start"].median()), 2),
           "median hours previous end to entry": round(float(d["listing_lag_h"].median()), 2)}
    for k in ("mid_1h", "mid_3h"):
        x = (d[k] - d["mid_entry"]).dropna()
        out[f"move entry to {k[4:]} (pts)"] = r([100 * v for v in boot_mean(x.to_numpy(), seed=SEED)]) + [int(len(x))]
    return out


def main() -> int:
    raw_pkl, markets_dir, out_json = sys.argv[1:4]
    raw, mk = load(raw_pkl, markets_dir)
    d, skipped = build(raw, mk)
    prim, ctrl = d[d["gap"] >= 45], d[d["gap"] < 10]
    res = {"manifest": provenance.manifest({"kalshi_raw": raw_pkl, "markets": markets_dir}, {"bootstrap": SEED}, " ".join(["python"] + sys.argv)),
           "matches_built": int(len(d)), "skipped": skipped,
           "PRIMARY gap>=45": summarise(prim), "control gap<10": summarise(ctrl),
           "gap 10-45": summarise(d[(d["gap"] >= 10) & (d["gap"] < 45)]),
           "gap>=90": summarise(d[d["gap"] >= 90])}
    for s in sorted(prim["series"].unique()):
        res[f"PRIMARY {s}"] = summarise(prim[prim["series"] == s])
    g = np.random.default_rng(SEED)
    p = prim["price_fresh"].to_numpy()
    if len(p):
        null = boot_mean(money(prim, (g.random(len(p)) < p).astype(int)), seed=SEED)
        fee = float(np.mean(TAKER_FEE * p * (1 - p)))
        planted = boot_mean(money(prim, (g.random(len(p)) < np.clip(p + 0.03, 0, 1)).astype(int)), seed=SEED)
        res["checks"] = {"market_null": {"pass": bool(null[1] <= -fee <= null[2]), "found_cents": [round(100 * v, 3) for v in null], "expected_cents": round(-100 * fee, 3)},
                         "planted_3pts": {"pass": bool(planted[1] > -fee and abs(planted[0] - (0.03 - fee)) < 0.03),
                                          "found_cents": [round(100 * v, 3) for v in planted], "expected_cents": round(100 * (0.03 - fee), 3)}}
        res["checks_passed"] = all(c["pass"] for c in res["checks"].values())
    Path(out_json).write_text(json.dumps(res, indent=1, default=str) + "\n")
    print(json.dumps({k: v for k, v in res.items() if k != "manifest"}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
