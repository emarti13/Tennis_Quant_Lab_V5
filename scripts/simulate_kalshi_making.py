"""Would quoting both sides of Kalshi tennis match markets have made money? (research, edge search 3)

Usage:  python scripts/simulate_kalshi_making.py --raw DIR [--oc-table PATH | --matches-cache PATH]
                                                 [--out docs/experiments/data/kalshi_making.json]

--raw is a folder holding the kalshi_*.jsonl.gz files of the market-raw-YYYY-MM releases
(every Kalshi market with its 1-minute best bid/ask and every trade before the start).

A replay, per Kalshi player market ("A wins", YES pays $1), of a resting buy and a resting
sell around a fair price, from the moment Pinnacle's line is open until one minute before the
match starts, when everything is cancelled:

- Fair price at time t: Pinnacle's de-vigged moneyline at the latest point known by t (open,
  T-24/12/6/1 h, close; the price store). Pinnacle is information here, never execution.
  "lean" adds the open+Elo+fatigue model's predicted shift from the open (measured in
  docs/experiments/2026-10-18-open-close-edge.md; fitted on January-June fixtures, so August
  to October is out of sample). Fixtures the model cannot price (fewer than 18 rated matches)
  get no lean.
- Quotes: buy at fair - h rounded down to the cent, sell at fair + h rounded up, never
  crossing the standing best bid/ask (that would be a taker trade). Q contracts per side;
  a side stops quoting once the net position in that market reaches the limit.
- Fills, conservatively, from Kalshi's real trades: a taker buying YES at price x fills our
  sell at s when x > s, or x == s and s was strictly better than the standing best ask (we
  were first in line); takers selling likewise for our buy. Each trade fills at most its own
  size. Takers who would have come only because our price was better are not counted.
- Three ways to count the result: held to settlement (the match decides what is left);
  marked at Kalshi's last mid before the start (the spread earned, net of being picked off,
  without the match's noise); flattened at the start (what is left closed by paying the
  spread and the taker fee).
- Settlement: YES pays 1 on "yes", 0 on "no"; anything else (void) is dropped. Maker fee:
  none, and Kalshi's maker schedule as a check (0.0175 * contracts * P * (1 - P)), since the
  fee on tennis markets is not confirmed. The taker pays the taker fee, not us.

Only fixtures starting before the sealed period (2026-10-13). Every setting tried is
reported; none is chosen here.
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from v5_devig import book_lam, devig  # noqa: E402
from v5_kalshi_history import rebuild_fixture_map  # noqa: E402

SEALED_FROM = pd.Timestamp("2026-10-13", tz="UTC")
HALF_WIDTHS = (0.01, 0.02, 0.03, 0.05)
SIZE = 100                  # contracts per quote
LIMIT = 300                 # net contracts per market before a side stops quoting
MAKER_FEE_RATE = 0.0175
KALSHI_TAKER = 0.07         # taker fee rate (v5_devig.KALSHI_TAKER_FEE_RATE), paid when flattening
CHECKPOINTS = (24, 12, 6, 1)
BOOTSTRAP = 2000


def load_raw(raw_dir: Path) -> dict:
    """ticker -> candles [(ts, bid, ask)], trades [(ts, yes_price, count, taker_side)], result."""
    out = {}
    for f in sorted(raw_dir.glob("kalshi_*.jsonl.gz")):
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            for line in fh:
                r = json.loads(line)
                m = r["market"]
                candles = [(pd.Timestamp(c["end_period_ts"], unit="s", tz="UTC"),
                            float(c["yes_bid"]["close_dollars"]) if c.get("yes_bid", {}).get("close_dollars") else None,
                            float(c["yes_ask"]["close_dollars"]) if c.get("yes_ask", {}).get("close_dollars") else None)
                           for c in r["candles"]]
                trades = [(pd.Timestamp(t["created_time"]), float(t["yes_price_dollars"]), float(t["count_fp"]), t["taker_side"])
                          for t in r["pre_start_trades"]]
                old = out.get(m["ticker"])
                if old is None or len(trades) + len(candles) >= len(old["trades"]) + len(old["candles"]):
                    out[m["ticker"]] = {"candles": candles, "trades": trades, "result": m.get("result")}
    return out


def pinnacle_path(base: Path) -> pd.DataFrame:
    """fixture_id -> start and Pinnacle's de-vigged p1 at each known point [(ts, p1)]."""
    fx = pd.concat([pd.read_csv(p, dtype=str, keep_default_na=False) for p in sorted((base / "market_history" / "fixtures").glob("*.csv"))])
    fx = fx.drop_duplicates("fixture_id").set_index("fixture_id")
    pts = pd.concat([pd.read_csv(p, dtype={"fixture_id": str}) for p in sorted((base / "market_history" / "price_points").glob("*.csv"))])
    pts = pts[(pts["market_group"] == "moneyline") & (pts["bookmaker"] == "pinnacle")]
    lam = book_lam("pinnacle")
    rows = {}
    for fid, g in pts.groupby("fixture_id"):
        if fid not in fx.index or set(g["side"]) != {"p1", "p2"}:
            continue
        start = pd.to_datetime(fx.at[fid, "cutoff_utc"], utc=True)
        a, b = g[g["side"] == "p1"].iloc[0], g[g["side"] == "p2"].iloc[0]
        path = []
        cols = [("open_price", a["open_utc"])] + [(f"t{h}h_price", start - pd.Timedelta(hours=h)) for h in CHECKPOINTS]
        if str(a["close_stale"]) != "True":
            cols.append(("close_price", a["close_utc"]))
        for col, when in cols:
            pa, pb = a[col], b[col]
            if pd.notna(pa) and pd.notna(pb) and pa > 1 and pb > 1 and pd.notna(when):
                path.append((pd.Timestamp(when) if isinstance(when, pd.Timestamp) else pd.to_datetime(when, utc=True), devig([pa, pb], lam)[0]))
        if path:
            rows[fid] = {"start": start, "path": sorted(path), "edition_key": fx.at[fid, "edition_key"]}
    return rows


