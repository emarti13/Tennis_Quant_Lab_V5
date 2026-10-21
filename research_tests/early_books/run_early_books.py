"""Does the feature model beat execution books' early prices? (research, 2026-10-21)

The feature model (research_tests/features, trained 2012-2024, early stopping on 2025, never fit
on 2026) gives P(player1) for 7,122 2026 fixtures (market_join.pkl: pm = model, pe = Elo,
open_p1/close_p1 = Pinnacle de-vigged). Bet a side at a book's price at a checkpoint (open,
t24h, t12h, t6h) when model EV = p * price - 1 exceeds a threshold. Two fair prices:
"model" (pm as is, nothing fit on 2026) and "blend" (logistic of logit(Pinnacle open) and
logit(pm), fit on January-June 2026, applied to July on). Optional gate: |pm - Pinnacle open|
>= 5 points. Return per dollar staked (95% range, resampling fixtures), closing-line value
against Pinnacle's close (fair close prob * price - 1), January-June and July-October halves.
Fixtures before 2026-10-13 only. Execution books: betrivers, draftkings, bet365.
"""
import glob
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

S = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
OUT = Path(__file__).with_name("results.json")
rng = np.random.default_rng(20261021)
lg = lambda p: np.log(np.clip(p, 1e-6, 1 - 1e-6) / (1 - np.clip(p, 1e-6, 1 - 1e-6)))  # noqa: E731

m = pd.read_pickle(S / "tests/features/market_join.pkl")
m = m[pd.to_datetime(m["start"], utc=True) < pd.Timestamp("2026-10-13", tz="UTC")].copy()
m["start"] = pd.to_datetime(m["start"], utc=True)
first = m["start"] < pd.Timestamp("2026-07-01", tz="UTC")
# blend fit on Jan-Jun only (Newton logistic, no intercept beyond a bias)
X = np.c_[lg(m["open_p1"]), lg(m["pm"]), np.ones(len(m))]
y = m["y"].to_numpy(float)
w = np.zeros(3)
for _ in range(50):
    p = 1 / (1 + np.exp(-X[first] @ w))
    g = X[first].T @ (p - y[first]) + 1e-3 * w
    h = (X[first] * (p * (1 - p))[:, None]).T @ X[first] + 1e-3 * np.eye(3)
    w -= np.linalg.solve(h, g)
m["pb"] = 1 / (1 + np.exp(-X @ w))

pts = pd.concat([pd.read_csv(f, dtype={"fixture_id": str}) for f in glob.glob("market_history/price_points/*.csv")])
pts = pts[(pts["market_group"] == "moneyline") & pts["fixture_id"].isin(m["fixture_id"])]
cols = {"open": "open_price", "t24h": "t24h_price", "t12h": "t12h_price", "t6h": "t6h_price"}
rows = []
for (fid, book), g in pts.groupby(["fixture_id", "bookmaker"]):
    if book == "pinnacle" or set(g["side"]) != {"p1", "p2"}:
        continue
    a, b = g[g["side"] == "p1"].iloc[0], g[g["side"] == "p2"].iloc[0]
    for cp, c in cols.items():
        if pd.notna(a[c]) and pd.notna(b[c]) and a[c] > 1 and b[c] > 1:
            rows.append({"fixture_id": fid, "book": book, "cp": cp, "o1": a[c], "o2": b[c]})
q = pd.DataFrame(rows).merge(m, on="fixture_id")


def boot(x, ids):
    if len(x) == 0:
        return None
    u, inv = np.unique(ids, return_inverse=True)
    s, c = np.bincount(inv, x), np.bincount(inv)
    idx = rng.integers(0, len(u), size=(2000, len(u)))
    means = s[idx].sum(1) / c[idx].sum(1)
    return [round(float(np.percentile(means, 2.5)), 4), round(float(np.percentile(means, 97.5)), 4)]


res = []
for fair in ("pm", "pb"):
    for gate in (False, True):
        for thr in (0.0, 0.03, 0.06):
            for cp in cols:
                for book in ("betrivers", "draftkings", "bet365", "any"):
                    d = q[q["cp"] == cp] if book == "any" else q[(q["cp"] == cp) & (q["book"] == book)]
                    if fair == "pb":
                        d = d[d["start"] >= pd.Timestamp("2026-07-01", tz="UTC")]
                    if gate:
                        d = d[(d["pm"] - d["open_p1"]).abs() >= 0.05]
                    p = d[fair].to_numpy()
                    ev1, ev2 = p * d["o1"] - 1, (1 - p) * d["o2"] - 1
                    pick1, pick2 = ev1 > thr, ev2 > thr
                    if book == "any":                       # best book per fixture and side
                        d = d.assign(ev1=ev1, ev2=ev2)
                        best1 = d.loc[d.groupby("fixture_id")["o1"].idxmax()]
                        best2 = d.loc[d.groupby("fixture_id")["o2"].idxmax()]
                        sel = [(best1[best1["ev1"] > thr], "o1", 1), (best2[best2["ev2"] > thr], "o2", 0)]
                    else:
                        sel = [(d[pick1.to_numpy()], "o1", 1), (d[pick2.to_numpy()], "o2", 0)]
                    r, clv, ids, half = [], [], [], []
                    for part, oc, side in sel:
                        won = part["y"] == side
                        r += list(np.where(won, part[oc] - 1, -1.0))
                        fc = part["close_p1"] if side == 1 else 1 - part["close_p1"]
                        clv += list(fc * part[oc] - 1)
                        ids += list(part["fixture_id"])
                        half += list(part["start"] < pd.Timestamp("2026-07-01", tz="UTC"))
                    r, clv, ids, half = map(np.asarray, (r, clv, ids, half))
                    cell = {"fair": fair, "gate5": gate, "ev_over": thr, "checkpoint": cp, "book": book, "bets": int(len(r))}
                    if len(r) >= 20:
                        cell.update(ret=round(float(r.mean()), 4), ret_ci95=boot(r, ids),
                                    clv=round(float(clv.mean()), 4), clv_ci95=boot(clv, ids),
                                    ret_jan_jun=round(float(r[half].mean()), 4) if half.any() else None,
                                    ret_jul_oct=round(float(r[~half].mean()), 4) if (~half).any() else None)
                    res.append(cell)
OUT.write_text(json.dumps({"blend_weights": w.round(4).tolist(), "cells": res}, indent=1) + "\n")
print(json.dumps({"blend_weights": w.round(4).tolist(), "n_cells": len(res)}))
