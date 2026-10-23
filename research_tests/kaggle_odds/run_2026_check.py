"""Step 3 re-check on 2026 (fixtures with true start before the 2026-10-13 seal).

Models are fit on the Kaggle years 2014-2024 (early stopping on 2025) exactly as in
run_market_models.fit_all, then applied to 2026 fixtures from market_history (OddsPapi) joined
to the same leak-free feature rows. The market offset is either
  exec : de-vigged consensus of BetRivers, DraftKings, Bet365 (soft books, like the training base)
  pin  : Pinnacle de-vigged
at the open or the close. Benchmarks: Pinnacle at the same checkpoint, and Pinnacle's close.
Bets: the side with the larger EV at the best execution-book price at that checkpoint (and per
book); returns and closing-line value against Pinnacle's close fair.

Run after run_market_models.py has been run once (it needs kaggle_joined.pkl and fs_market.pkl).
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_market_models as rm  # noqa: E402

SCRATCH = rm.SCRATCH
EXEC = ["betrivers", "draftkings", "bet365"]


def load_2026(F):
    mk = pd.read_pickle(os.path.join(SCRATCH, "fs_market.pkl"))
    F26 = F[F.year == 2026]
    x = F26.merge(mk[["key", "fixture_id", "a_key", "y", "start"] + [c for c in mk.columns if c.startswith("ml_")]],
                  on="key", suffixes=("", "_mk"))
    a_p1 = (x.a_key == x.a_key_mk).to_numpy()                  # features' A is fixture player1
    x["y"] = np.where(a_p1, x.y_mk, 1 - x.y_mk)
    for cp in ("open", "close"):
        L, n = np.zeros(len(x)), np.zeros(len(x))
        for b in EXEC + ["pinnacle"]:
            o1, o2 = x[f"ml_{cp}_{b}_p1"].to_numpy(float), x[f"ml_{cp}_{b}_p2"].to_numpy(float)
            oa, ob = np.where(a_p1, o1, o2), np.where(a_p1, o2, o1)
            x[f"{b}_{cp}_A"], x[f"{b}_{cp}_B"] = oa, ob
            ok = np.isfinite(oa) & np.isfinite(ob) & (oa > 1) & (ob > 1)
            p = np.where(ok, (1 / oa) / (1 / oa + 1 / ob), np.nan)
            x[f"p_{b}_{cp}"] = p
            if b != "pinnacle":
                L += np.where(ok, rm.lg(p), 0); n += ok
        x[f"exec_{cp}"] = np.where(n > 0, L / np.maximum(n, 1), np.nan)
        x[f"nexec_{cp}"] = n
        for s in ("A", "B"):
            x[f"bestx_{cp}_{s}"] = np.nanmax(np.column_stack([x[f"{b}_{cp}_{s}"] for b in EXEC]), 1)
    x["month"] = pd.to_datetime(x.start).dt.month.astype(float)
    return x


def main():
    D = rm.load()
    cols = rm.feature_cols(D)
    F = pd.read_pickle(os.path.join(rm.ROOT, "research_tests", "features", "features.pkl"))
    X26 = load_2026(F)
    R = {"fixtures_2026": int(len(X26))}
    tr = (D.kyear <= 2024).to_numpy(); va = (D.kyear == 2025).to_numpy()
    for base in ("open", "close"):
        M = rm.fit_all(D, tr, va, base, cols)
        for off in ("exec", "pin"):
            m = (X26[f"exec_{base}"] if off == "exec" else rm.lg(X26[f"p_pinnacle_{base}"])).to_numpy(float)
            ok = np.isfinite(m) & np.isfinite(X26[f"p_pinnacle_{base}"]) & np.isfinite(X26["p_pinnacle_close"])
            Xs = X26[ok].copy()
            Xs["move"] = (Xs.exec_close - Xs.exec_open) if off == "exec" else \
                (rm.lg(Xs.p_pinnacle_close) - rm.lg(Xs.p_pinnacle_open))
            Xs["nbooks_close"] = Xs.nexec_close if off == "exec" else 1.0
            P = rm.predict_all(M, Xs, m[ok], Xs.group.to_numpy())
            y = Xs.y.to_numpy(float)
            pin_same, pin_close = Xs[f"p_pinnacle_{base}"].to_numpy(), Xs.p_pinnacle_close.to_numpy()
            cell = {"n": int(ok.sum()), "logloss": {"pinnacle_same_time": round(float(rm.ll(y, pin_same).mean()), 5),
                                                    "pinnacle_close": round(float(rm.ll(y, pin_close).mean()), 5)}}
            for mdl in ["mkt"] + rm.MODELS:
                cell["logloss"][mdl] = round(float(rm.ll(y, P[mdl].to_numpy()).mean()), 5)
                cell[f"gain_vs_pinnacle_same_time|{mdl}"] = rm.boot_mean(rm.ll(y, pin_same) - rm.ll(y, P[mdl].to_numpy()))
            # bets at the best execution price at this checkpoint
            bets = {}
            for mdl in ("lgb_resid", "ens", "blend", "lgb_alone"):
                p = P[mdl].to_numpy()
                for bk in ["best"] + EXEC:
                    oa = Xs[f"bestx_{base}_A"].to_numpy() if bk == "best" else Xs[f"{bk}_{base}_A"].to_numpy(float)
                    ob = Xs[f"bestx_{base}_B"].to_numpy() if bk == "best" else Xs[f"{bk}_{base}_B"].to_numpy(float)
                    for thr in (0.0, 0.03):
                        ea, eb = p * oa - 1, (1 - p) * ob - 1
                        ta, tb = (ea > thr) & (ea >= eb), (eb > thr) & (eb > ea)
                        r_ = np.concatenate([np.where(y[ta] == 1, oa[ta] - 1, -1.0), np.where(y[tb] == 0, ob[tb] - 1, -1.0)])
                        clv = np.concatenate([oa[ta] * pin_close[ta] - 1, ob[tb] * (1 - pin_close[tb]) - 1])
                        if len(r_) >= 30:
                            bets[f"{mdl}|{bk}|ev>{thr:.2f}"] = {"roi": rm.boot_mean(r_), "clv_vs_pinnacle_close": rm.boot_mean(clv)}
            cell["bets"] = bets
            R[f"{base}|offset={off}"] = cell
            print(base, off, json.dumps(cell["logloss"]), flush=True)
    json.dump(R, open(os.path.join(HERE, "results_2026_check.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
