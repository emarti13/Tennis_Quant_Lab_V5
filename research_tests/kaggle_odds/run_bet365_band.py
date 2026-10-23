"""Test 2 (pre-registered in docs/experiments/2026-10-23-prereg-intransitivity-bet365-band.md):
back the underdog at Bet365's closing price in a fixed price band, band chosen on 2014-2019,
judged on 2020-2025. Market-only: no model.

Run: python research_tests/kaggle_odds/run_bet365_band.py -> results_bet365_band.json
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_market_models as rm  # noqa: E402

BANDS = [(1.8, 2.2), (2.2, 2.6), (2.6, 3.2), (3.2, 4.0), (4.0, 6.0), (2.2, 4.0)]


def main():
    D = rm.load()
    oa, ob = D["bet365_A"].to_numpy(float), D["bet365_B"].to_numpy(float)
    ok = np.isfinite(oa) & np.isfinite(ob) & (oa > 1) & (ob > 1) & (oa != ob)
    dog_a = oa > ob
    price = np.where(dog_a, oa, ob)
    win = np.where(dog_a, D.y.to_numpy() == 1, D.y.to_numpy() == 0)
    ret = np.where(win, price - 1, -1.0)
    # the other three books' fair probability of the underdog
    L, n = np.zeros(len(D)), np.zeros(len(D))
    for b in ("Betfair", "Ladbrokes", "Unibet"):
        p = D[f"p_{b}_close"].to_numpy()
        f = np.isfinite(p)
        L += np.where(f, rm.lg(p), 0); n += f
    pa_oth = np.where(n > 0, rm.sig(L / np.maximum(n, 1)), np.nan)
    p_dog_oth = np.where(dog_a, pa_oth, 1 - pa_oth)
    ev_oth = p_dog_oth * price - 1                         # value claimed by the other books' fair price
    yr = D.kyear.to_numpy(); grp = D.group.to_numpy()
    disc, conf = ok & (yr <= 2019), ok & (yr >= 2020)
    R = {"discovery": {}, "rule": None}
    for lo, hi in BANDS:
        m = disc & (price >= lo) & (price < hi)
        R["discovery"][f"[{lo},{hi})"] = rm.boot_mean(ret[m])
    elig = {k: v for k, v in R["discovery"].items() if v.get("n", 0) >= 1000}
    best = max(elig, key=lambda k: elig[k]["mean"])
    R["chosen_band"] = best
    R["chosen_discovery"] = elig[best]
    if elig[best]["lo"] <= 0:
        R["rule"] = "no rule: the best discovery band's 95% range is not above zero"
    lo, hi = [float(x) for x in best.strip("[)").split(",")]
    m = conf & (price >= lo) & (price < hi)
    R["confirmation"] = {
        "all": rm.boot_mean(ret[m]),
        "by_group": {g: rm.boot_mean(ret[m & (grp == g)]) for g in ("ATP", "Challenger", "WTA")},
        "mean_value_vs_other_books_fair": rm.boot_mean(ev_oth[m]),
        "by_year": {int(Y): rm.boot_mean(ret[m & (yr == Y)]) for Y in range(2020, 2026)},
    }
    # reference, not part of the decision: every band on the confirmation years
    R["confirmation_all_bands_reference"] = {f"[{a},{b})": rm.boot_mean(ret[conf & (price >= a) & (price < b)])
                                             for a, b in BANDS}
    R["success"] = bool(R["rule"] is None and R["confirmation"]["all"]["lo"] > 0)
    json.dump(R, open(os.path.join(HERE, "results_bet365_band.json"), "w"), indent=1)
    print(json.dumps(R, indent=1))


if __name__ == "__main__":
    main()
