"""Timing-safe check of the 2026 DraftKings-open cell (run_2026_check.py).

The consensus or Pinnacle opening price used as the offset there is often not yet posted when
DraftKings opens (median 2 h earlier, research_tests/early_books). Here the only market input is
DraftKings' own de-vigged opening price, plus the pre-match features: all known at the bet.
"""
import json, os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import run_market_models as rm, run_2026_check as rc

D = rm.load(); cols = rm.feature_cols(D)
F = pd.read_pickle(os.path.join(rm.ROOT, "research_tests", "features", "features.pkl"))
X = rc.load_2026(F)
M = rm.fit_all(D, (D.kyear <= 2024).to_numpy(), (D.kyear == 2025).to_numpy(), "open", cols)
R = {}
for bk in ("draftkings", "betrivers"):
    m = rm.lg(X[f"p_{bk}_open"]).to_numpy(float)
    ok = np.isfinite(m) & np.isfinite(X.p_pinnacle_close)
    Xs = X[ok]
    P = rm.predict_all(M, Xs, m[ok], Xs.group.to_numpy())
    y = Xs.y.to_numpy(float); pin = Xs.p_pinnacle_close.to_numpy()
    oa, ob = Xs[f"{bk}_open_A"].to_numpy(float), Xs[f"{bk}_open_B"].to_numpy(float)
    for mdl in ("ens", "lgb_resid", "lr_resid", "blend"):
        p = P[mdl].to_numpy()
        for thr in (0.0, 0.03, 0.05):
            ea, eb = p * oa - 1, (1 - p) * ob - 1
            ta, tb = (ea > thr) & (ea >= eb), (eb > thr) & (eb > ea)
            r = np.concatenate([np.where(y[ta] == 1, oa[ta] - 1, -1.0), np.where(y[tb] == 0, ob[tb] - 1, -1.0)])
            clv = np.concatenate([oa[ta] * pin[ta] - 1, ob[tb] * (1 - pin[tb]) - 1])
            st = pd.to_datetime(np.concatenate([Xs.start.to_numpy()[ta], Xs.start.to_numpy()[tb]]), utc=True)
            h1 = st < pd.Timestamp("2026-06-01", tz="UTC")
            R[f"{bk}|{mdl}|ev>{thr:.2f}"] = {"roi": rm.boot_mean(r), "clv": rm.boot_mean(clv),
                                             "roi_jan_may": rm.boot_mean(r[h1]), "roi_jun_oct": rm.boot_mean(r[~h1]),
                                             "clv_jan_may": rm.boot_mean(clv[h1]), "clv_jun_oct": rm.boot_mean(clv[~h1])}
            print(bk, mdl, thr, json.dumps(R[f"{bk}|{mdl}|ev>{thr:.2f}"]))
    R[f"{bk}|logloss"] = {"book_open": round(float(rm.ll(y, P.mkt).mean()), 5), "ens": round(float(rm.ll(y, P.ens).mean()), 5),
                          "pinnacle_close": round(float(rm.ll(y, pin).mean()), 5), "n": int(ok.sum())}
    print(R[f"{bk}|logloss"])
json.dump(R, open(os.path.join(HERE, "results_dk_open.json"), "w"), indent=1)
