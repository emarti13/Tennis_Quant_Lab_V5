#!/usr/bin/env python3
import warnings
warnings.filterwarnings("ignore")
"""Market-only edge search on the 2014-2025 tennis odds dataset (300,059 rows).

Usage:  python -I run_market.py <path to tennis_matches_2014_2025.csv>

Reads the CSV with pandas only. Writes results.json next to this script.

Protocol
- player_a is always the winner in the file. Every match is re-oriented by a seeded coin flip
  (SEED) into p1/p2; the label y = 1 if p1 won. All odds are re-oriented with it.
- Void: only comment == 'completed' matches are settled (retired_or_abandoned, not_played,
  incomplete, invalid_score excluded). Player history uses every played row (not not_played).
- Periods: train 2014-2021 (all choices), val 2022-2023 (confirm), test 2024-2025 (final).
  Nothing from val/test is used to choose rules, thresholds or model settings.
- Level: tournament name contains 'challenger' -> challenger; contains 'itf' -> ITF; else main.
  Gender: connected components of the player graph (men and women never meet); a component
  is men if it contains any ATP-tagged non-ITF match. The file's 'tour' column tags all ITF
  rows WTA, but 93 ITF rows are men's (component check). Qualifying rounds are not present.
- Return per dollar at executable prices: bet365 / Ladbrokes / Unibet / best_odds; Betfair
  (and best_odds when the best is Betfair) minus 2% commission on net winnings.
- CLV = odds * p_fair(Betfair close, multiplicative de-vig) - 1, where Betfair close is valid.
- Every rule is recorded. 95% ranges: delta-method for all rules; bootstrap over matches
  (B=1000) for every rule positive in both val and test, or credibly positive on train.
"""
import json
import os
import sys
import time

import numpy as np
import pandas as pd

SEED = 20261021
T0 = time.time()
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
OUT = os.path.join(HERE, "results.json")
B_BOOT = 1000
COMM = 0.02
PERIODS = ["train", "val", "test"]


def log(*a):
    print(f"[{time.time() - T0:6.0f}s]", *a, flush=True)


# ------------------------------------------------------------------ load & clean
df = pd.read_csv(DATA, low_memory=False)
meta = {"n_raw": int(len(df)), "seed": SEED}
df = df[df.player_a_url.notna() & df.player_b_url.notna()]
df = df[~df.tournament.str.contains("exhibition", case=False, na=False)]
df = df.drop_duplicates(["match_date_formatted", "player_a_url", "player_b_url"]).reset_index(drop=True)
meta["n_after_clean"] = int(len(df))
dt = pd.to_datetime(df.match_date_formatted)
df["day"] = dt.dt.normalize()
df["year"] = dt.dt.year
df["month"] = dt.dt.month
N = len(df)

# gender by player-graph components
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

codes, uni = pd.factorize(pd.concat([df.player_a_url, df.player_b_url]))
ca, cb = codes[:N], codes[N:]
_, comp = connected_components(coo_matrix((np.ones(N), (ca, cb)), shape=(len(uni), len(uni))), directed=False)
tl = df.tournament.str.lower()
is_itf = tl.str.contains("itf").values
is_ch = tl.str.contains("challenger").values
men_comps = set(comp[ca][(~is_itf) & (df.tour.values == "ATP")])
male = np.isin(comp[ca], list(men_comps))
level = np.where(is_ch, "challenger", np.where(is_itf, np.where(male, "itf_m", "itf_w"),
                                               np.where(male, "atp_main", "wta_main")))
df["level"] = level
meta["level_counts"] = df.level.value_counts().to_dict()
meta["level_rule"] = ("name contains 'challenger' -> challenger; contains 'itf' -> ITF (gender from player-graph "
                      "component); else ATP/WTA main by component. No W15/M25 tags or qualifying rounds in the file.")
ok = (df.comment == "completed").values
meta["void_counts"] = df.comment.value_counts().to_dict()
yr = df.year.values
per = np.where(yr <= 2021, "train", np.where(yr <= 2023, "val", "test"))
meta["period_counts_completed"] = pd.Series(per[ok]).value_counts().to_dict()

# coin flip orientation
rng = np.random.default_rng(SEED)
s = rng.random(N) < 0.5  # True: p1 = player_a (winner)
y = s.astype(int)


def orient(ca_, cb_):
    a = df[ca_].values.astype(float)
    b = df[cb_].values.astype(float)
    return np.where(s, a, b), np.where(s, b, a)


SOFT = ["bet365", "Ladbrokes", "Unibet"]
O = {}
for bk in SOFT + ["Betfair", "best"]:
    for t, suf in [("close", ""), ("open", "_opening")]:
        o1, o2 = orient(f"{bk}_odds_a{suf}", f"{bk}_odds_b{suf}")
        bad = ~((o1 > 1.0) & (o2 > 1.0) & np.isfinite(o1) & np.isfinite(o2))
        ovr = 1 / o1 + 1 / o2
        if bk in SOFT:
            bad |= (ovr < 1.0) | (ovr > 1.25)
        elif bk == "Betfair":
            bad |= (ovr < 0.99) | (ovr > 1.10)  # opening exchange prices are mostly placeholders
        o1[bad] = np.nan
        o2[bad] = np.nan
        O[(bk, t)] = (o1, o2)
# best odds: must be >= every soft book on that side and overround >= 0.95
for t in ["close", "open"]:
    b1, b2 = O[("best", t)]
    for side, bb in [(0, b1), (1, b2)]:
        mx = np.nanmax(np.vstack([O[(bk, t)][side] for bk in SOFT]), axis=0)
        bb[(bb < mx - 1e-9)] = np.nan
    ov = 1 / b1 + 1 / b2
    bad = ov < 0.95
    b1[bad] = np.nan
    b2[bad] = np.nan
# commission flag for best (Betfair best)
bka = df.best_odds_a_bookmaker.values
bkb = df.best_odds_b_bookmaker.values
best_is_bf_close = (np.where(s, bka, bkb) == "Betfair", np.where(s, bkb, bka) == "Betfair")
rawbf_o = orient("Betfair_odds_a_opening", "Betfair_odds_b_opening")
best_is_bf_open = (np.isclose(O[("best", "open")][0], rawbf_o[0]), np.isclose(O[("best", "open")][1], rawbf_o[1]))
meta["valid_share_completed"] = {f"{k[0]}_{k[1]}": float(np.isfinite(v[0][ok]).mean()) for k, v in O.items()}


def fair(bk, t):
    o1, o2 = O[(bk, t)]
    return (1 / o1) / (1 / o1 + 1 / o2)


