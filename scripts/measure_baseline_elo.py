"""Measure the leak-free player_id Elo (v5_baseline_elo) out of sample, next to the market.

Usage:  python scripts/measure_baseline_elo.py [--out docs/experiments/data/baseline_elo.json] [--quick]

Chronological, nothing from the sealed period (from 2026-10-13; CLAUDE.md):
- settings chosen on 2025 matches (log loss), from a small grid: K scale, surface blend,
  newcomer rating;
- tested on 2026 matches from events that started before 2026-10-06 (so none of their
  rounds reach the sealed period);
- on the 2026 matches the price store also has (both players resolved, Pinnacle close not
  stale): log loss of this Elo, of the current engine's accepted baseline (serve/return +
  Elo, calibrated on 2025; from v5_*_walkforward.csv, whose Elo uses the old ordering) and of
  the market (Pinnacle close, de-vigged with its measured lam), with paired-bootstrap 95%
  intervals of the differences;
- by tour, level and players' experience (matches rated before).
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
from v5_devig import book_lam, devig  # noqa: E402
from v5_model_calibration import calibrated_match_probability  # noqa: E402

TEST_EVENTS_BEFORE = pd.Timestamp("2026-10-06")
SEALED_FROM = pd.Timestamp("2026-10-13", tz="UTC")
GRID_K = (0.6, 1.0, 1.4)
GRID_BLEND = (0.3, 0.5, 0.7)
GRID_NEWCOMER = (1350.0, 1425.0, 1500.0)
BOOTSTRAP = 1000


def loss(p) -> np.ndarray:
    return -np.log(np.clip(np.asarray(p, float), 1e-12, 1))


def tune(m: pd.DataFrame, quick: bool) -> tuple[be.EloParams, list[dict]]:
    tried, best = [], None
    grid_k, grid_b = ((1.0,), (0.5,)) if quick else (GRID_K, GRID_BLEND)
    for k in grid_k:
        for b in grid_b:
            pr = be.run(m, be.EloParams(k=k, blend=b))
            v = float(loss(pr[pr["date"].dt.year == 2025]["p_winner"]).mean())
            tried.append({"k": k, "blend": b, "newcomer": 1500.0, "log_loss_2025": round(v, 5)})
            best = min(best or tried[-1], tried[-1], key=lambda r: r["log_loss_2025"])
    for nc in (() if quick else GRID_NEWCOMER):
        if nc == 1500.0:
            continue
        pr = be.run(m, be.EloParams(k=best["k"], blend=best["blend"], newcomer=nc))
        v = float(loss(pr[pr["date"].dt.year == 2025]["p_winner"]).mean())
        tried.append({"k": best["k"], "blend": best["blend"], "newcomer": nc, "log_loss_2025": round(v, 5)})
        best = min(best, tried[-1], key=lambda r: r["log_loss_2025"])
    return be.EloParams(k=best["k"], blend=best["blend"], newcomer=best["newcomer"]), tried


def market_close(base: Path) -> pd.DataFrame:
    """One row per fixture: our two player ids, start, and Pinnacle's de-vigged close for p1."""
    fx = pd.concat([pd.read_csv(p, dtype=str, keep_default_na=False) for p in sorted((base / "market_history" / "fixtures").glob("*.csv"))])
    fx = fx.drop_duplicates("fixture_id")
    fx["start"] = pd.to_datetime(fx["cutoff_utc"], utc=True)
    fx = fx[(fx["resolution"] == "ok") & (fx["start"] < SEALED_FROM) & (fx["player1_id"] != "") & (fx["player2_id"] != "")]
    pts = pd.concat([pd.read_csv(p, dtype={"fixture_id": str}) for p in sorted((base / "market_history" / "price_points").glob("*.csv"))])
    pts = pts[(pts["market_group"] == "moneyline") & (pts["bookmaker"] == "pinnacle") & (pts["close_stale"].astype(str) != "True")]
    wide = pts.pivot_table(index="fixture_id", columns="side", values="close_price", aggfunc="first").dropna()
    wide = wide[(wide["p1"] > 1) & (wide["p2"] > 1)]
    lam = book_lam("pinnacle")
    wide["market_p1"] = [devig([a, b], lam)[0] for a, b in zip(wide["p1"], wide["p2"])]
    return fx.merge(wide[["market_p1"]], left_on="fixture_id", right_index=True)[
        ["fixture_id", "start", "player1_id", "player2_id", "edition_key", "market_p1"]]


