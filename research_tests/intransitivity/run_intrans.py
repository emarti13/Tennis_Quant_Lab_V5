"""Test 1 (pre-registered in docs/experiments/2026-10-23-prereg-intransitivity-bet365-band.md):
does the market do relatively worse on intransitive matchups (Clegg & Cartlidge 2025)?

I* per match is built only from events that had finished before the match's event began. An
event counts as finished after its first week + 2 weeks (Slams, Masters / WTA 1000) or
+ 1 week (all others): stricter than the repo's visibility rule, so a two-week event can never
feed matches still being played.

Run: python research_tests/intransitivity/run_intrans.py -> results.json next to this file
"""
from __future__ import annotations

import json
import math
import os
import sys
import time

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "research_tests", "kaggle_odds"))
sys.path.insert(0, os.path.join(ROOT, "research_tests", "first_server"))
import v5_baseline_elo as be  # noqa: E402
from v5_fatigue_features import event_table  # noqa: E402
import fs_core as fc  # noqa: E402
import run_market_models as rm  # noqa: E402
from post_bets import odds_kind  # noqa: E402

LAM = 0.38                                     # per year
SURF = {"Hard": 0, "Clay": 1, "Grass": 2}
# ALPHA[target][source]: transfer from the source surface to the target (paper Table 3)
ALPHA = np.array([[1.0, 0.01, 0.37],           # target hard  <- hard, clay, grass
                  [0.07, 1.0, 0.09],           # target clay  <- hard, clay, grass
                  [0.45, 0.05, 1.0]])          # target grass <- hard, clay, grass
BETA = {"G": 1.0, "F": 0.94, "M": 0.85, "1000": 0.85, "PM": 0.85, "P5": 0.85, "500": 0.69, "P": 0.69}
BETA_OTHER = 0.5
MAX_COMMON = 25
GRID = [1.0, 1.5, 2.0, 2.55, 3.0, 4.0]


def games_share(score):
    s = fc.parse_sets(score)
    if not s:
        return None
    w = sum(a for a, b, _ in s); l = sum(b for a, b, _ in s)
    return w / (w + l) if w + l else None


class Store:
    """Per pair (i < j): sums over matches of beta*e^(lam t)*g_i and beta*e^(lam t), by match surface."""

    def __init__(self):
        self.num, self.den = {}, {}
        self.nb = {}

    def add(self, i, j, g_i, t, surf, beta):
        if i > j:
            i, j, g_i = j, i, 1 - g_i
        k = (i, j)
        if k not in self.num:
            self.num[k], self.den[k] = np.zeros(3), np.zeros(3)
            self.nb.setdefault(i, set()).add(j); self.nb.setdefault(j, set()).add(i)
        w = beta * math.exp(LAM * t)
        self.num[k][surf] += w * g_i
        self.den[k][surf] += w

    def dom(self, i, j, s):
        """(D(i over j) on target surface s, raw weighted denominator) or None."""
        flip = i > j
        k = (j, i) if flip else (i, j)
        if k not in self.num:
            return None
        a = ALPHA[s]
        den = float(a @ self.den[k])
        if den <= 0:
            return None
        d = float(a @ self.num[k]) / den
        return (1 - d if flip else d), den


def intransitivity(store, u, v, s, t):
    duv = store.dom(u, v, s)
    if duv is None:
        return 0.0, 0.0
    evid_uv = duv[1] * math.exp(-LAM * t)
    common = store.nb.get(u, set()) & store.nb.get(v, set())
    scored = []
    for c in common:
        a, b = store.dom(u, c, s), store.dom(v, c, s)
        if a and b:
            scored.append((min(a[1], b[1]), c))
    scored.sort(reverse=True)
    nodes = [u, v] + [c for _, c in scored[:MAX_COMMON]]
    idx = {p: n for n, p in enumerate(nodes)}
    rows, vals = [], []
    for x in range(len(nodes)):
        for y in range(x + 1, len(nodes)):
            d = store.dom(nodes[x], nodes[y], s)
            if d is None:
                continue
            p = min(max(d[0], 0.02), 0.98)
            rows.append((x, y)); vals.append(math.log(p / (1 - p)))
    B = np.zeros((len(rows), len(nodes)))
    for r, (x, y) in enumerate(rows):
        B[r, x], B[r, y] = 1.0, -1.0
    a = np.array(vals)
    pot, *_ = np.linalg.lstsq(B, a, rcond=None)
    grad = B @ pot
    I = (1 + np.linalg.norm(a - grad)) / (1 + np.linalg.norm(grad))
    return float(I * math.sqrt(evid_uv)), math.sqrt(evid_uv)


