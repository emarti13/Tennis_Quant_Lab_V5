"""Freeze the blend weights for the Kalshi forward test (registration 2026-11-04, Kalshi blend at the open).

Usage:  python research_tests/open_clv/freeze_kalshi_blend.py JOINED_PKL CANON_PKL HISTORY_DIR EVENTS_CSV ELEV_CSV OUT_JSON

The live tracker can only build the inputs that come from the TennisMyLife results (ages, entry codes,
ranks, rounds, earlier matches). It cannot yet build the ones that need start times or venue
coordinates (jet_lag, short_rest, rest_diff, altitude), or the dates of the next Grand Slam before it
starts (pre_slam, bubble_main, bubble_quali). So the frozen model uses only LIVE_INPUTS:

  model:  P(A wins) = sigmoid(w_open * logit(p_open) + sum_i w_i * x_i), no intercept, so swapping A and B
          gives exactly 1 - P (the live tracker does not know a "first" player). Logistic, L2, C = 0.3.
  fit:    every 2016-2025 odds match, p_open = de-vigged bet365 opening price (as run_open_clv.py).
  report: the same model walk-forward (trained on earlier years only), test 2022-2025: log loss against the
          open and the close, and bets at edge >= 3 points at the bet365 open (CLV-expected and realised ROI),
          so the reduced input set can be compared with the full blend in run_open_clv.py.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_open_clv as oc  # noqa: E402
from research_kit import provenance  # noqa: E402
from research_kit.core import boot_mean, log_loss, logit, walk_forward  # noqa: E402

LIVE_INPUTS = ["age_gap", "qualifier", "season_end", "wildcard", "defending", "hangover", "venue", "layoff",
               "surface", "surface_spec", "freepass"]
C_REG = 0.3


def design(df):
    return np.column_stack([logit(df["p_open"].to_numpy())] + [df[c].to_numpy(float) for c in LIVE_INPUTS])


def main() -> int:
    from sklearn.linear_model import LogisticRegression
    args = sys.argv[1:7]
    _, df, orient_ok = oc.inputs_frame(*args[:5])
    X, y = design(df), df["y"].to_numpy()
    fit = lambda tr: LogisticRegression(C=C_REG, fit_intercept=False, max_iter=2000).fit(X[tr], y[tr])
    full = fit(np.ones(len(df), bool))
    w = dict(zip(["open"] + LIVE_INPUTS, [float(v) for v in full.coef_[0]]))
    p = walk_forward(df["year"].to_numpy(), oc.TEST_YEARS, lambda tr, te: fit(tr).predict_proba(X[te])[:, 1], first_train_year=2016)
    m = df["year"].isin(oc.TEST_YEARS).to_numpy() & np.isfinite(p)
    p0 = df["p_open"].to_numpy()
    sub = df[m].reset_index(drop=True)
    pm = p[m]
    ea, eb = pm - 1 / sub["oa_open"], (1 - pm) - 1 / sub["ob_open"]
    side_a = (ea >= 0.03) & (ea >= eb)
    pick = (side_a | ((eb >= 0.03) & (eb > ea))).to_numpy()
    out = {"model": "P(A) = sigmoid(open * logit(p_open_A) + sum w_i * x_i); x_i = A minus B; no intercept",
           "inputs": LIVE_INPUTS, "weights": {k: round(v, 6) for k, v in w.items()}, "C": C_REG,
           "fit_rows": int(len(df)), "fit_years": "2016-2025", "orientation agrees across builds": orient_ok,
           "check (walk-forward, test 2022-25)": {
               "M minus open, log loss": [round(v, 5) for v in boot_mean(log_loss(y[m], pm) - log_loss(y[m], p0[m]), seed=oc.SEED)],
               "M minus close, log loss": [round(v, 5) for v in boot_mean(log_loss(y[m], pm) - log_loss(y[m], df["p_close"].to_numpy()[m]), seed=oc.SEED)],
               "edge >= 3 at bet365 open": oc.bet_stats(sub[pick].reset_index(drop=True), side_a.to_numpy()[pick])},
           "manifest": provenance.manifest(dict(zip(["joined", "canon", "history", "events", "elev"], args[:5])),
                                           {"orientation": oc.SEED}, " ".join(["python"] + sys.argv))}
    Path(args[5]).write_text(json.dumps(out, indent=1, default=str) + "\n")
    print(json.dumps({k: v for k, v in out.items() if k != "manifest"}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