def join_market(pred: pd.DataFrame, mk: pd.DataFrame) -> pd.DataFrame:
    """A rated match <-> a priced fixture: same two players, fixture start within the event's
    window (TennisMyLife dates are the event start). Unique matches only."""
    mk = mk.assign(pair=[frozenset(x) for x in zip(mk["player1_id"], mk["player2_id"])])
    pred = pred.assign(pair=[frozenset(x) for x in zip(pred["winner_key"], pred["loser_key"])])
    j = pred.merge(mk, on="pair")
    d = (j["start"].dt.tz_localize(None) - j["date"]).dt.days
    j = j[(d >= -3) & (d <= 20)]
    j = j[~j.duplicated("key", keep=False) & ~j.duplicated("fixture_id", keep=False)]
    j["market_winner"] = np.where(j["player1_id"] == j["winner_key"], j["market_p1"], 1 - j["market_p1"])
    return j


def current_engine(pred: pd.DataFrame, base: Path) -> pd.Series:
    """Accepted baseline of the current engine for each match, by names and event date."""
    parts = []
    for tour, f in (("MEN", "v5_men_walkforward.csv"), ("WTA", "v5_wta_walkforward.csv")):
        w = pd.read_csv(base / f, low_memory=False)
        w["date"] = pd.to_datetime(w["date"])
        w["p_current"] = [calibrated_match_probability(a, b, e, tour)
                          for a, b, e in zip(w["winner_serve_p"], w["loser_serve_p"], w["elo_winner_p"])]
        parts.append(w.assign(tour=tour)[["tour", "date", "winner", "loser", "p_current"]])
    w = pd.concat(parts).drop_duplicates(["tour", "date", "winner", "loser"], keep=False)
    j = pred.merge(w, left_on=["tour", "date", "winner_name", "loser_name"], right_on=["tour", "date", "winner", "loser"], how="left")
    return j.set_index("key")["p_current"]


def paired(a: np.ndarray, b: np.ndarray, rng) -> dict:
    d = a - b
    idx = rng.integers(0, len(d), size=(BOOTSTRAP, len(d)))
    boots = d[idx].mean(axis=1)
    return {"mean": round(float(d.mean()), 5), "ci95": [round(float(np.percentile(boots, 2.5)), 5), round(float(np.percentile(boots, 97.5)), 5)]}


def summary(df: pd.DataFrame, cols: list[str]) -> dict:
    return {"n": int(len(df)), **{c: round(float(loss(df[c]).mean()), 5) for c in cols}}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="docs/experiments/data/baseline_elo.json")
    ap.add_argument("--quick", action="store_true", help="one setting, no grid (for a smoke run)")
    args = ap.parse_args()
    rng = np.random.default_rng(20261017)
    m = be.load_matches(BASE)
    params, tried = tune(m, args.quick)
    pred = be.run(m, params)
    names = m.set_index("key")[["winner_name", "loser_name", "level"]]
    pred = pred.join(names, on="key")
    first = m.groupby(["tour", "tid"])["date"].min()
    pred["event_start"] = [first[(t, i)] for t, i in zip(pred["tour"], pred["tid"])]
    test = pred[(pred["date"].dt.year == 2026) & (pred["event_start"] < TEST_EVENTS_BEFORE)].copy()
    test["p_current"] = test["key"].map(current_engine(test, BASE))
    report = {"params": params.__dict__, "grid": tried, "test_2026_all": summary(test, ["p_winner"])}
    both = test.dropna(subset=["p_current"])
    report["test_2026_with_current_engine"] = {**summary(both, ["p_winner", "p_current"]),
                                               "elo_minus_current": paired(loss(both["p_winner"]), loss(both["p_current"]), rng)}
    j = join_market(test, market_close(BASE))
    jc = j.dropna(subset=["p_current"])
    report["test_2026_with_market"] = {
        **summary(j, ["p_winner", "market_winner"]),
        "elo_minus_market": paired(loss(j["p_winner"]), loss(j["market_winner"]), rng),
        "with_current_engine": {**summary(jc, ["p_winner", "p_current", "market_winner"]),
                                "elo_minus_current": paired(loss(jc["p_winner"]), loss(jc["p_current"]), rng),
                                "current_minus_market": paired(loss(jc["p_current"]), loss(jc["market_winner"]), rng)},
    }
    j["family"] = j["edition_key"].str.split("|").str[0]
    j["experience"] = pd.cut(np.minimum(j["n_winner"], j["n_loser"]), [-1, 9, 29, 99, 1e9], labels=["<10", "10-29", "30-99", "100+"])
    report["by_family"] = {f: summary(g, ["p_winner", "market_winner"]) for f, g in j.groupby("family")}
    report["by_experience"] = {str(e): summary(g, ["p_winner", "market_winner"]) for e, g in j.groupby("experience", observed=True)}
    out = BASE / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1, default=str) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