def model_shift(oc_table: pd.DataFrame) -> dict:
    """fixture_id -> the open+Elo+fatigue model's shift from Pinnacle's open for player1
    (fitted on January-June; scripts/measure_open_close_edge.py)."""
    import scripts.measure_open_close_edge as oc
    j = oc_table[oc_table["n_min"] >= 18].copy()
    j["elo_gap"] = oc.logit(j["elo_p1"]) - oc.logit(j["open_p1"])
    cols = ["elo_gap"] + [f"d_{c}" for c in oc.FATIGUE] + [f"d_{c}_missing" for c in oc.FATIGUE]
    train = j[j["start"] < oc.TEST_FROM]
    Xtr, mu, sd = oc.design(train, cols)
    w = oc.fit_logistic(np.c_[Xtr, np.ones(len(Xtr))], train["y"].to_numpy(float), oc.logit(train["open_p1"]))
    X, _, _ = oc.design(j, cols, mu, sd)
    p = 1 / (1 + np.exp(-(oc.logit(j["open_p1"]) + np.c_[X, np.ones(len(X))] @ w)))
    test = (j["start"] >= oc.TEST_FROM).to_numpy()
    return dict(zip(j["fixture_id"][test], (p - j["open_p1"].to_numpy())[test]))


def fair_at(path: list, t) -> float | None:
    p = None
    for when, v in path:
        if when <= t:
            p = v
        else:
            break
    return p


def mid_fair(best_bid, best_ask) -> float | None:
    """Kalshi's own mid as the fair price: only from a two-sided book no wider than 20c."""
    if best_bid and best_ask and 0 < best_bid < best_ask < 1 and best_ask - best_bid <= 0.20:
        return (best_bid + best_ask) / 2
    return None


def quotes(fair: float, h: float, best_bid, best_ask) -> tuple[float, float]:
    """Our buy and sell: fair -/+ h to the cent, never crossing the standing book."""
    f = min(max(fair, 0.02), 0.98)
    bid, ask = math.floor(round((f - h) * 100, 6)) / 100, math.ceil(round((f + h) * 100, 6)) / 100
    if best_ask is not None:
        bid = min(bid, round(best_ask - 0.01, 2))
    if best_bid is not None:
        ask = max(ask, round(best_bid + 0.01, 2))
    return bid, ask


