"""Measure each book's de-vig setting (Box-Cox lam) on our own closing prices.

Usage:  python scripts/measure_devig.py [--out docs/experiments/data/devig_measurement.json]

Spec §2.5 / rebuild plan Step 3 (user decision 2026-10-13):
- moneyline prices from the price store (market_history/), winners joined through our ids
  (v5_market_results);
- only fixtures that started before the sealed period (2026-10-13; CLAUDE.md);
- per book, at the close (a close whose book stopped quoting more than 60 minutes before the
  start is left out, spec §5.4) and 6 hours before the start;
- lam fitted on the earliest 60% (by start time), tested on the latest 40%: log loss for the
  fitted lam, multiplicative (0), additive (1) and power, with paired-bootstrap 95% intervals
  against multiplicative, by men's tour, women's tour, Challengers and WTA 125;
- reliability of the fitted lam by probability bucket on the test set.
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
from v5_devig import devig, devig_power  # noqa: E402
from v5_market_results import load_fixture_winners  # noqa: E402

SEALED_FROM = pd.Timestamp("2026-10-13", tz="UTC")
COARSE = [round(x, 2) for x in np.arange(0.0, 5.01, 0.25)]   # then 0.05 steps around the best
POINTS = {"close": "close_price", "t6h": "t6h_price"}
FIT_SHARE = 0.6
BOOTSTRAP = 1000
MIN_TEST = 200
COVERAGE: dict = {}


def load_pairs(base: Path) -> pd.DataFrame:
    """One row per fixture, book and point: both sides' prices and the winner."""
    fx = pd.concat([pd.read_csv(p, dtype=str, keep_default_na=False) for p in sorted((base / "market_history" / "fixtures").glob("*.csv"))])
    fx = fx.drop_duplicates("fixture_id")
    fx["cutoff"] = pd.to_datetime(fx["cutoff_utc"], utc=True)
    fx = fx[fx["cutoff"] < SEALED_FROM]
    pts = pd.concat([pd.read_csv(p, dtype={"fixture_id": str, "market_id": str}) for p in sorted((base / "market_history" / "price_points").glob("*.csv"))])
    pts = pts[(pts["market_group"] == "moneyline") & pts["fixture_id"].isin(fx["fixture_id"])]
    winners = load_fixture_winners(fx, base)
    resolved = fx[fx["resolution"] == "ok"]
    COVERAGE.update(fixtures=int(len(fx)), resolved=int(len(resolved)),
                    resolved_with_winner=int(resolved["fixture_id"].isin(winners["fixture_id"]).sum()),
                    by_month={m: round(float(g["fixture_id"].isin(winners["fixture_id"]).mean()), 3)
                              for m, g in resolved.groupby(resolved["cutoff"].dt.strftime("%Y-%m"))})
    rows = []
    for point, col in POINTS.items():
        use = pts if point != "close" else pts[pts["close_stale"].astype(str) != "True"]
        wide = use.pivot_table(index=["fixture_id", "bookmaker", "market_id"], columns="side", values=col, aggfunc="first")
        wide = wide.dropna(subset=[c for c in ("p1", "p2") if c in wide.columns]).reset_index()
        if not {"p1", "p2"} <= set(wide.columns):
            continue
        wide = wide[(wide["p1"] > 1) & (wide["p2"] > 1)].drop_duplicates(["fixture_id", "bookmaker"])
        rows.append(wide.assign(point=point))
    pairs = pd.concat(rows, ignore_index=True).merge(winners, on="fixture_id")
    pairs = pairs.merge(fx[["fixture_id", "cutoff", "edition_key"]], on="fixture_id")
    pairs["family"] = pairs["edition_key"].str.split("|").str[0]
    pairs["y"] = (pairs["winner_side"] == "p1").astype(int)
    return pairs


def _loss(q1: np.ndarray, y: np.ndarray) -> np.ndarray:
    q = np.clip(np.where(y == 1, q1, 1 - q1), 1e-12, 1)
    return -np.log(q)