def build_istar(target_keys):
    m = be.load_matches(ROOT)
    m = m[m.date < pd.Timestamp("2026-10-12")].copy()
    ev = event_table(m)
    ev["span"] = np.where(ev.level.astype(str).isin(["G", "M", "1000", "PM"]), 2, 1)
    ev["done_week"] = ev.first_week + ev.span              # visible once done_week < first_week of the asker
    m["g"] = [games_share(s) if not (w or r) else None for s, w, r in zip(m.score, m.walkover, m.retired)]
    m["t"] = (m.date - pd.Timestamp("2000-01-01")).dt.days / 365.25
    m["s"] = m.surface.map(be.surface_of).map(SURF).fillna(0).astype(int)
    m["beta"] = m.level.astype(str).map(BETA).fillna(BETA_OTHER)
    store = Store()
    by_ev = {k: g for k, g in m.groupby(["tour", "tid"])}
    order = ev.sort_values("first_week").index.tolist()
    pending = sorted(order, key=lambda e: ev.at[e, "done_week"])
    pi = 0
    out = {}
    t0 = time.time()
    for n, e in enumerate(order):
        fw = ev.at[e, "first_week"]
        while pi < len(pending) and ev.at[pending[pi], "done_week"] < fw:
            for r in by_ev[pending[pi]].itertuples():
                if pd.notna(r.g) and isinstance(r.winner_key, str) and isinstance(r.loser_key, str):
                    store.add(r.winner_key, r.loser_key, r.g, r.t, r.s, r.beta)
            pi += 1
        g = by_ev[e]
        for r in g.itertuples():
            if r.key in target_keys:
                out[r.key] = intransitivity(store, r.winner_key, r.loser_key, r.s, r.t)
        if n % 1000 == 0:
            print("event", n, len(order), f"{time.time() - t0:.0f}s", flush=True)
    return out


def diff_boot(a, b, reps=2000):
    a, b = np.asarray(a), np.asarray(b)
    ia = rm.RNG.integers(0, len(a), size=(reps, len(a))); ib = rm.RNG.integers(0, len(b), size=(reps, len(b)))
    d = a[ia].mean(1) - b[ib].mean(1)
    return {"diff": round(float(a.mean() - b.mean()), 5), "lo": round(float(np.percentile(d, 2.5)), 5),
            "hi": round(float(np.percentile(d, 97.5)), 5), "n_top": int(len(a)), "n_bin0": int(len(b))}


def main():
    D = rm.load()
    P = pd.read_pickle(os.path.join(rm.SCRATCH, "kaggle_preds_close.pkl"))
    dd = D.loc[P.index].copy()
    ist = build_istar(set(dd.key))
    dd["istar"] = [ist.get(k, (np.nan, np.nan))[0] for k in dd.key]
    y = dd.y.to_numpy(float)
    gain = rm.ll(y, P.mkt.to_numpy()) - rm.ll(y, P.ens.to_numpy())      # > 0: ensemble beats the consensus close
    yr = dd.kyear.to_numpy(); I = dd.istar.to_numpy(); grp = dd.group.to_numpy()
    ok = np.isfinite(I)
    pos_disc = I[ok & (yr <= 2021) & (I > 0)]
    cuts = np.percentile(pos_disc, [100 / 3, 200 / 3])
    binv = np.where(~ok, -1, np.where(I == 0, 0, np.where(I < cuts[0], 1, np.where(I < cuts[1], 2, 3))))
    R = {"n": int(ok.sum()), "share_istar_zero": round(float(np.mean(I[ok] == 0)), 4),
         "tertile_cuts_2017_21": [round(float(c), 3) for c in cuts], "bins": {}}
    for per, pm in (("2017_21", yr <= 2021), ("2022_25", yr >= 2022)):
        for b in range(4):
            R["bins"][f"{per}|bin{b}"] = rm.boot_mean(gain[pm & (binv == b)])
        for g in ("WTA", "ATP", "Challenger"):
            for b in (0, 3):
                R["bins"][f"{per}|{g}|bin{b}"] = rm.boot_mean(gain[pm & (binv == b) & (grp == g)])
    conf = yr >= 2022
    R["test_top_minus_bin0_2022_25"] = diff_boot(gain[conf & (binv == 3)], gain[conf & (binv == 0)])
    R["success_logloss"] = bool(R["test_top_minus_bin0_2022_25"]["lo"] > 0)
    # betting check: ensemble EV > 0 and I* >= gamma, gamma chosen on 2017-21 at Bet365
    p = P.ens.to_numpy()
    res = {}
    for kind in ("bet365", "books_avg", "betfair_net"):
        oa, ob = odds_kind(dd, kind, "", "A"), odds_kind(dd, kind, "", "B")
        ea, eb = p * oa - 1, (1 - p) * ob - 1
        ta, tb = (ea > 0) & (ea >= eb), (eb > 0) & (eb > ea)
        r = np.where(ta, np.where(y == 1, oa - 1, -1.0), np.where(tb, np.where(y == 0, ob - 1, -1.0), np.nan))
        res[kind] = r
    disc_cells = {}
    for gm in GRID:
        sel = (yr <= 2021) & (I >= gm) & np.isfinite(res["bet365"])
        if sel.sum() >= 300:
            disc_cells[gm] = rm.boot_mean(res["bet365"][sel])
    R["betting_discovery_bet365"] = {str(k): v for k, v in disc_cells.items()}
    if disc_cells:
        gbest = max(disc_cells, key=lambda k: disc_cells[k]["mean"])
        R["gamma_chosen"] = gbest
        R["betting_confirmation_2022_25"] = {}
        for kind, r in res.items():
            sel = conf & (I >= gbest) & np.isfinite(r)
            R["betting_confirmation_2022_25"][kind] = rm.boot_mean(r[sel])
            for g in ("WTA", "ATP", "Challenger"):
                R["betting_confirmation_2022_25"][f"{kind}|{g}"] = rm.boot_mean(r[sel & (grp == g)])
    dd[["key", "istar"]].to_pickle(os.path.join(rm.SCRATCH, "istar.pkl"))
    json.dump(R, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    print(json.dumps(R, indent=1))


if __name__ == "__main__":
    main()