def fill(taker: str, x: float, count: float, bid: float, ask: float, best_bid, best_ask, pos: float):
    """Does a real trade (taker side, YES price x, size) fill our quote? (side, price, contracts)
    or None. Through our price, or at it while we were strictly the best; at most the trade's
    size, the quote size and what the position limit leaves."""
    if taker == "yes" and pos > -LIMIT and 0 < ask < 1:                  # taker buys YES: our sell
        if x > ask or (x == ask and (best_ask is None or ask < best_ask)):
            return ("sell", ask, min(count, SIZE, LIMIT + pos))
    elif taker == "no" and pos < LIMIT and 0 < bid < 1:                  # taker sells YES: our buy
        if x < bid or (x == bid and (best_bid is None or bid > best_bid)):
            return ("buy", bid, min(count, SIZE, LIMIT - pos))
    return None


def replay(market: dict, fair_path: list | None, start, h: float, lean: float) -> list[tuple[str, float, float]]:
    """Fills [(side 'buy'/'sell', price, contracts)] for one market. With no fair path the
    fair price is Kalshi's own mid standing before the trade (quotes start once a two-sided
    book exists)."""
    stop = start - pd.Timedelta(minutes=1)
    candles = [c for c in market["candles"] if c[0] <= stop]
    fills, pos, ci = [], 0.0, -1
    for ts, x, count, taker in sorted(t for t in market["trades"] if t[0] <= stop):
        while ci + 1 < len(candles) and candles[ci + 1][0] <= ts:
            ci += 1
        best_bid, best_ask = (candles[ci][1], candles[ci][2]) if ci >= 0 else (None, None)
        fair = fair_at(fair_path, ts) if fair_path is not None else mid_fair(best_bid, best_ask)
        if fair is None:
            continue
        bid, ask = quotes(fair + lean, h, best_bid, best_ask)
        got = fill(taker, x, count, bid, ask, best_bid, best_ask, pos)
        if got:
            fills.append(got)
            pos += got[2] if got[0] == "buy" else -got[2]
    return fills


def last_quote(market: dict, start) -> tuple[float | None, float | None]:
    """Kalshi's best bid/ask standing one minute before the start."""
    stop = start - pd.Timedelta(minutes=1)
    before = [c for c in market["candles"] if c[0] <= stop and c[1] and c[2] and c[1] < c[2]]
    return (before[-1][1], before[-1][2]) if before else (None, None)


def pnl(fills: list, won: float, maker_fee: bool) -> tuple[float, float, float]:
    """(profit, contracts traded, net position at the start). `won` is the settlement (1/0),
    or a mark price (Kalshi's last mid) to value the fills without the match result."""
    total, vol, pos = 0.0, 0.0, 0.0
    for side, price, q in fills:
        total += q * ((won - price) if side == "buy" else (price - won))
        if maker_fee:
            total -= MAKER_FEE_RATE * q * price * (1 - price)
        vol += q
        pos += q if side == "buy" else -q
    return total, vol, pos


