"""Do favourites win as often as Pinnacle's closing price says, by price band? (research)

Usage:  python scripts/measure_favourite_bands.py [--from 2026-01-01] [--to 2026-10-13] [--out PATH]
                                                 [--matches-cache PATH]

Every fixture in the price store starting in [--from, --to) with a result: per book and
favourite price band, the favourite's de-vigged price (Pinnacle lam for Pinnacle, equal
split elsewhere), how often it won (95% bootstrap range), and the return per dollar of
backing every favourite and every underdog at that book's close. For the pre-registered
band (docs/experiments/2026-10-19-preregistered-near-even-favourites.md) it also reports the
underdog's return at Kalshi's closing ask, Kalshi's taker fee included.

The defaults stop before the sealed period (CLAUDE.md). The pre-registered test runs this
once, on the sealed period, with the dates the pre-registration names.
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
import v5_baseline_elo as be  # noqa: E402
from v5_devig import book_lam, devig, kalshi_fee  # noqa: E402
from scripts.measure_baseline_elo import join_market  # noqa: E402

# favourite decimal price bands, (low, high]
BANDS = [1.0, 1.08, 1.15, 1.25, 1.4, 1.6, 1.8, 2.01]
LABELS = ["-1250 or shorter", "-1250..-667", "-667..-400", "-400..-250", "-250..-167", "-167..-125", "-125..-100"]
PREREGISTERED = "-167..-125"            # Pinnacle close favourite price in (1.60, 1.80]
BOOKS = ("pinnacle", "betrivers", "draftkings", "bet365")
KALSHI_CONTRACTS = 100                  # fee per order of this size (Kalshi rounds the fee up per order)
BOOTSTRAP = 2000


def fixtures_with_results(base: Path, start: pd.Timestamp, end: pd.Timestamp, cache: str | None) -> pd.DataFrame:
    """fixture_id -> y (fixture player1 won), family; the same result join as the baseline measurement."""
    fx = pd.concat([pd.read_csv(p, dtype=str, keep_default_na=False) for p in sorted((base / "market_history" / "fixtures").glob("*.csv"))])
    fx = fx.drop_duplicates("fixture_id")
    fx["start"] = pd.to_datetime(fx["cutoff_utc"], utc=True)
    fx = fx[(fx["resolution"] == "ok") & (fx["start"] >= start) & (fx["start"] < end)
            & (fx["player1_id"] != "") & (fx["player2_id"] != "")].assign(market_p1=np.nan)
    m = pd.read_pickle(cache) if cache and Path(cache).exists() else be.load_matches(base)
    j = join_market(be.run(m, be.PRODUCTION_PARAMS), fx)
    j["y"] = (j["player1_id"] == j["winner_key"]).astype(int)
    j["family"] = j["edition_key"].str.split("|").str[0]
    return j[["fixture_id", "y", "family", "start"]].drop_duplicates("fixture_id")


def close_prices(base: Path) -> pd.DataFrame:
    pts = pd.concat([pd.read_csv(p, dtype={"fixture_id": str}) for p in sorted((base / "market_history" / "price_points").glob("*.csv"))])
    pts = pts[(pts["market_group"] == "moneyline") & (pts["close_stale"].astype(str) != "True")]
    w = pts.pivot_table(index=["fixture_id", "bookmaker"], columns="side", values="close_price", aggfunc="first").dropna().reset_index()
    return w[(w["p1"] > 1) & (w["p2"] > 1)]


def kalshi_close_ask(base: Path) -> pd.DataFrame:
    """fixture_id, side (p1/p2) -> Kalshi's best ask standing at the start."""
    d = base / "market_history" / "kalshi" / "price_points"
    if not d.exists():
        return pd.DataFrame(columns=["fixture_id", "side", "close_ask"])
    k = pd.concat([pd.read_csv(p, dtype={"fixture_id": str}) for p in sorted(d.glob("*.csv"))])
    fmap = base / "market_history" / "kalshi" / "fixture_map.csv"
    if fmap.exists():                   # price points pulled before the match was mapped carry no fixture id
        m = pd.read_csv(fmap, dtype=str).drop_duplicates("ticker").set_index("ticker")
        k["fixture_id"] = k["fixture_id"].fillna(k["ticker"].map(m["fixture_id"]))
        k["side"] = k["side"].fillna(k["ticker"].map(m["side"]))
    k = k[k["fixture_id"].notna() & k["side"].isin(["p1", "p2"]) & (k["close_ask"] > 0) & (k["close_ask"] < 1)]
    return k[["fixture_id", "side", "close_ask"]].drop_duplicates(["fixture_id", "side"])