def _probs(df: pd.DataFrame, method) -> np.ndarray:
    out = []
    for a, b in zip(df["p1"], df["p2"]):
        try:
            out.append(method([a, b])[0])
        except ValueError:
            out.append(float("nan"))
    return np.array(out)


def evaluate(df: pd.DataFrame, rng: np.random.Generator) -> dict:
    df = df.sort_values("cutoff")
    cut = int(len(df) * FIT_SHARE)
    fit, test = df.iloc[:cut], df.iloc[cut:]
    yf, yt = fit["y"].to_numpy(), test["y"].to_numpy()
    fit_loss = lambda lam: float(np.nanmean(_loss(_probs(fit, lambda p, l=lam: devig(p, l)), yf)))
    grid = {lam: fit_loss(lam) for lam in COARSE}
    c = min(grid, key=grid.get)
    for lam in np.arange(max(0.0, c - 0.2), min(5.0, c + 0.2) + 1e-9, 0.05):
        lam = round(float(lam), 2)
        grid.setdefault(lam, fit_loss(lam))
    best = min(grid, key=grid.get)
    methods = {"fitted": lambda p: devig(p, best), "multiplicative": lambda p: devig(p, 0.0),
               "additive": lambda p: devig(p, 1.0), "power": devig_power}
    losses = {k: _loss(_probs(test, m), yt) for k, m in methods.items()}
    ok = np.all([np.isfinite(v) for v in losses.values()], axis=0)
    base = losses["multiplicative"][ok]
    out = {"n_fit": int(len(fit)), "n_test": int(ok.sum()), "fit_until": str(fit["cutoff"].max()),
           "lam_fitted": best, "lam_at_edge": best in (0.0, 5.0), "fit_curve": {str(k): round(v, 5) for k, v in grid.items() if k in (0.0, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0)},
           "test_log_loss": {k: round(float(v[ok].mean()), 5) for k, v in losses.items()}}
    idx = rng.integers(0, ok.sum(), size=(BOOTSTRAP, ok.sum()))
    for k in ("fitted", "additive", "power"):
        d = losses[k][ok] - base
        boots = d[idx].mean(axis=1)
        out.setdefault("vs_multiplicative", {})[k] = {"mean": round(float(d.mean()), 5),
                                                       "ci95": [round(float(np.percentile(boots, 2.5)), 5), round(float(np.percentile(boots, 97.5)), 5)]}
    q = _probs(test, methods["fitted"])
    buckets = pd.cut(q, [0, .1, .2, .3, .4, .5, .6, .7, .8, .9, 1])
    rel = pd.DataFrame({"q": q, "y": yt, "b": buckets}).groupby("b", observed=True).agg(n=("y", "size"), predicted=("q", "mean"), observed=("y", "mean"))
    out["reliability"] = [{"bucket": str(b), "n": int(r.n), "predicted": round(r.predicted, 3), "observed": round(r.observed, 3)} for b, r in rel.iterrows()]
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="docs/experiments/data/devig_measurement.json")
    args = ap.parse_args()
    rng = np.random.default_rng(20261013)
    pairs = load_pairs(BASE)
    report = {"sealed_from": str(SEALED_FROM.date()), "pairs": int(len(pairs)), "coverage": COVERAGE,
              "by_book_point": {}, "by_family": {}}
    for (book, point), g in pairs.groupby(["bookmaker", "point"]):
        if len(g) * (1 - FIT_SHARE) >= MIN_TEST:
            report["by_book_point"][f"{book}|{point}"] = evaluate(g, rng)
    for (book, point, family), g in pairs.groupby(["bookmaker", "point", "family"]):
        if point == "close" and len(g) * (1 - FIT_SHARE) >= MIN_TEST:
            report["by_family"][f"{book}|{family}"] = evaluate(g, rng)
    out = BASE / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    print("coverage", json.dumps(COVERAGE))
    for key, r in report["by_book_point"].items():
        print(f"{key:24s} n={r['n_fit']}+{r['n_test']} lam={r['lam_fitted']:.2f} test={r['test_log_loss']} "
              f"fitted-vs-mult={r['vs_multiplicative']['fitted']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