P = {k: fair(*k) for k in O if k[0] != "best"}
for t in ["close", "open"]:
    P[("cons", t)] = np.nanmean(np.vstack([P[(bk, t)] for bk in SOFT]), axis=0)
    o1s = np.nanmax(np.vstack([O[(bk, t)][0] for bk in SOFT]), axis=0)
    o2s = np.nanmax(np.vstack([O[(bk, t)][1] for bk in SOFT]), axis=0)
    O[("softbest", t)] = (o1s, o2s)
pbfc = P[("Betfair", "close")]


def logit(p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def ll(p, yy):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return -(yy * np.log(p) + (1 - yy) * np.log(1 - p))


# ------------------------------------------------------------------ rule engine
RULES = []
brng = np.random.default_rng(SEED + 1)


def ratio_ci(pr, st):
    n = len(pr)
    R = pr.sum() / st.sum()
    if n < 3:
        return R, np.nan, np.nan
    sb = st.mean()
    se = np.std(pr - R * st, ddof=1) / (np.sqrt(n) * sb)
    return R, R - 1.96 * se, R + 1.96 * se


def boot_ci(pr, st, B=B_BOOT):
    n = len(pr)
    if n < 5:
        return [np.nan, np.nan]
    out = []
    chunk = max(1, int(4e6 // n))
    done = 0
    while done < B:
        k = min(chunk, B - done)
        idx = brng.integers(0, n, (k, n))
        out.append(pr[idx].sum(1) / st[idx].sum(1))
        done += k
    out = np.concatenate(out)
    return [float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5))]


def settle(o, w, comm):
    return np.where(w, (o - 1) * (1 - comm), -1.0)


def add_rule(family, name, b1, b2, o1, o2, c1=0.0, c2=0.0, mask=None, params=None, decided="close",
             sub=None, ysub=None, clvref=None):
    """b1/b2 boolean arrays (bet p1 / p2), o1/o2 odds, c1/c2 commission. sub: index subset (for
    row-level markets such as totals, pass arrays already aligned and ysub = win flags)."""
    if sub is None:
        base = ok if mask is None else (ok & mask)
        w1, w2 = (y == 1), (y == 0)
        perr = per
        ref1, ref2 = pbfc, 1 - pbfc
    else:
        base = np.ones(len(b1), bool) if mask is None else mask
        w1, w2 = ysub
        perr = per[sub]
        ref1, ref2 = clvref if clvref is not None else (np.full(len(b1), np.nan),) * 2
    b1 = b1 & base & np.isfinite(o1)
    b2 = b2 & base & np.isfinite(o2)
    c1 = np.broadcast_to(c1, b1.shape)
    c2 = np.broadcast_to(c2, b2.shape)
    pr = np.zeros(len(b1))
    st = np.zeros(len(b1))
    clv_sum = np.zeros(len(b1))
    clv_n = np.zeros(len(b1))
    oo = np.where(np.isfinite(o1), o1, 0)
    pr += np.where(b1, settle(oo, w1, c1), 0)
    st += b1
    oo2 = np.where(np.isfinite(o2), o2, 0)
    pr += np.where(b2, settle(oo2, w2, c2), 0)
    st += b2
    v1 = b1 & np.isfinite(ref1)
    v2 = b2 & np.isfinite(ref2)
    clv_sum += np.where(v1, oo * (1 - c1) * ref1 - 1 + 0 * c1, 0) + np.where(v2, oo2 * (1 - c2) * ref2 - 1, 0)
    clv_n += v1.astype(int) + v2.astype(int)
    oddsum = np.where(b1, oo, 0) + np.where(b2, oo2, 0)
    rec = {"family": family, "name": name, "decided": decided, "params": params or {}}
    sel = st > 0
    for P_ in PERIODS:
        m = sel & (perr == P_)
        n = int(m.sum())
        if n == 0:
            rec[P_] = {"n": 0}
            continue
        R, lo, hi = ratio_ci(pr[m], st[m])
        cn = clv_n[m].sum()
        rec[P_] = {"n": n, "bets": int(st[m].sum()), "roi": float(R), "ci_delta": [float(lo), float(hi)],
                   "hit": float(((pr[m] > 0).sum()) / n), "avg_odds": float(oddsum[m].sum() / st[m].sum()),
                   "clv": float(clv_sum[m].sum() / cn) if cn > 0 else None, "clv_n": int(cn)}
    yrr = yr if sub is None else yr[sub]
    for Y in [2024, 2025]:
        m = sel & (perr == "test") & (yrr == Y)
        if m.sum() > 0:
            rec[f"test_{Y}"] = {"n": int(m.sum()), "roi": float(pr[m].sum() / st[m].sum())}
    tr, va, te = rec["train"], rec["val"], rec["test"]
    want = (va.get("n", 0) >= 30 and te.get("n", 0) >= 30 and va["roi"] > 0 and te["roi"] > 0) or \
           (tr.get("n", 0) >= 100 and tr["ci_delta"][0] > 0)
    if want:
        for P_ in PERIODS:
            m = sel & (perr == P_)
            if m.sum() >= 5:
                rec[P_]["ci_boot"] = boot_ci(pr[m], st[m])
    RULES.append(rec)
    return rec


LEVELS = ["all", "atp_main", "wta_main", "challenger", "itf_w", "itf_m"]


def lvmask(lv):
    return np.ones(N, bool) if lv == "all" else (level == lv)


def comm_for(bk, t):
    if bk == "Betfair":
        return COMM, COMM
    if bk == "best":
        f = best_is_bf_close if t == "close" else best_is_bf_open
        return np.where(f[0], COMM, 0.0), np.where(f[1], COMM, 0.0)
    return 0.0, 0.0


R = {}  # descriptive results

# ------------------------------------------------------------------ H1 efficiency
log("H1 efficiency")
srcs = {"bf_close": pbfc, "bf_open": P[("Betfair", "open")], "b365_close": P[("bet365", "close")],
        "b365_open": P[("bet365", "open")], "lad_close": P[("Ladbrokes", "close")],
        "uni_close": P[("Unibet", "close")], "cons_open": P[("cons", "open")], "cons_close": P[("cons", "close")]}
common = ok & np.isfinite(pbfc) & np.isfinite(srcs["b365_close"]) & np.isfinite(srcs["b365_open"])
ovr365c = 1 / O[("bet365", "close")][0] + 1 / O[("bet365", "close")][1]
ovr365o = 1 / O[("bet365", "open")][0] + 1 / O[("bet365", "open")][1]
ovrbf = 1 / O[("Betfair", "close")][0] + 1 / O[("Betfair", "close")][1]
fav365 = np.minimum(O[("bet365", "close")][0], O[("bet365", "close")][1])
favband = pd.cut(fav365, [1, 1.2, 1.4, 1.6, 1.8, 2.01], labels=["<1.2", "1.2-1.4", "1.4-1.6", "1.6-1.8", "1.8-2"]).astype(object).astype(str)
favband = np.asarray(favband)
from sklearn.linear_model import LogisticRegression


def calib_slope(p, yy):
    if len(yy) < 200:
        return None, None
    m = LogisticRegression(C=1e6, max_iter=200).fit(logit(p).reshape(-1, 1), yy)
    return float(m.coef_[0, 0]), float(m.intercept_[0])


def eff_table(keyarr, mask):
    out = {}
    for k in pd.unique(keyarr[mask]):
        m = mask & (keyarr == k)
        if m.sum() < 300:
            continue
        rec = {"n": int(m.sum())}
        for nm in ["bf_close", "b365_close", "b365_open"]:
            rec["ll_" + nm] = float(ll(srcs[nm][m], y[m]).mean())
        rec["b365_margin_close"] = float(np.nanmean(ovr365c[m]) - 1)
        rec["bf_overround_close"] = float(np.nanmean(ovrbf[m]) - 1)
        rec["gap_b365c_minus_bfc"] = rec["ll_b365_close"] - rec["ll_bf_close"]
        rec["gap_open_minus_close_b365"] = rec["ll_b365_open"] - rec["ll_b365_close"]
        sl, ic = calib_slope(srcs["b365_close"][m], y[m])
        rec["b365c_calib_slope"] = sl
        out[str(k)] = rec
    return out


R["H1_efficiency_common_sample"] = {}
for nm, arr in [("level", level), ("round", df["round"].values), ("surface", df.surface.values),
                ("month", df.month.values), ("year", yr), ("format", df.match_format.values),
                ("fav_band_b365c", favband), ("period", per)]:
    R["H1_efficiency_common_sample"][nm] = eff_table(np.asarray(arr).astype(str), common)
# level-wise all-source log loss on each source's own availability
R["H1_level_each_source"] = {}
for lv in LEVELS[1:]:
    d = {}
    for nm, p in srcs.items():
        m = ok & (level == lv) & np.isfinite(p)
        if m.sum() > 300:
            d[nm] = {"n": int(m.sum()), "ll": float(ll(p[m], y[m]).mean())}
    R["H1_level_each_source"][lv] = d
# recalibration per level fitted on train, evaluated val/test (does it beat raw b365 close / open?)
_m = ok & np.isfinite(P[("Betfair", "open")]) & np.isfinite(pbfc) & np.isfinite(srcs["b365_close"])
R["H1_bf_open_timing_check"] = {"n": int(_m.sum()), "ll_bf_open": float(ll(P[("Betfair", "open")][_m], y[_m]).mean()),
                                "ll_bf_close": float(ll(pbfc[_m], y[_m]).mean()), "ll_b365_close": float(ll(srcs["b365_close"][_m], y[_m]).mean()),
                                "ll_b365_open": float(ll(srcs["b365_open"][_m], y[_m]).mean()),
                                "note": "same-subset check: if Betfair open beat the closes its prices would be late-recorded; it does not"}
R["H1_recalibration"] = {}
for src in ["b365_close", "b365_open"]:
    for lv in LEVELS[1:5]:
        m = ok & (level == lv) & np.isfinite(srcs[src])
        mt = m & (per == "train")
        if mt.sum() < 1000:
            continue
        lr = LogisticRegression(C=1e6, max_iter=200).fit(logit(srcs[src][mt]).reshape(-1, 1), y[mt])
        rr = {"slope": float(lr.coef_[0, 0]), "intercept": float(lr.intercept_[0])}
        for P_ in ["val", "test"]:
            mm = m & (per == P_)
            pr_ = lr.predict_proba(logit(srcs[src][mm]).reshape(-1, 1))[:, 1]
            d = ll(srcs[src][mm], y[mm]) - ll(pr_, y[mm])
            bi = brng.integers(0, len(d), (500, len(d))) if len(d) < 40000 else None
            ci = [float(np.percentile(d[bi].mean(1), 2.5)), float(np.percentile(d[bi].mean(1), 97.5))] if bi is not None else \
                [float(d.mean() - 1.96 * d.std() / np.sqrt(len(d))), float(d.mean() + 1.96 * d.std() / np.sqrt(len(d)))]
            rr[P_] = {"n": int(mm.sum()), "ll_gain": float(d.mean()), "ci": ci}
        R["H1_recalibration"][f"{src}_{lv}"] = rr

# H1b: bet the per-level logistic recalibration of a book's own de-vigged price (FLB correction only)
for src, bk, t in [("b365_open", "bet365", "open"), ("b365_close", "bet365", "close"), ("cons_open", "softbest", "open")]:
    pq = np.full(N, np.nan)
    for lv in LEVELS[1:]:
        m = ok & (level == lv) & np.isfinite(srcs[src])
        mt = m & (per == "train")
        if mt.sum() < 500:
            continue
        lr = LogisticRegression(C=1e6, max_iter=200).fit(logit(srcs[src][mt]).reshape(-1, 1), y[mt])
        mall = (level == lv) & np.isfinite(srcs[src])
        pq[mall] = lr.predict_proba(logit(srcs[src][mall]).reshape(-1, 1))[:, 1]
    o1, o2 = O[(bk, t)]
    ev1 = pq * o1 - 1
    ev2 = (1 - pq) * o2 - 1
    for lv in LEVELS[:5]:
        for X in [0.0, 0.02, 0.05]:
            add_rule("H1b_recal", f"recal_{src}_{bk}_{t}_{lv}_ev{X}", (ev1 >= X) & (ev1 > ev2), (ev2 >= X) & (ev2 >= ev1), o1, o2,
                     mask=lvmask(lv), params={"src": src, "book": bk, "ev": X, "level": lv,
                                              "note": "recalibration fitted on all of 2014-2021, so train ROI is in-sample"}, decided=t)

# ------------------------------------------------------------------ H2 favourite-longshot
log("H2 FLB")
BANDS = [1.0, 1.25, 1.5, 1.8, 2.2, 3.0, 5.0, 10.0, 1000]
R["H2_calibration"] = {}
for bk in SOFT + ["Betfair", "best"]:
    for t in ["close", "open"]:
        o1, o2 = O[(bk, t)]
        p1 = P.get((bk, t))
        c1, c2 = comm_for(bk, t)
        for lv in LEVELS:
            lm = lvmask(lv)
            for i in range(len(BANDS) - 1):
                lo, hi = BANDS[i], BANDS[i + 1]
                b1 = (o1 >= lo) & (o1 < hi)
                b2 = (o2 >= lo) & (o2 < hi)
                add_rule("H2_flb_band", f"{bk}_{t}_{lv}_[{lo},{hi})", b1, b2, o1, o2, c1, c2, mask=lm,
                         params={"book": bk, "time": t, "level": lv, "band": [lo, hi]}, decided=t)
                if lv != "all" and t == "close" and bk == "bet365":
                    for P_ in ["train"]:
                        m1 = ok & lm & (per == P_) & b1
                        m2 = ok & lm & (per == P_) & b2
                        n_ = m1.sum() + m2.sum()
                        if n_ > 100:
                            act = (y[m1].sum() + (1 - y[m2]).sum()) / n_
                            imp = (p1[m1].sum() + (1 - p1[m2]).sum()) / n_
                            R["H2_calibration"][f"{bk}_{t}_{lv}_[{lo},{hi})"] = {"n": int(n_), "actual": float(act),
                                                                                 "implied_fair": float(imp)}
            fav1 = o1 < o2
            add_rule("H2_fav_dog", f"{bk}_{t}_{lv}_fav", fav1, ~fav1 & (o1 != o2), o1, o2, c1, c2, mask=lm,
                     params={"book": bk, "time": t, "level": lv, "side": "fav"}, decided=t)
            add_rule("H2_fav_dog", f"{bk}_{t}_{lv}_dog", ~fav1 & (o1 != o2), fav1, o1, o2, c1, c2, mask=lm,
                     params={"book": bk, "time": t, "level": lv, "side": "dog"}, decided=t)

# ------------------------------------------------------------------ H3 line movement
log("H3 line movement")
mv = {"bf": pbfc - P[("Betfair", "open")], "b365": P[("bet365", "close")] - P[("bet365", "open")],
      "cons": P[("cons", "close")] - P[("cons", "open")]}
R["H3_move_regression"] = {}
specs = [("b365c+b365move", P[("bet365", "close")], logit(P[("bet365", "close")]) - logit(P[("bet365", "open")])),
         ("bfc+b365move", pbfc, logit(P[("bet365", "close")]) - logit(P[("bet365", "open")])),
         ("bfc+bfmove", pbfc, logit(pbfc) - logit(P[("Betfair", "open")])),
         ("b365c+consmove", P[("bet365", "close")], logit(P[("cons", "close")]) - logit(P[("cons", "open")])),
         ("bfc+b365c_vs_bfc", pbfc, logit(P[("bet365", "close")]) - logit(pbfc))]
for nm, base_p, x in specs:
    m = ok & np.isfinite(base_p) & np.isfinite(x)
    mt = m & (per == "train")
    X = np.c_[logit(base_p), x]
    lr = LogisticRegression(C=1e6, max_iter=300).fit(X[mt], y[mt])
    lr0 = LogisticRegression(C=1e6, max_iter=300).fit(X[mt][:, :1], y[mt])
    rr = {"coef_base": float(lr.coef_[0, 0]), "coef_move": float(lr.coef_[0, 1]), "n_train": int(mt.sum())}
    for P_ in ["val", "test"]:
        mm = m & (per == P_)
        d = ll(base_p[mm], y[mm]) - ll(lr.predict_proba(X[mm])[:, 1], y[mm])
        d0 = ll(lr0.predict_proba(X[mm][:, :1])[:, 1], y[mm]) - ll(lr.predict_proba(X[mm])[:, 1], y[mm])
        se = d.std() / np.sqrt(len(d))
        se0 = d0.std() / np.sqrt(len(d0))
        rr[P_] = {"n": int(mm.sum()), "ll_gain_vs_raw_base": float(d.mean()), "ci": [float(d.mean() - 1.96 * se), float(d.mean() + 1.96 * se)],
                  "ll_gain_vs_recalibrated_base": float(d0.mean()), "ci_recal": [float(d0.mean() - 1.96 * se0), float(d0.mean() + 1.96 * se0)]}
    R["H3_move_regression"][nm] = rr

for lv in LEVELS[:5]:
    lm = lvmask(lv)
    for t_ in [0.02, 0.04, 0.08]:
        # hindsight / optimistic: bet at the open the side that later shortens
        for src in ["bf", "b365", "cons"]:
            d = mv[src]
            for bk in ["bet365", "softbest"]:
                o1, o2 = O[(bk, "open")]
                add_rule("H3_oracle_open", f"follow_{src}_move_at_{bk}_open_{lv}_{t_}", d >= t_, d <= -t_, o1, o2,
                         mask=lm, params={"src": src, "book": bk, "thr": t_, "level": lv,
                                          "note": "HINDSIGHT: uses the later move; upper bound"}, decided="open(hindsight)")
        # steam following and reverse at close (decided at close)
        for src in ["bf", "cons", "b365"]:
            d = mv[src]
            for bk in ["bet365", "softbest", "Betfair"]:
                if bk == "Betfair" and src == "bf":
                    continue
                o1, o2 = O[(bk, "close")]
                c1, c2 = comm_for(bk, "close")
                add_rule("H3_steam_close", f"steam_{src}_{bk}_close_{lv}_{t_}", d >= t_, d <= -t_, o1, o2, c1, c2,
                         mask=lm, params={"src": src, "book": bk, "thr": t_, "level": lv})
                add_rule("H3_reverse_close", f"reverse_{src}_{bk}_close_{lv}_{t_}", d <= -t_, d >= t_, o1, o2, c1, c2,
                         mask=lm, params={"src": src, "book": bk, "thr": t_, "level": lv})
        # lag: Betfair moved, bet365 did not
        d = mv["bf"]
        still = np.abs(mv["b365"]) < 0.005
        o1, o2 = O[("bet365", "close")]
        add_rule("H3_lag_close", f"bf_moved_b365_still_{lv}_{t_}", (d >= t_) & still, (d <= -t_) & still, o1, o2,
                 mask=lm, params={"thr": t_, "level": lv})

# ------------------------------------------------------------------ H4 book disagreement
log("H4 disagreement")
for lv in LEVELS[:5]:
    lm = lvmask(lv)
    for t in ["open", "close"]:
        pref_bf = P[("Betfair", t)]
        for bk in SOFT + ["softbest", "best"]:
            o1, o2 = O[(bk, t)]
            c1, c2 = comm_for(bk, t)
            # reference: Betfair same time; and consensus of the other soft books
            refs = {"bf": pref_bf}
            if bk in SOFT:
                refs["others"] = np.nanmean(np.vstack([P[(b, t)] for b in SOFT if b != bk]), axis=0)
            else:
                refs["cons"] = P[("cons", t)]
            for rn, pr_ in refs.items():
                ev1 = o1 * (1 - np.asarray(c1)) * pr_ - 1
                ev2 = o2 * (1 - np.asarray(c2)) * (1 - pr_) - 1
                for X in [0.0, 0.02, 0.05, 0.10]:
                    b1 = (ev1 >= X) & ~(ev2 > ev1)
                    b2 = (ev2 >= X) & ~(ev1 >= ev2)
                    add_rule("H4_disagree", f"{bk}_{t}_vs_{rn}_{lv}_ev{X}", b1, b2, o1, o2, c1, c2, mask=lm,
                             params={"book": bk, "time": t, "ref": rn, "ev": X, "level": lv}, decided=t)
    # Betfair exchange vs soft consensus at close
    o1, o2 = O[("Betfair", "close")]
    pr_ = P[("cons", "close")]
    for X in [0.0, 0.02, 0.05]:
        ev1 = o1 * 0.98 * pr_ - 1
        ev2 = o2 * 0.98 * (1 - pr_) - 1
        add_rule("H4_disagree", f"Betfair_close_vs_cons_{lv}_ev{X}", (ev1 >= X) & (ev1 > ev2), (ev2 >= X) & (ev2 >= ev1),
                 o1, o2, COMM, COMM, mask=lm, params={"book": "Betfair", "time": "close", "ref": "cons", "ev": X, "level": lv})

# ------------------------------------------------------------------ H5 totals
log("H5 totals")
tg = df.total_games.values.astype(float)
tsets = (df.total_sets_a.values + df.total_sets_b.values).astype(float)
rows = []
for bk in SOFT:
    line = df[f"{bk}_total_games_line"].values.astype(float)
    oo = df[f"{bk}_odds_over"].values.astype(float)
    ou = df[f"{bk}_odds_under"].values.astype(float)
    v = ok & np.isfinite(line) & (oo > 1) & (ou > 1) & ((1 / oo + 1 / ou) >= 1.0) & ((1 / oo + 1 / ou) <= 1.25)
    idx = np.where(v)[0]
    kind = np.where(line[idx] <= 5.5, "sets", "games")
    actual = np.where(kind == "sets", tsets[idx], tg[idx])
    rows.append(pd.DataFrame({"mid": idx, "book": bk, "line": line[idx], "o_over": oo[idx], "o_under": ou[idx],
                              "kind": kind, "actual": actual}))
T = pd.concat(rows, ignore_index=True)
T = T[np.isfinite(T.actual)]
T["over_win"] = (T.actual > T.line).astype(int)
T["push"] = (T.actual == T.line)
T = T[~T.push].reset_index(drop=True)
T["p_over_fair"] = (1 / T.o_over) / (1 / T.o_over + 1 / T.o_under)
mid = T.mid.values
T["level"] = level[mid]
T["fmt"] = df.match_format.values[mid]
T["per"] = per[mid]
pfav_c = np.where(np.isfinite(pbfc), pbfc, P[("cons", "close")])
T["closeness"] = np.abs(pfav_c[mid] - 0.5)
T["surface"] = df.surface.values[mid]
T["round"] = df["round"].values[mid]
R["H5_totals_calibration"] = {}
for (bk, kind, lv, fmt), g in T[T.per == "train"].groupby(["book", "kind", "level", "fmt"]):
    if len(g) < 300:
        continue
    R["H5_totals_calibration"][f"{bk}_{kind}_{lv}_bo{fmt}"] = {
        "n": int(len(g)), "over_rate": float(g.over_win.mean()), "implied_over_fair": float(g.p_over_fair.mean()),
        "mean_actual_minus_line": float((g.actual - g.line).mean()), "mean_line": float(g.line.mean())}
R["H5_totals_by_closeness_train"] = {}
T["cl_band"] = pd.cut(T.closeness, [-0.01, 0.1, 0.25, 0.51], labels=["close<0.1", "0.1-0.25", ">0.25"]).astype(str)
for (bk, kind, cb), g in T[T.per == "train"].groupby(["book", "kind", "cl_band"]):
    if len(g) > 300:
        R["H5_totals_by_closeness_train"][f"{bk}_{kind}_{cb}"] = {"n": int(len(g)), "over_rate": float(g.over_win.mean()),
                                                                   "implied_over_fair": float(g.p_over_fair.mean())}


def add_tot_rule(name, bo, bu, g, params):
    sub = g.mid.values
    ysub = (g.over_win.values == 1, g.over_win.values == 0)
    add_rule("H5_totals", name, bo, bu, g.o_over.values, g.o_under.values, sub=sub, ysub=ysub, params=params)


for bk in SOFT:
    for kind in ["games", "sets"]:
        g = T[(T.book == bk) & (T.kind == kind)]
        if len(g) < 500:
            continue
        for lv in LEVELS[:5]:
            lm = np.ones(len(g), bool) if lv == "all" else (g.level.values == lv)
            for fmt in [3, 5, "any"]:
                fm = lm & (np.ones(len(g), bool) if fmt == "any" else (g.fmt.values == fmt))
                if fm.sum() < 200:
                    continue
                add_tot_rule(f"{bk}_{kind}_{lv}_bo{fmt}_over", fm, np.zeros(len(g), bool), g, {"book": bk, "kind": kind, "level": lv, "fmt": fmt, "side": "over"})
                add_tot_rule(f"{bk}_{kind}_{lv}_bo{fmt}_under", np.zeros(len(g), bool), fm, g, {"book": bk, "kind": kind, "level": lv, "fmt": fmt, "side": "under"})
        for cb in ["close<0.1", "0.1-0.25", ">0.25"]:
            cm = g.cl_band.values == cb
            add_tot_rule(f"{bk}_{kind}_closeness{cb}_over", cm, np.zeros(len(g), bool), g, {"book": bk, "kind": kind, "closeness": cb, "side": "over"})
            add_tot_rule(f"{bk}_{kind}_closeness{cb}_under", np.zeros(len(g), bool), cm, g, {"book": bk, "kind": kind, "closeness": cb, "side": "under"})

# totals model: LightGBM classifier P(over), fit 2014-2018, early stop 2019, thresholds read on 2020-2021
import lightgbm as lgb

lvcode = {k: i for i, k in enumerate(LEVELS[1:])}
surfcode = {k: i for i, k in enumerate(sorted(df.surface.unique()))}
rndcode = {k: i for i, k in enumerate(sorted(df["round"].astype(str).unique()))}
bkcode = {k: i for i, k in enumerate(SOFT)}
T["yr"] = yr[mid]
FT = pd.DataFrame({"line": T.line, "p_over_fair": T.p_over_fair, "ovr": 1 / T.o_over + 1 / T.o_under,
                   "closeness": T.closeness, "pfav_cons_open": np.abs(P[("cons", "open")][mid] - 0.5),
                   "level": T.level.map(lvcode), "fmt": T.fmt, "surface": T.surface.map(surfcode),
                   "round": T["round"].astype(str).map(rndcode), "book": T.book.map(bkcode),
                   "kind": (T.kind == "sets").astype(int), "ml_ovr": ovr365c[mid]})
prm = dict(objective="binary", learning_rate=0.03, num_leaves=15, min_data_in_leaf=300, feature_fraction=0.8,
           bagging_fraction=0.8, bagging_freq=1, lambda_l2=10.0, verbose=-1, seed=SEED, num_threads=4,
           deterministic=True, force_row_wise=True)
cat = ["level", "surface", "round", "book"]
tr_m = T.yr.values <= 2018
es_m = T.yr.values == 2019
init = logit(T.p_over_fair.values)
dtr = lgb.Dataset(FT[tr_m], T.over_win[tr_m], init_score=init[tr_m], categorical_feature=cat)
des = lgb.Dataset(FT[es_m], T.over_win[es_m], init_score=init[es_m], categorical_feature=cat, reference=dtr)
mt = lgb.train(prm, dtr, 2000, valid_sets=[des], callbacks=[lgb.early_stopping(100, verbose=False)])
T["p_model"] = 1 / (1 + np.exp(-(mt.predict(FT, raw_score=True, num_iteration=mt.best_iteration) + init)))
R["H5_totals_model"] = {"best_iter": int(mt.best_iteration)}
for P_, msk in [("oos2020_21", (T.yr >= 2020) & (T.yr <= 2021)), ("val", T.per == "val"), ("test", T.per == "test")]:
    g = T[msk]
    d = ll(g.p_over_fair.values, g.over_win.values) - ll(g.p_model.values, g.over_win.values)
    se = d.std() / np.sqrt(len(d))
    R["H5_totals_model"][P_] = {"n": int(len(g)), "ll_gain_vs_book_fair": float(d.mean()), "ci": [float(d.mean() - 1.96 * se), float(d.mean() + 1.96 * se)]}
Tm = T[T.yr >= 2020].copy()
Tm.loc[Tm.yr <= 2021, "per"] = "train"  # model rules: 'train' = 2020-2021 out-of-sample only
for bk in SOFT + ["any"]:
    for kind in ["games", "sets"]:
        g = Tm[((Tm.book == bk) if bk != "any" else True) & (Tm.kind == kind)]
        if bk == "any":
            # one bet per match: the book with the best EV
            g = g.copy()
            g["evo"] = g.p_model * g.o_over - 1
            g["evu"] = (1 - g.p_model) * g.o_under - 1
            g["evmax"] = g[["evo", "evu"]].max(1)
            g = g.sort_values("evmax", ascending=False).drop_duplicates("mid")
        if len(g) < 300:
            continue
        evo = g.p_model.values * g.o_over.values - 1
        evu = (1 - g.p_model.values) * g.o_under.values - 1
        for X in [0.0, 0.02, 0.05, 0.10]:
            # per[sub] must be the row's period; override via a temporary per array
            sub = g.mid.values
            ysub = (g.over_win.values == 1, g.over_win.values == 0)
            per_save = per
            per = per.copy()
            per[sub] = g.per.values  # for these rows: 2020-21 labelled train
            add_rule("H5_totals_model", f"model_{bk}_{kind}_ev{X}", (evo >= X) & (evo > evu), (evu >= X) & (evu >= evo),
                     g.o_over.values, g.o_under.values, sub=sub, ysub=ysub,
                     params={"book": bk, "kind": kind, "ev": X, "train_period": "2020-2021 OOS"})
            per = per_save

# ------------------------------------------------------------------ player history (strictly earlier dates)
log("history features")
played = (df.comment != "not_played").values
pid_a = df.player_a_url.values
pid_b = df.player_b_url.values
p365o_a = (1 / df.bet365_odds_a_opening) / (1 / df.bet365_odds_a_opening + 1 / df.bet365_odds_b_opening)
p365o_a = np.where(np.isfinite(O[("bet365", "open")][0]), p365o_a.values, np.nan)
pcons_o_p1 = P[("cons", "open")]
pcons_o_a = np.where(s, pcons_o_p1, 1 - pcons_o_p1)
pa_hist = np.where(np.isfinite(p365o_a), p365o_a, pcons_o_a)
isfinal = (df["round"].values == "final")
L = pd.DataFrame({"pid": np.r_[pid_a[played], pid_b[played]],
                  "day": np.r_[df.day.values[played], df.day.values[played]],
                  "won": np.r_[np.ones(played.sum()), np.zeros(played.sum())],
                  "p": np.r_[pa_hist[played], 1 - pa_hist[played]],
                  "fw": np.r_[isfinal[played].astype(float), np.zeros(played.sum())]})
L["hasp"] = np.isfinite(L.p).astype(float)
L["res"] = np.where(L.hasp > 0, L.won - L.p, 0.0)
A = L.groupby(["pid", "day"], sort=True).agg(n=("won", "size"), w=("won", "sum"), r=("res", "sum"),
                                            npz=("hasp", "sum"), fw=("fw", "sum")).reset_index()
for c in ["n", "w", "r", "npz", "fw"]:
    A["c" + c] = A.groupby("pid")[c].cumsum()
A["last_day"] = A.day
A = A.sort_values("day")
cols = ["pid", "day", "cn", "cw", "cr", "cnpz", "cfw", "last_day"]


def asof(pids, days, suffix):
    q = pd.DataFrame({"pid": pids, "day": days, "row": np.arange(len(pids))}).sort_values("day")
    m = pd.merge_asof(q, A[cols], on="day", by="pid", allow_exact_matches=False)
    m = m.sort_values("row")
    out = m[["cn", "cw", "cr", "cnpz", "cfw", "last_day"]].fillna({"cn": 0, "cw": 0, "cr": 0, "cnpz": 0, "cfw": 0})
    out.columns = [c + suffix for c in out.columns]
    return out.reset_index(drop=True)


H = {}
day = df.day.values
jan1 = pd.to_datetime(pd.Series(yr).astype(str) + "-01-01").values
for side, pids in [("1", np.where(s, pid_a, pid_b)), ("2", np.where(s, pid_b, pid_a))]:
    c0 = asof(pids, day, "")
    c14 = asof(pids, day - np.timedelta64(14, "D"), "_14")
    c90 = asof(pids, day - np.timedelta64(90, "D"), "_90")
    c365 = asof(pids, day - np.timedelta64(365, "D"), "_365")
    cy = asof(pids, jan1, "_y")
    H[f"n_prior{side}"] = c0.cn.values
    H[f"winrate{side}"] = ((c0.cw + 5) / (c0.cn + 10)).values
    H[f"resid{side}"] = (c0.cr / (c0.cnpz + 20)).values
    H[f"resid365_{side}"] = ((c0.cr - c365.cr_365) / (c0.cnpz - c365.cnpz_365 + 20)).values
    H[f"resid90_{side}"] = ((c0.cr - c90.cr_90) / (c0.cnpz - c90.cnpz_90 + 10)).values
    H[f"days_since{side}"] = np.where(c0.last_day.notna(), (day - c0.last_day.values.astype("datetime64[ns]")) / np.timedelta64(1, "D"), np.nan)
    H[f"n14_{side}"] = (c0.cn - c14.cn_14).values
    H[f"n90_{side}"] = (c0.cn - c90.cn_90).values
    H[f"titles_season{side}"] = (c0.cfw - cy.cfw_y).values
H = pd.DataFrame(H)
for c in ["n_prior", "winrate", "resid", "resid365_", "resid90_", "days_since", "n14_", "n90_", "titles_season"]:
    H[f"d_{c}"] = H[f"{c}1" if not c.endswith("_") else f"{c}1"] - H[f"{c}2" if not c.endswith("_") else f"{c}2"]
# leak self-test: history must not depend on same-day or later rows -> recompute for a random sample by brute force
chk = np.random.default_rng(SEED + 7).choice(np.where(played)[0], 200, replace=False)
bad = 0
for i in chk:
    pidv = pid_a[i] if s[i] else pid_b[i]
    prior = ((pid_a == pidv) | (pid_b == pidv)) & played & (day < day[i])
    if prior.sum() != H.n_prior1.values[i]:
        bad += 1
meta["history_leak_selftest_mismatches_of_200"] = int(bad)
log("history self-test mismatches", bad)

# H7: market under-rated players (prior residual) at the open
for lv in LEVELS[:5]:
    lm = lvmask(lv)
    for X in [0.03, 0.05, 0.08]:
        for minn in [30]:
            d = H.resid1.values - H.resid2.values
            enough = (H.n_prior1.values >= minn) & (H.n_prior2.values >= minn)
            for bk in ["bet365", "softbest"]:
                o1, o2 = O[(bk, "open")]
                add_rule("H7_underrated", f"resid_diff_{bk}_open_{lv}_{X}", enough & (d >= X), enough & (d <= -X), o1, o2,
                         mask=lm, params={"x": X, "min_prior": minn, "book": bk, "level": lv}, decided="open")
        # rest/fatigue rule: back the rested player vs one with >=4 matches in 14 days
        f1 = (H.n14_1.values >= 4) & (H.n14_2.values <= 1)
        f2 = (H.n14_2.values >= 4) & (H.n14_1.values <= 1)
    for bk in ["bet365", "softbest"]:
        o1, o2 = O[(bk, "open")]
        add_rule("H7_rest", f"back_rested_vs_busy_{bk}_open_{lv}", f2, f1, o1, o2, mask=lm, params={"book": bk, "level": lv}, decided="open")
        add_rule("H7_rest", f"back_busy_vs_rested_{bk}_open_{lv}", f1, f2, o1, o2, mask=lm, params={"book": bk, "level": lv}, decided="open")

# ------------------------------------------------------------------ H6 LightGBM at the open
log("H6 LightGBM")
base = np.where(np.isfinite(P[("bet365", "open")]), P[("bet365", "open")], P[("cons", "open")])
F = pd.DataFrame({"base_logit": logit(base)})
for bk in SOFT + ["Betfair"]:
    pp = P[(bk, "open")]
    F[f"l_{bk}_open"] = logit(pp)
    F[f"d_{bk}_open"] = logit(pp) - logit(base)
    F[f"ovr_{bk}_open"] = 1 / O[(bk, "open")][0] + 1 / O[(bk, "open")][1]
bo1, bo2 = O[("best", "open")]
F["best_open_imp1"] = 1 / bo1
F["best_open_imp2"] = 1 / bo2
F["best_open_ovr"] = 1 / bo1 + 1 / bo2
F["closeness"] = np.abs(base - 0.5)
F["level"] = pd.Series(level).map(lvcode).values
F["round"] = df["round"].astype(str).map(rndcode).values
F["surface"] = df.surface.map(surfcode).values
F["month"] = df.month.values
F["fmt"] = df.match_format.values
F = pd.concat([F, H], axis=1)
def run_variant(tag, cols):
    global per
    mm = ok & np.isfinite(base)
    tr_m = mm & (yr <= 2018)
    es_m = mm & (yr == 2019)
    initb = logit(base)
    cat = [c for c in ["level", "round", "surface"] if c in cols]
    Fv = F[cols]
    dtr = lgb.Dataset(Fv[tr_m], y[tr_m], init_score=initb[tr_m], categorical_feature=cat)
    des = lgb.Dataset(Fv[es_m], y[es_m], init_score=initb[es_m], categorical_feature=cat, reference=dtr)
    prm2 = dict(prm, learning_rate=0.02, min_data_in_leaf=500)
    mdl = lgb.train(prm2, dtr, 3000, valid_sets=[des], callbacks=[lgb.early_stopping(150, verbose=False)])
    raw = mdl.predict(Fv, raw_score=True, num_iteration=mdl.best_iteration)
    pm = 1 / (1 + np.exp(-(raw + initb)))
    imp = sorted(zip(Fv.columns, mdl.feature_importance("gain")), key=lambda z: -z[1])[:15]
    R["H6_lgbm_"+tag] = {"best_iter": int(mdl.best_iteration), "n_train": int(tr_m.sum()), "top_gain": [[a, float(b)] for a, b in imp]}
    per_m = per.copy()
    per_m[(yr == 2020) | (yr == 2021)] = "train"
    per_m[yr <= 2019] = "fit"
    for P_ in ["train", "val", "test"]:
        msk = mm & (per_m == P_)
        d = ll(base[msk], y[msk]) - ll(pm[msk], y[msk])
        se = d.std() / np.sqrt(len(d))
        rec = {"n": int(msk.sum()), "ll_base_b365open": float(ll(base[msk], y[msk]).mean()), "ll_model": float(ll(pm[msk], y[msk]).mean()),
               "gain": float(d.mean()), "ci": [float(d.mean() - 1.96 * se), float(d.mean() + 1.96 * se)]}
        m2 = msk & np.isfinite(pbfc)
        rec["on_bf_close_subset"] = {"n": int(m2.sum()), "ll_bf_close": float(ll(pbfc[m2], y[m2]).mean()),
                                     "ll_model": float(ll(pm[m2], y[m2]).mean()), "ll_b365_open": float(ll(base[m2], y[m2]).mean())}
        # does the close move toward the model?
        m3 = msk & np.isfinite(P[("cons", "close")])
        dis = pm[m3] - base[m3]
        mvv = P[("cons", "close")][m3] - P[("cons", "open")][m3]
        rec["slope_cons_move_on_model_disagreement"] = float(np.polyfit(dis, mvv, 1)[0]) if m3.sum() > 100 else None
        for lv in LEVELS[1:5]:
            ml_ = msk & (level == lv)
            if ml_.sum() > 200:
                dd = ll(base[ml_], y[ml_]) - ll(pm[ml_], y[ml_])
                rec[f"gain_{lv}"] = [float(dd.mean()), float(1.96 * dd.std() / np.sqrt(len(dd)))]
        R["H6_lgbm_"+tag][P_ + ("(2020-21 OOS)" if P_ == "train" else "")] = rec

    per_save = per
    per = per_m
    for lv in LEVELS[:5]:
        lm = lvmask(lv)
        for bk in ["bet365", "softbest", "best"]:
            o1, o2 = O[(bk, "open")]
            c1, c2 = comm_for(bk, "open")
            ev1 = pm * o1 * (1 - np.asarray(c1)) - 1
            ev2 = (1 - pm) * o2 * (1 - np.asarray(c2)) - 1
            for X in [0.0, 0.02, 0.05, 0.10]:
                add_rule("H6_lgbm_open", f"lgbm{tag}_{bk}_open_{lv}_ev{X}", (ev1 >= X) & (ev1 > ev2), (ev2 >= X) & (ev2 >= ev1), o1, o2,
                         c1, c2, mask=lm & mm, params={"book": bk, "ev": X, "level": lv, "train_period": "2020-2021 OOS"}, decided="open")
        # timing check: bet365 price unchanged open -> close, so the open price stood until the start
        o1, o2 = O[("bet365", "open")]
        q1, q2 = O[("bet365", "close")]
        same = np.isclose(o1, q1) & np.isclose(o2, q2)
        ev1 = pm * o1 - 1
        ev2 = (1 - pm) * o2 - 1
        for X in [0.0, 0.02, 0.05]:
            add_rule("H6_lgbm_timing", f"lgbm{tag}_bet365_unchanged_{lv}_ev{X}", (ev1 >= X) & (ev1 > ev2), (ev2 >= X) & (ev2 >= ev1), o1, o2,
                     mask=lm & mm & same, params={"book": "bet365", "ev": X, "level": lv, "filter": "bet365 open == close"}, decided="open (price stood to close)")
            add_rule("H6_lgbm_timing", f"lgbm{tag}_bet365_moved_{lv}_ev{X}", (ev1 >= X) & (ev1 > ev2), (ev2 >= X) & (ev2 >= ev1), o1, o2,
                     mask=lm & mm & ~same, params={"book": "bet365", "ev": X, "level": lv, "filter": "bet365 open != close"}, decided="open")
        # same model, bet at the close (stale model info at close)
        o1, o2 = O[("softbest", "close")]
        for X in [0.02, 0.05]:
            ev1 = pm * o1 - 1
            ev2 = (1 - pm) * o2 - 1
            add_rule("H6_lgbm_close", f"lgbm{tag}_softbest_close_{lv}_ev{X}", (ev1 >= X) & (ev1 > ev2), (ev2 >= X) & (ev2 >= ev1), o1, o2,
                     mask=lm & mm, params={"book": "softbest", "ev": X, "level": lv, "train_period": "2020-2021 OOS"})
    per = per_save
    return pm

allc = list(F.columns)
softonly = [c for c in allc if not (c.startswith("best_open") or "Betfair" in c)]
hist_cols = list(H.columns)
softnohist = [c for c in softonly if c not in hist_cols]
R["H6_variants"] = {"full": allc, "soft": softonly, "softnohist": softnohist}
pm_full = run_variant("", allc)
pm_soft = run_variant("_soft", softonly)
pm_softnohist = run_variant("_softnohist", softnohist)

# ------------------------------------------------------------------ summary
log("summary", len(RULES), "rules")


def g(r, P_, k, d=None):
    return r[P_].get(k, d)


both = [r for r in RULES if g(r, "val", "n", 0) >= 30 and g(r, "test", "n", 0) >= 30 and r["val"]["roi"] > 0 and r["test"]["roi"] > 0]
cred = [r for r in both if r["val"].get("ci_boot", [np.nan])[0] > 0 and r["test"].get("ci_boot", [np.nan])[0] > 0]
train_sel = [r for r in RULES if g(r, "train", "n", 0) >= 100 and r["train"]["ci_delta"][0] > 0]
fam = pd.Series([r["family"] for r in RULES]).value_counts().to_dict()


def short(r):
    o = {"family": r["family"], "name": r["name"], "decided": r["decided"]}
    for P_ in PERIODS:
        x = r[P_]
        o[P_] = {k: x.get(k) for k in ["n", "roi", "ci_boot", "ci_delta", "clv", "avg_odds"] if k in x}
    return o


summary = {"n_rules": len(RULES), "rules_per_family": fam,
           "n_positive_val_and_test": len(both),
           "n_positive_val_and_test_bootstrap_lower_gt0_both": len(cred),
           "credible_both": [short(r) for r in cred],
           "n_selected_on_train_ci_lower_gt0": len(train_sel),
           "train_selected": [short(r) for r in train_sel],
           "train_selected_positive_val": int(sum(1 for r in train_sel if g(r, "val", "roi", -1) is not None and r["val"].get("n", 0) > 0 and r["val"]["roi"] > 0)),
           "train_selected_positive_val_and_test": int(sum(1 for r in train_sel if r["val"].get("n", 0) > 0 and r["test"].get("n", 0) > 0 and r["val"]["roi"] > 0 and r["test"]["roi"] > 0)),
           "positive_both_top": [short(r) for r in sorted(both, key=lambda r: -min(r["val"]["roi"], r["test"]["roi"]))[:60]]}


def clean(o):
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    return o


with open(OUT, "w") as f:
    json.dump(clean({"meta": meta, "summary": summary, "descriptive": R, "rules": RULES}), f, indent=1)
log("wrote", OUT)