def boot(x: np.ndarray, rng) -> list[float]:
    if len(x) == 0:
        return [float("nan"), float("nan")]
    b = x[rng.integers(0, len(x), size=(BOOTSTRAP, len(x)))].mean(axis=1)
    return [round(float(np.percentile(b, 2.5)), 4), round(float(np.percentile(b, 97.5)), 4)]


def table(w: pd.DataFrame, book: str, rng) -> pd.DataFrame:
    fav1 = w["p1"] < w["p2"]
    w = w.assign(fp=np.where(fav1, w["p1"], w["p2"]), dp=np.where(fav1, w["p2"], w["p1"]),
                 won=np.where(fav1, w["y"] == 1, w["y"] == 0), fav_side=np.where(fav1, "p1", "p2"))
    lam = book_lam(book) if book == "pinnacle" else None
    w["fair"] = [devig([a, b], lam)[0] if lam is not None else (1 / a) / (1 / a + 1 / b) for a, b in zip(w["fp"], w["dp"])]
    w["band"] = pd.cut(w["fp"], BANDS, labels=LABELS)
    w["fav_ret"] = np.where(w["won"], w["fp"] - 1, -1.0)
    w["dog_ret"] = np.where(~w["won"], w["dp"] - 1, -1.0)
    return w


def summarise(w: pd.DataFrame, rng) -> dict:
    out = {}
    for band, g in w.groupby("band", observed=True):
        won = g["won"].to_numpy(float)
        out[str(band)] = {"n": int(len(g)), "price_says": round(float(g["fair"].mean()), 4),
                          "fav_won": round(float(won.mean()), 4), "fav_won_ci95": boot(won, rng),
                          "won_minus_price": round(float((won - g["fair"]).mean()), 4),
                          "won_minus_price_ci95": boot((won - g["fair"]).to_numpy(), rng),
                          "fav_roi": round(float(g["fav_ret"].mean()), 4), "dog_roi": round(float(g["dog_ret"].mean()), 4),
                          "dog_roi_ci95": boot(g["dog_ret"].to_numpy(), rng)}
    out["ALL"] = {"n": int(len(w)), "fav_roi": round(float(w["fav_ret"].mean()), 4), "dog_roi": round(float(w["dog_ret"].mean()), 4)}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", default="2026-01-01")
    ap.add_argument("--to", dest="end", default="2026-10-13")
    ap.add_argument("--out", default="docs/experiments/data/favourite_bands.json")
    ap.add_argument("--matches-cache", default=None, help="a pickled v5_baseline_elo.load_matches frame (speed only)")
    args = ap.parse_args()
    rng = np.random.default_rng(20261019)
    start, end = pd.Timestamp(args.start, tz="UTC"), pd.Timestamp(args.end, tz="UTC")
    res = fixtures_with_results(BASE, start, end, args.matches_cache)
    prices = close_prices(BASE).merge(res, on="fixture_id")
    report = {"window": [str(start.date()), str(end.date())], "books": {}}
    pin = None
    for book in BOOKS:
        w = prices[prices["bookmaker"] == book]
        if len(w) < 100:
            continue
        t = table(w, book, rng)
        report["books"][book] = summarise(t, rng)
        if book == "pinnacle":
            pin = t
    # the pre-registered band, defined by Pinnacle's close, executed elsewhere
    if pin is not None:
        sel = pin[pin["band"] == PREREGISTERED][["fixture_id", "won", "fav_side"]]
        sel = sel.assign(dog_side=np.where(sel["fav_side"] == "p1", "p2", "p1"))
        exe = {}
        for book in BOOKS[1:]:
            b = prices[prices["bookmaker"] == book].set_index("fixture_id")
            s = sel[sel["fixture_id"].isin(b.index)]
            if len(s):
                price = np.array([b.at[f, d] for f, d in zip(s["fixture_id"], s["dog_side"])], float)
                r = np.where(~s["won"].to_numpy(bool), price - 1, -1.0)
                exe[book] = {"n": int(len(r)), "dog_roi": round(float(r.mean()), 4), "dog_roi_ci95": boot(r, rng)}
        k = kalshi_close_ask(BASE)
        s = sel.merge(k, left_on=["fixture_id", "dog_side"], right_on=["fixture_id", "side"])
        if len(s):
            cost = s["close_ask"] + [kalshi_fee(a, KALSHI_CONTRACTS) / KALSHI_CONTRACTS for a in s["close_ask"]]
            r = (np.where(~s["won"].to_numpy(bool), 1.0, 0.0) - cost) / cost
            exe["kalshi"] = {"n": int(len(r)), "dog_roi": round(float(r.mean()), 4), "dog_roi_ci95": boot(r.to_numpy(), rng)}
        report["preregistered_band_underdog_at_execution_books"] = exe
    out = BASE / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
