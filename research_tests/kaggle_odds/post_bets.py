"""Betting returns from the rolling predictions at executable prices.

run_market_models.py reports the file's best odds (max over many scraped books: not executable)
and a four-book average (including Betfair before commission). Here: Bet365 alone (the
execution book in this file, CLAUDE.md), the mean of the three bookmakers (Bet365, Ladbrokes,
Unibet), Betfair net of 5% commission on winnings, and best odds for reference. One bet per
match on the side with the larger EV above the threshold; the open base bets at the opening
price and also reports closing-line value against the consensus close.

Run after run_market_models.py: python research_tests/kaggle_odds/post_bets.py
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
from qa import QA  # noqa: E402

COMMISSION = 0.05


def odds_kind(dd, kind, suf, s):
    if kind == "bet365":
        return dd[f"bet365{suf}_{s}"].to_numpy(float)
    if kind == "books_avg":
        o = np.column_stack([dd[f"{b}{suf}_{s}"].to_numpy(float) for b in ("bet365", "Ladbrokes", "Unibet")])
        o[o <= 1] = np.nan
        return np.nanmean(o, 1)
    if kind == "betfair_net":
        o = dd[f"Betfair{suf}_{s}"].to_numpy(float)
        return 1 + (o - 1) * (1 - COMMISSION)
    return dd[f"best{suf}_{s}"].to_numpy(float)


def main():
    D = rm.load()
    R = {}
    for base in ("close", "open"):
        P = pd.read_pickle(os.path.join(rm.SCRATCH, f"kaggle_preds_{base}.pkl"))
        dd = D.loc[P.index]
        suf = "" if base == "close" else "_opening"
        y = dd.y.to_numpy()
        pc = rm.sig(dd.mkt_close.to_numpy())
        yr = dd.kyear.to_numpy()
        grp = dd.group.to_numpy()
        for model in ("ens", "lgb_resid", "lr_resid", "lgb_group"):
            p = P[model].to_numpy()
            for kind in ("bet365", "books_avg", "betfair_net", "best"):
                oa, ob = odds_kind(dd, kind, suf, "A"), odds_kind(dd, kind, suf, "B")
                for thr in (0.0, 0.02, 0.05):
                    ea, eb = p * oa - 1, (1 - p) * ob - 1
                    ta, tb = (ea > thr) & (ea >= eb), (eb > thr) & (eb > ea)
                    sel = ta | tb
                    ret = np.where(ta, np.where(y == 1, oa - 1, -1.0), np.where(y == 0, ob - 1, -1.0))[sel]
                    clv = np.where(ta, oa * pc - 1, ob * (1 - pc) - 1)[sel]
                    if sel.sum() < 50:
                        continue
                    cell = {"all": rm.boot_mean(ret), "disc_2017_21": rm.boot_mean(ret[yr[sel] <= 2021]),
                            "conf_2022_25": rm.boot_mean(ret[yr[sel] >= 2022]),
                            "by_group": {g: rm.boot_mean(ret[grp[sel] == g]) for g in ("ATP", "Challenger", "WTA")}}
                    if base == "open":
                        cell["clv_vs_close_consensus"] = rm.boot_mean(clv)
                    R[f"{base}|{model}|{kind}|ev>{thr:.2f}"] = cell
        # market alone: back every side at Bet365 (the book's margin), for reference
        for kind in ("bet365", "books_avg", "betfair_net"):
            oa, ob = odds_kind(dd, kind, suf, "A"), odds_kind(dd, kind, suf, "B")
            r = np.r_[np.where(y == 1, oa - 1, -1.0), np.where(y == 0, ob - 1, -1.0)]
            R[f"{base}|back_everything|{kind}"] = rm.boot_mean(r)
    qa = QA("post_bets")
    for base in ("close", "open"):
        for kind, lo, hi in (("bet365", -0.13, -0.05), ("books_avg", -0.12, -0.04)):
            qa.check(f"{base}: backing every side at {kind} loses about the margin", R[f"{base}|back_everything|{kind}"]["mean"], lo, hi)
    qa.save(HERE)
    json.dump(R, open(os.path.join(HERE, "results_post_bets.json"), "w"), indent=1)
    for k, v in R.items():
        a = v.get("all", v)
        print(k, a.get("n"), a.get("mean"), a.get("lo"), a.get("hi"),
              "| conf", v.get("conf_2022_25", {}).get("mean") if isinstance(v, dict) and "conf_2022_25" in v else "")


if __name__ == "__main__":
    main()
