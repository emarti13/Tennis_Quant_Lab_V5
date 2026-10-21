"""First-server effect against the Kaggle bookmaker totals, 2014-2025 (Bet365, Ladbrokes, Unibet).

Same method as run_fs.py part E: serve level from each match's pre-match history, gap solved
from the de-vigged consensus close moneyline; the model's server shift is read at the line on
the market's quantile. Handicaps in the file are unusable (see kaggle_odds/join_odds.py).

E1  realised totals vs the model's prediction under the inferable selection
E2  open-to-close move of each book's over probability on the server shift (controls: result);
    the file has one line column, so rows whose open and close fair differ by more than 0.15
    (probably a line change) are dropped
E3  post-toss bets at each book's close, realised on the inferable subset vs the model's
    expectation for that subset; model-implied value if every toss is seen

Run after build_fs_table.py and kaggle_odds/join_odds.py: python research_tests/first_server/run_fs_kaggle.py
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fs_core as fc  # noqa: E402
from run_fs import aligned, invert_gap, mean_se, ols_ctrl, ols_slope, r4  # noqa: E402

SCRATCH = os.environ.get("FS_SCRATCH", "/tmp/claude-0/-home-user-Tennis-Quant-Lab-V5/a0609b44-84ba-59ef-a5f1-f66b68d375ec/scratchpad")
BOOKS = ["bet365", "Ladbrokes", "Unibet"]
ML_BOOKS = ["Betfair", "bet365", "Ladbrokes", "Unibet"]
RNG = np.random.default_rng(7)


def devig(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    ok = (a > 1) & (b > 1)
    return np.where(ok, (1 / a) / (1 / a + 1 / b), np.nan)


def build():
    t = pd.read_pickle(os.path.join(SCRATCH, "fs_table.pkl"))
    J = pd.read_pickle(os.path.join(SCRATCH, "kaggle_joined.pkl"))
    J = J.drop(columns=[c for c in ("tour", "tid", "level", "date", "y") if c in J])
    d = t.merge(J, on="key", how="inner")
    d = d[d.level.astype(str) != "D"].copy()
    L, n = np.zeros(len(d)), np.zeros(len(d))
    for b in ML_BOOKS:
        p = devig(d[f"{b}_A"], d[f"{b}_B"])
        ok = np.isfinite(p)
        L += np.where(ok, np.log(np.clip(p, 1e-6, 1) / np.clip(1 - p, 1e-6, 1)), 0); n += ok
    d["ml_close_fair"] = np.where(n > 0, 1 / (1 + np.exp(-L / np.maximum(n, 1))), np.nan)
    return d.reset_index(drop=True)


def shifts_for_book(d, b):
    """Rows with this book's close total; model pieces at the aligned line."""
    line, fo = d[f"{b}_tot_line"].to_numpy(float), devig(d[f"{b}_over"], d[f"{b}_under"])
    if b == "Ladbrokes":                       # 2017-18 lines are a scrape defect (lines of 2.5, overs 93-99%)
        line = np.where(d.mdate.dt.year.isin([2017, 2018]).to_numpy(), np.nan, line)
    g0 = d[np.isfinite(line) & np.isfinite(fo) & np.isfinite(d.pa_close)].copy()
    g0["fair"] = fo[g0.index]
    g0["line"] = line[g0.index]
    g0["fair_open"] = devig(d[f"{b}_over_opening"], d[f"{b}_under_opening"])[g0.index] if f"{b}_over_opening" in d else np.nan
    parts = []
    for (bo, rule), g in g0.groupby(["best_of", "rule"]):
        dA = fc.match_dist(g.pa_close.to_numpy(), g.pb_close.to_numpy(), int(bo), rule, True)
        dB = fc.match_dist(g.pa_close.to_numpy(), g.pb_close.to_numpy(), int(bo), rule, False)
        tail = lambda P: np.cumsum(P[:, ::-1], 1)[:, ::-1][:, 1:]
        PA, PB = dA["T_det"] + dA["T_ind"], dB["T_det"] + dB["T_ind"]
        jt = aligned(0.5 * (tail(PA) + tail(PB)), g.fair.to_numpy())
        r = np.arange(len(g))
        o = pd.DataFrame(index=g.index)
        for M, dd, P in (("A", dA, PA), ("B", dB, PB)):
            o[f"pover_{M}"] = tail(P)[r, jt]
            o[f"pdet_{M}"] = dd["T_det"].sum(1)
            o[f"poverdet_{M}"] = tail(dd["T_det"])[r, jt] / o[f"pdet_{M}"]
        parts.append(o)
    g0 = g0.join(pd.concat(parts))
    g0["pover_blind"] = 0.5 * (g0.pover_A + g0.pover_B)
    return g0