def boot(x: np.ndarray, rng) -> list[float]:
    if len(x) == 0:
        return [float("nan")] * 2
    b = x[rng.integers(0, len(x), size=(BOOTSTRAP, len(x)))].sum(axis=1)
    return [round(float(np.percentile(b, 2.5)), 2), round(float(np.percentile(b, 97.5)), 2)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", required=True)
    ap.add_argument("--oc-table", default=None, help="the joined fixture table pickled by measure_open_close_edge.py --dump")
    ap.add_argument("--out", default="docs/experiments/data/kalshi_making.json")
    args = ap.parse_args()
    rng = np.random.default_rng(20261019)
    raw = load_raw(Path(args.raw))
    mk = pd.concat([pd.read_csv(p, dtype=str, keep_default_na=False) for p in sorted((BASE / "market_history" / "kalshi" / "markets").glob("*.csv"))])
    registry = pd.read_csv(BASE / "oddspapi_registry" / "fixtures.csv", dtype=str, keep_default_na=False)
    fmap = rebuild_fixture_map(mk.drop_duplicates("ticker"), registry)
    fmap = fmap[fmap["match_method"] == "names"].merge(mk.drop_duplicates("ticker")[["ticker", "family"]], on="ticker")
    pin = pinnacle_path(BASE)
    shifts = model_shift(pd.read_pickle(args.oc_table)) if args.oc_table else {}
    reg = registry.set_index("fixture_id")
    rows = []
    for r in fmap.itertuples():
        m, p = raw.get(r.ticker), pin.get(r.fixture_id)
        if m is None or m["result"] not in ("yes", "no") or r.fixture_id not in reg.index:
            continue
        f = reg.loc[r.fixture_id]
        f = f.iloc[0] if isinstance(f, pd.DataFrame) else f
        start = pd.to_datetime(f["true_start_time_utc"] or f["start_time_utc"], utc=True)
        if start >= SEALED_FROM:
            continue
        sign = 1.0 if r.side == "p1" else -1.0
        won = int(m["result"] == "yes")
        shift = shifts.get(r.fixture_id)
        runs = [("kalshi_mid", None, 0.0)]
        if p is not None:
            path = [(t, v if sign > 0 else 1 - v) for t, v in p["path"]]
            runs.append(("pinnacle", path, 0.0))
            if shift is not None:
                runs.append(("pinnacle+lean", path, sign * shift))
        for h in HALF_WIDTHS:
            for name, path, lean in runs:
                fills = replay(m, path, start, h, lean)
                bid, ask = last_quote(m, start)
                for fee in (False, True):
                    prof, vol, pos = pnl(fills, won, fee)
                    if bid is not None:
                        mark, _, _ = pnl(fills, (bid + ask) / 2, fee)
                        # flatten what is left at the start: cross half the spread and pay the taker fee
                        exit_price = ask if pos < 0 else bid
                        flat = mark - abs(pos) * (abs((bid + ask) / 2 - exit_price) + KALSHI_TAKER * exit_price * (1 - exit_price))
                    else:
                        mark = flat = np.nan
                    rows.append({"ticker": r.ticker, "event": r.event_ticker, "family": r.family, "start": start,
                                 "h": h, "fair": name, "maker_fee": fee, "has_lean": shift is not None,
                                 "profit": prof, "marked": mark, "flattened": flat, "contracts": vol, "end_position": pos})
    d = pd.DataFrame(rows)
    report = {"markets": int(d["ticker"].nunique()), "events": int(d["event"].nunique()),
              "dates": [str(d["start"].min().date()), str(d["start"].max().date())], "settings": []}
    for (h, fair, fee, fam), g in d.groupby(["h", "fair", "maker_fee", "family"]):
        report["settings"].append({"h": h, "fair": fair, "maker_fee": fee, "family": fam, "markets": int(len(g)),
                                   "markets_filled": int((g["contracts"] > 0).sum()), "contracts": round(float(g["contracts"].sum())),
                                   "profit": round(float(g["profit"].sum()), 2), "profit_ci95": boot(g["profit"].to_numpy(), rng),
                                   "marked_at_last_mid": round(float(g["marked"].sum()), 2),
                                   "marked_ci95": boot(g["marked"].dropna().to_numpy(), rng),
                                   "flattened_at_start": round(float(g["flattened"].sum()), 2),
                                   "flattened_ci95": boot(g["flattened"].dropna().to_numpy(), rng),
                                   "cents_per_contract": round(100 * float(g["profit"].sum() / max(g["contracts"].sum(), 1)), 2),
                                   "worst_market": round(float(g["profit"].min()), 2),
                                   "mean_abs_end_position": round(float(g["end_position"].abs().mean()), 1)})
    # same fixtures only: the lean versus no lean
    leanable = d[d["has_lean"]]
    report["lean_vs_none_same_markets"] = [
        {"h": h, "family": fam, "maker_fee": False, "markets": int(g["ticker"].nunique()),
         **{f: round(float(g[(g["fair"] == f) & ~g["maker_fee"]]["profit"].sum()), 2) for f in ("pinnacle", "pinnacle+lean")}}
        for (h, fam), g in leanable.groupby(["h", "family"])]
    out = BASE / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1, default=str) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