def ret(win, push, price):
    return np.where(push, 0.0, np.where(win, price - 1, -1.0))


def main():
    d = build()
    d["pa_close"], d["pb_close"] = invert_gap(d, "close")
    R = {"rows": int(len(d)), "with_server": int(d.first_a.notna().sum())}
    for b in BOOKS:
        g = shifts_for_book(d, b)
        out = {"fixtures": int(len(g)), "mean_abs_pover_shift": r4(np.mean(np.abs(g.pover_A - g.pover_blind)))}
        k = g[g.first_a.notna()].copy()
        fa = k.first_a.to_numpy() == 1
        y = (k["T"] > k.line).astype(float).to_numpy()
        push = (k["T"] == k.line).to_numpy()
        w = (k.pdet_A / (k.pdet_A + k.pdet_B)).to_numpy()
        pM = np.where(fa, k.poverdet_A, k.poverdet_B)
        pbl = w * k.poverdet_A + (1 - w) * k.poverdet_B
        out["E1_beta_totals"] = ols_slope((y - pbl)[~push], (pM - pbl)[~push])
        z = (np.where(fa, k.pover_A, k.pover_B) - k.pover_blind).to_numpy()
        mv = (k.fair - k.fair_open).to_numpy()
        ok = np.isfinite(mv) & (np.abs(mv) < 0.15)
        ctrl = np.c_[k.y.to_numpy(float), k["H"].to_numpy(float), k["T"].to_numpy(float)]
        e2 = ols_ctrl(mv[ok], z[ok], ctrl[ok])
        plac = []
        for _ in range(200):
            fz = RNG.random(len(k)) < w
            zz = (np.where(fz, k.pover_A, k.pover_B) - k.pover_blind).to_numpy()
            plac.append(ols_ctrl(mv[ok], zz[ok], ctrl[ok])["beta"])
        out["E2_open_to_close_move_on_shift"] = {**e2, "placebo_mean": r4(np.mean(plac)), "placebo_sd": r4(np.std(plac)),
                                                 "share_moved": r4(np.mean(np.abs(mv[ok]) > 1e-9))}
        # E3 post-toss bets at this book's close
        po, pu = k[f"{b}_over"].to_numpy(float), k[f"{b}_under"].to_numpy(float)
        fair = k.fair.to_numpy() + z
        cells = {}
        for thr in (0.0, 0.02):
            ea, eb = fair * po - 1, (1 - fair) * pu - 1
            ta, tb = (ea > thr) & (ea >= eb), (eb > thr) & (eb > ea)
            r_ = np.concatenate([ret(y[ta] == 1, push[ta], po[ta]), ret(y[tb] == 0, push[tb], pu[tb])])
            exp = np.concatenate([pM[ta] * po[ta] - 1, (1 - pM[tb]) * pu[tb] - 1])
            cells[f"ev>{thr:.2f}"] = {"bets": int(len(r_)), "realised": mean_se(r_) if len(r_) > 1 else None,
                                      "model_expected_same_selection": r4(np.mean(exp)) if len(exp) else None}
        out["E3_post_toss_inferable_subset"] = cells
        # model-implied over all fixtures with a fair toss
        evs, nb = [], 0
        poa, pua = g[f"{b}_over"].to_numpy(float), g[f"{b}_under"].to_numpy(float)
        for pMx in (g.pover_A, g.pover_B):
            f_ = g.fair.to_numpy() + (pMx - g.pover_blind).to_numpy()
            best = np.fmax(f_ * poa - 1, (1 - f_) * pua - 1)
            evs.append(np.where(best > 0, best, 0.0)); nb += np.nansum(best > 0)
        out["E3b_model_implied_all"] = {"bet_share": r4(nb / 2 / len(g)),
                                        "EV_per_bet": r4(np.nansum(0.5 * (evs[0] + evs[1])) / max(nb / 2, 1))}
        # book's own calibration of totals (no server): sanity
        yy = (g["T"] > g.line).to_numpy(float); pp = (g["T"] != g.line).to_numpy()
        out["over_rate_vs_fair"] = {"over_rate": r4(yy[pp].mean()), "mean_fair": r4(g.fair.to_numpy()[pp].mean())}
        R[b] = out
        print(b, json.dumps(out), flush=True)
    json.dump(R, open(os.path.join(HERE, "results_kaggle_totals.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
