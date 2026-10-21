"""First-server effect tests (Mohammadi 2026). Reads fs_table.pkl and fs_market.pkl (scratchpad),
writes results.json next to this file.

  A  inference coverage, and agreement of the two inference routes (service games vs breaks)
  B  replication of the paper's Tables 2 and 4, and what the plain iid model predicts for the
     same statistics with a fair coin toss (the selection the paper does not correct for)
  C  the effect itself, from PRE-MATCH strength: totals and margins by favourite-served-first
     vs underdog-served-first, against the model's prediction under the same selection
  D  who serves first: P(favourite serves first) by full likelihood (corrects the selection)
  E  2026 markets (Pinnacle and execution books, totals and handicaps): does the realised score
     carry the first-server shift relative to the market; does the close move with the first
     server (anyone pricing the toss); post-toss bet values
  F  totals model with a strength-weighted first-server prior: out-of-sample log loss vs no prior,
     on history (exact total games) and on 2026 Pinnacle totals
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fs_core as fc  # noqa: E402

SCRATCH = os.environ.get("FS_SCRATCH", "/tmp/claude-0/-home-user-Tennis-Quant-Lab-V5/a0609b44-84ba-59ef-a5f1-f66b68d375ec/scratchpad")
RNG = np.random.default_rng(20261021)
R = {}


def r4(x):
    return None if x is None or not np.isfinite(x) else round(float(x), 4)


def ols_slope(y, x):
    """Slope of y ~ a + beta x and its SE (the intercept absorbs the model's level error)."""
    y, x = np.asarray(y, float), np.asarray(x, float)
    ok = np.isfinite(y) & np.isfinite(x)
    y, x = y[ok], x[ok]
    xc, yc = x - x.mean(), y - y.mean()
    b = (xc * yc).sum() / (xc * xc).sum()
    e = yc - b * xc
    se = np.sqrt((e * e).sum() / (len(y) - 2) / (xc * xc).sum())
    return {"beta": r4(b), "se": r4(se), "z": r4(b / se), "n": int(len(y))}


def ols_ctrl(y, x, C):
    """Coefficient on x in y ~ 1 + x + C, with its classical SE."""
    y, x = np.asarray(y, float), np.asarray(x, float)
    ok = np.isfinite(y) & np.isfinite(x) & np.isfinite(C).all(1)
    X = np.c_[np.ones(ok.sum()), x[ok], C[ok]]
    yy = y[ok]
    b, *_ = np.linalg.lstsq(X, yy, rcond=None)
    e = yy - X @ b
    cov = np.linalg.inv(X.T @ X) * (e @ e) / (len(yy) - X.shape[1])
    return {"beta": r4(b[1]), "se": r4(np.sqrt(cov[1, 1])), "z": r4(b[1] / np.sqrt(cov[1, 1])), "n": int(len(yy))}


def mean_se(v):
    v = np.asarray(v, float)
    v = v[np.isfinite(v)]
    return {"mean": r4(v.mean()), "se": r4(v.std(ddof=1) / np.sqrt(len(v))), "n": int(len(v))}


# ------------------------------------------------------------------ per-row model summaries
def summaries(pa, pb, best_of, rule, T_obs, H_obs, prefix):
    """Model pieces for both first-server cases, vectorised over rows sharing (best_of, rule)."""
    out = {}
    for M, af in (("A", True), ("B", False)):
        d = fc.match_dist(pa, pb, best_of, rule, af)
        t = np.arange(d["T_det"].shape[1])
        h = np.arange(d["H_det"].shape[1]) - d["hmax"]
        Td, Ti, Hd, Hi = d["T_det"], d["T_ind"], d["H_det"], d["H_ind"]
        Taw = d["T_det_aw"]
        pdet = Td.sum(1)
        out[f"{prefix}pdet_{M}"] = pdet
        out[f"{prefix}ET_{M}"] = ((Td + Ti) * t).sum(1)
        out[f"{prefix}ETdet_{M}"] = (Td * t).sum(1) / pdet
        out[f"{prefix}EH_{M}"] = ((Hd + Hi) * h).sum(1)
        out[f"{prefix}EHdet_{M}"] = (Hd * h).sum(1) / pdet
        pa_w = Taw.sum(1)
        out[f"{prefix}ETdet_awin_{M}"] = (Taw * t).sum(1) / pa_w
        out[f"{prefix}ETdet_bwin_{M}"] = ((Td - Taw) * t).sum(1) / (pdet - pa_w)
        out[f"{prefix}pdet_awin_{M}"] = pa_w
        out[f"{prefix}pdet_bwin_{M}"] = pdet - pa_w
        ti = np.clip(T_obs, 0, Td.shape[1] - 1).astype(int)
        r = np.arange(len(ti))
        out[f"{prefix}pT_{M}"] = (Td + Ti)[r, ti]
        out[f"{prefix}pTdet_{M}"] = Td[r, ti]
        out[f"{prefix}pwin"] = d["pwin"]
    return out


def add_summaries(t, pa_col, pb_col, prefix, chunk=15000):
    parts = []
    for (bo, rule), g in t.groupby(["best_of", "rule"]):
        for s in range(0, len(g), chunk):
            gg = g.iloc[s:s + chunk]
            o = summaries(gg[pa_col].to_numpy(float), gg[pb_col].to_numpy(float), int(bo), rule,
                          gg["T"].to_numpy(), gg["H"].to_numpy(), prefix)
            parts.append(pd.DataFrame(o, index=gg.index))
    return t.join(pd.concat(parts))


# ------------------------------------------------------------------ A
def part_a(t):
    out = {}
    for g, x in t.groupby("group"):
        vc = x.method.value_counts()
        n = len(x)
        out[g] = {"matches": n, **{k: int(v) for k, v in vc.items()},
                  "determined_pct": r4(100 * x.first_a.notna().mean())}
    # agreement of svgms and breaks where both are usable
    agree = tot = 0
    for r in t[t.method == "svgms"].itertuples():
        bf = [r.w_bpFaced, r.w_bpSaved, r.l_bpFaced, r.l_bpSaved]
        if not all(np.isfinite(pd.to_numeric(bf, errors="coerce"))):
            continue
        sets_w = r.sets_a if r.y == 1 else [(b, a, tb) for a, b, tb in r.sets_a]
        who, how = fc.infer_first_server(sets_w, np.nan, np.nan, *map(float, bf))
        if who is None:
            continue
        tot += 1
        agree += who == r.first_wl
    out["svgms_vs_breaks"] = {"both_determined": tot, "agree_pct": r4(100 * agree / max(tot, 1))}
    return out


# ------------------------------------------------------------------ B
def part_b(t):
    """Paper Table 2 (residual by winner/loser served first, in-match serve shares) and Table 4
    (logit of winner-served-first on P_W - P_L), observed vs the iid model with a fair toss."""
    d = t[t.first_a.notna() & np.isfinite(t.pa_in) & np.isfinite(t.pb_in)
          & t.pa_in.between(0.3, 0.95) & t.pb_in.between(0.3, 0.95)].copy()
    d = add_summaries(d, "pa_in", "pb_in", "in_")
    out = {}
    aw = d.y.to_numpy() == 1
    first_is_w = (d.first_a.to_numpy() == 1) == aw
    ET = 0.5 * (d.in_ET_A + d.in_ET_B)
    resid = d["T"] - ET
    # model expectation of the same residual given (determinable, who served, who won), fair toss
    def mexp(M, X):
        return d[f"in_ETdet_{X}win_{M}"]
    exp = np.where(d.first_a == 1, np.where(aw, mexp("A", "a"), mexp("A", "b")),
                   np.where(aw, mexp("B", "a"), mexp("B", "b"))) - ET
    for g in ["ATP", "WTA", "Challenger"]:
        m = (d.group == g).to_numpy()
        row = {}
        for lab, sel in (("W_first", first_is_w), ("L_first", ~first_is_w)):
            k = m & sel
            row[lab] = {"observed_resid": mean_se(resid[k]), "iid_fair_toss_expected": r4(np.mean(exp[k])),
                        "share_of_determined": r4(k.sum() / m.sum())}
        row["gap_L_minus_W"] = {"observed": r4(np.mean(resid[m & ~first_is_w]) - np.mean(resid[m & first_is_w])),
                                "iid_expected": r4(np.mean(exp[m & ~first_is_w]) - np.mean(exp[m & first_is_w]))}
        # Table 4: logit(winner served first) on P_W - P_L; and the same fit to the model's
        # fair-toss probability of winner-first given (determinable, winner)
        ds = np.where(aw, d.pa_in - d.pb_in, d.pb_in - d.pa_in)[m]
        yobs = first_is_w[m].astype(float)
        pw_first = np.where(aw, d.in_pdet_awin_A / (d.in_pdet_awin_A + d.in_pdet_awin_B),
                            d.in_pdet_bwin_B / (d.in_pdet_bwin_A + d.in_pdet_bwin_B))[m]
        row["table4_beta_observed"] = r4(logit_slope(ds, yobs))
        row["table4_beta_iid_fair_toss"] = r4(logit_slope(ds, pw_first))
        row["mean_P_winner_first_observed"] = r4(yobs.mean())
        row["mean_P_winner_first_iid_fair_toss"] = r4(pw_first.mean())
        out[g] = row
    return out


def logit_slope(x, y):
    """Logistic regression y (0..1, soft labels allowed) on x with intercept; returns slope."""
    x = np.asarray(x, float); y = np.asarray(y, float)
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    b = np.zeros(2)
    X = np.c_[np.ones(len(x)), x]
    for _ in range(50):
        p = 1 / (1 + np.exp(-X @ b))
        g = X.T @ (y - p)
        Hm = (X * (p * (1 - p))[:, None]).T @ X
        step = np.linalg.solve(Hm, g)
        b += step
        if np.abs(step).max() < 1e-10:
            break
    return b[1]


# ------------------------------------------------------------------ C
def part_c(t):
    """Pre-match test. Favourite = higher pre-match model win probability."""
    d = t[t.first_a.notna()].copy()
    fav_a = d.pre_pwin.to_numpy() >= 0.5
    fav_first = (d.first_a.to_numpy() == 1) == fav_a
    sgn = np.where(fav_a, 1, -1)
    ETdet_obs = np.where(d.first_a == 1, d.pre_ETdet_A, d.pre_ETdet_B)
    w = 0.5 * d.pre_pdet_A / (0.5 * d.pre_pdet_A + 0.5 * d.pre_pdet_B)       # P(M=A | det), fair toss
    ETdet_blind = w * d.pre_ETdet_A + (1 - w) * d.pre_ETdet_B
    EHdet_obs = np.where(d.first_a == 1, d.pre_EHdet_A, d.pre_EHdet_B) * sgn
    EHdet_blind = (w * d.pre_EHdet_A + (1 - w) * d.pre_EHdet_B) * sgn
    Hfav = d["H"].to_numpy() * sgn
    pT_obs = np.where(d.first_a == 1, d.pre_pTdet_A / d.pre_pdet_A, d.pre_pTdet_B / d.pre_pdet_B)
    pT_blind = (0.5 * d.pre_pTdet_A + 0.5 * d.pre_pTdet_B) / (0.5 * d.pre_pdet_A + 0.5 * d.pre_pdet_B)
    gap = np.abs(d.pre_pwin.to_numpy() - 0.5)
    out = {}
    groups = {"all": np.ones(len(d), bool), **{g: (d.group == g).to_numpy() for g in ("ATP", "WTA", "Challenger")},
              "gap_lt_0.15": gap < 0.15, "gap_0.15_0.30": (gap >= 0.15) & (gap < 0.30), "gap_ge_0.30": gap >= 0.30,
              "best_of_5": (d.best_of == 5).to_numpy()}
    for name, m in groups.items():
        row = {"n_determined": int(m.sum()), "fav_first_share": r4(fav_first[m].mean())}
        for lab, sel in (("fav_first", fav_first), ("dog_first", ~fav_first)):
            k = m & sel
            row[lab] = {"T_obs": r4(d["T"].to_numpy()[k].mean()), "T_model_given_server": r4(ETdet_obs[k].mean()),
                        "T_model_server_blind": r4(ETdet_blind[k].mean()),
                        "Hfav_obs": r4(Hfav[k].mean()), "Hfav_model_given_server": r4(EHdet_obs[k].mean())}
        # beta = 1: the server shift shows up as predicted; 0: no shift
        row["beta_total"] = ols_slope(d["T"].to_numpy()[m] - ETdet_blind[m], ETdet_obs[m] - ETdet_blind[m])
        row["beta_margin"] = ols_slope(Hfav[m] - EHdet_blind[m], EHdet_obs[m] - EHdet_blind[m])
        ll = np.log(np.clip(pT_obs[m], 1e-12, 1)) - np.log(np.clip(pT_blind[m], 1e-12, 1))
        row["exact_total_loglik_gain_per_match"] = mean_se(ll)
        # placebo: a server drawn from the server-blind posterior P(M = A | determinable); beta ~ 0
        fa = (RNG.random(len(d)) < w.to_numpy()).astype(float)
        ETp = np.where(fa == 1, d.pre_ETdet_A, d.pre_ETdet_B)
        row["placebo_beta_total"] = ols_slope(d["T"].to_numpy()[m] - ETdet_blind[m], ETp[m] - ETdet_blind[m])
        out[name] = row
    return out


# ------------------------------------------------------------------ D
def fit_prior(x, det_first_a, LA, LB, det_mask):
    """MLE of beta in P(A serves first) = sigmoid(beta * x). Determinable rows contribute
    log pi_M (their path term does not depend on beta); the others log(pi LA + (1-pi) LB)."""
    x = np.asarray(x, float)

    def nll(b):
        pi = 1 / (1 + np.exp(-b * x))
        v = np.where(det_mask, np.log(np.where(det_first_a == 1, pi, 1 - pi)),
                     np.log(pi * LA + (1 - pi) * LB))
        return -np.nansum(v)

    res = minimize_scalar(nll, bounds=(-5, 5), method="bounded")
    b = res.x
    h = 1e-3
    curv = (nll(b + h) - 2 * nll(b) + nll(b - h)) / h ** 2
    return {"beta": r4(b), "se": r4(1 / np.sqrt(curv)) if curv > 0 else None}


def path_lik(t, pa_col, pb_col):
    LA = np.full(len(t), np.nan); LB = np.full(len(t), np.nan)
    pos = {k: i for i, k in enumerate(t.index)}
    for (bo, rule), g in t.groupby(["best_of", "rule"]):
        idx = [pos[k] for k in g.index]
        pa, pb = g[pa_col].to_numpy(float), g[pb_col].to_numpy(float)
        sa = list(g.sets_a)
        LA[idx] = fc.path_likelihood(pa, pb, sa, int(bo), rule, True)
        LB[idx] = fc.path_likelihood(pa, pb, sa, int(bo), rule, False)
    return LA, LB


def part_d(t, LA, LB):
    x = np.log(t.elo_p / (1 - t.elo_p)).to_numpy()
    det = t.first_a.notna().to_numpy()
    fa = t.first_a.to_numpy()
    out = {}
    for name, m in {"all": np.ones(len(t), bool), **{g: (t.group == g).to_numpy() for g in ("ATP", "WTA", "Challenger")},
                    "train_2010_2021": (t.year <= 2021).to_numpy(), "test_2022_2026": (t.year >= 2022).to_numpy()}.items():
        ok = m & np.isfinite(x) & np.isfinite(LA) & np.isfinite(LB) & (LA + LB > 0)
        naive_b = logit_slope(x[ok & det], fa[ok & det])
        full = fit_prior(x[ok], fa[ok], LA[ok], LB[ok], det[ok])
        fav = x > 0
        out[name] = {"n": int(ok.sum()), "n_determined": int((ok & det).sum()),
                     "naive_det_only_beta": r4(naive_b), "full_likelihood": full,
                     "naive_fav_first_share": r4(np.mean((fa[ok & det] == 1) == fav[ok & det])),
                     "full_P_fav_first_at_elo_p_0.75": r4(1 / (1 + np.exp(-full["beta"] * np.log(3))))}
    return out


# ------------------------------------------------------------------ E
def invert_gap(mk, cp):
    """(pa, pb) with the serve level pa + pb from each match's pre-match history and the gap
    solved from Pinnacle's de-vigged moneyline at cp (bisection). The iid model cannot match the
    moneyline AND the total line at once (given the moneyline it runs about 2 games long), so the
    totals line is not used here; see aligned shifts below."""
    pa_hat = np.full(len(mk), np.nan); pb_hat = np.full(len(mk), np.nan)
    pos = {k: i for i, k in enumerate(mk.index)}
    ok = mk[f"ml_{cp}_fair"].notna() & np.isfinite(mk.pa_pre) & np.isfinite(mk.pb_pre)
    for (bo, rule), g in mk[ok].groupby(["best_of", "rule"]):
        lvl = np.clip((g.pa_pre + g.pb_pre).to_numpy() / 2, 0.5, 0.8)
        target = g[f"ml_{cp}_fair"].to_numpy()
        lo, hi = np.full(len(g), -0.35), np.full(len(g), 0.35)
        for _ in range(22):
            mid = (lo + hi) / 2
            pw = fc.match_dist(lvl + mid / 2, lvl - mid / 2, int(bo), "tb7" if rule == "tb7" else rule, True)["pwin"]
            lo, hi = np.where(pw < target, mid, lo), np.where(pw < target, hi, mid)
        mid = (lo + hi) / 2
        idx = [pos[k] for k in g.index]
        pa_hat[idx], pb_hat[idx] = lvl + mid / 2, lvl - mid / 2
    return pa_hat, pb_hat


def aligned(P_blind_tail, target):
    """Index of the half-point line whose server-blind tail probability is closest to target."""
    return np.nanargmin(np.abs(P_blind_tail - target[:, None]), axis=1)


def ret(win, push, price):
    return np.where(push, 0.0, np.where(win, price - 1, -1.0))


def part_e(mk):
    out = {}
    mk = mk.copy()
    mk["pa_close"], mk["pb_close"] = invert_gap(mk, "close")
    out["n_fixtures"] = int(len(mk))
    out["n_inverted_close"] = int(np.isfinite(mk.pa_close).sum())
    out["n_determined"] = int(mk.first_a.notna().sum())
    mk = mk[np.isfinite(mk.pa_close) & mk.tot_close_fair.notna()].copy()
    # model pieces at the implied parameters; every probability is read at the model line that
    # sits at the market's quantile (server-blind tail = Pinnacle's fair), so only the server
    # SHIFT comes from the model, not its level
    rows = []
    for (bo, rule), g in mk.groupby(["best_of", "rule"]):
        dA = fc.match_dist(g.pa_close.to_numpy(), g.pb_close.to_numpy(), int(bo), rule, True)
        dB = fc.match_dist(g.pa_close.to_numpy(), g.pb_close.to_numpy(), int(bo), rule, False)
        o = pd.DataFrame(index=g.index)
        tt = np.arange(dA["T_det"].shape[1])
        lines = tt[:-1] + 0.5
        tail = lambda P: np.cumsum(P[:, ::-1], 1)[:, ::-1][:, 1:]            # P(T > t + 0.5)
        PA, PB = dA["T_det"] + dA["T_ind"], dB["T_det"] + dB["T_ind"]
        jt = aligned(0.5 * (tail(PA) + tail(PB)), g.tot_close_fair.to_numpy())
        r = np.arange(len(g))
        o["model_line_tot"] = lines[jt]
        hh = np.arange(dA["H_det"].shape[1]) - dA["hmax"]
        HA, HB = dA["H_det"] + dA["H_ind"], dB["H_det"] + dB["H_ind"]
        # P(H + h' > 0) for h' = k + 0.5: tail of H above -h'
        htail = lambda P: np.cumsum(P[:, ::-1], 1)[:, ::-1]                    # P(H >= hh[k])
        hcf = g.hc_close_fair.to_numpy()
        hc_ok = np.isfinite(hcf)
        jh = aligned(0.5 * (htail(HA) + htail(HB)), np.where(hc_ok, hcf, 0.5))
        o["model_line_hc"] = np.where(hc_ok, -(hh[jh] - 0.5), np.nan)
        for M, d, P, Hm in (("A", dA, PA, HA), ("B", dB, PB, HB)):
            o[f"pover_{M}"] = tail(P)[r, jt]
            o[f"pdet_{M}"] = d["T_det"].sum(1)
            o[f"poverdet_{M}"] = tail(d["T_det"])[r, jt] / o[f"pdet_{M}"]
            o[f"pcov_{M}"] = np.where(hc_ok, htail(Hm)[r, jh], np.nan)
            o[f"pcovdet_{M}"] = np.where(hc_ok, htail(d["H_det"])[r, jh] / o[f"pdet_{M}"], np.nan)
            o[f"ET_{M}"] = (P * tt).sum(1)
        rows.append(o)
    mk = mk.join(pd.concat(rows))
    mk["pover_blind"] = 0.5 * (mk.pover_A + mk.pover_B)
    mk["pcov_blind"] = 0.5 * (mk.pcov_A + mk.pcov_B)
    out["model_level_check"] = {"model_ET_blind_mean": r4(np.mean(0.5 * (mk.ET_A + mk.ET_B))),
                                "observed_T_mean": r4(mk["T"].mean()),
                                "pinnacle_line_mean": r4(mk.tot_close_line.mean()),
                                "model_line_mean": r4(mk.model_line_tot.mean())}
    out["model_shift_unconditional"] = {
        "mean_abs_ET_A_minus_ET_B_games": r4(np.mean(np.abs(mk.ET_A - mk.ET_B))),
        "mean_abs_pover_shift_vs_blind": r4(np.mean(np.abs(mk.pover_A - mk.pover_blind))),
        "p90_abs_pover_shift": r4(np.percentile(np.abs(mk.pover_A - mk.pover_blind), 90)),
        "mean_abs_pcover_shift_vs_blind": r4(np.nanmean(np.abs(mk.pcov_A - mk.pcov_blind))),
        "p90_abs_pcover_shift": r4(np.nanpercentile(np.abs(mk.pcov_A - mk.pcov_blind), 90)),
    }
    d = mk[mk.first_a.notna()].copy()
    fa = d.first_a.to_numpy() == 1
    # E1: realised outcome vs model, given the determinable selection
    wdet = d.pdet_A / (d.pdet_A + d.pdet_B)
    yo = (d["T"] > d.tot_close_line).astype(float).to_numpy()
    po_M = np.where(fa, d.poverdet_A, d.poverdet_B)
    po_bl = wdet * d.poverdet_A + (1 - wdet) * d.poverdet_B
    ll = lambda y, p: y * np.log(np.clip(p, 1e-9, 1)) + (1 - y) * np.log(np.clip(1 - p, 1e-9, 1))
    np_ = (d["T"] != d.tot_close_line).to_numpy()                       # pushes excluded
    e1 = {"totals_beta": ols_slope((yo - po_bl)[np_], (po_M - po_bl)[np_]),
          "totals_logloss_gain_per_bet": mean_se((ll(yo, po_M) - ll(yo, po_bl))[np_])}
    hcok = (d.hc_close_line.notna() & ((d["H"] + d.hc_close_line) != 0)).to_numpy()
    yc = ((d["H"] + d.hc_close_line) > 0).astype(float).to_numpy()
    pc_M = np.where(fa, d.pcovdet_A, d.pcovdet_B)
    pc_bl = wdet * d.pcovdet_A + (1 - wdet) * d.pcovdet_B
    e1["handicap_beta"] = ols_slope((yc - pc_bl)[hcok], (pc_M - pc_bl)[hcok])
    e1["handicap_logloss_gain_per_bet"] = mean_se((ll(yc, pc_M) - ll(yc, pc_bl))[hcok])
    out["E1_realised_vs_model_given_selection"] = e1
    # E2: does Pinnacle's close move with the first server (vs its t1h price, same line)?
    z_tot = np.where(fa, d.pover_A, d.pover_B) - d.pover_blind
    z_hc = np.where(fa, d.pcov_A, d.pcov_B) - d.pcov_blind
    same = (d.tot_t1h_line == d.tot_close_line).to_numpy()
    mv = (d.tot_close_fair - d.tot_t1h_fair).to_numpy()
    e2 = {"totals_close_move_on_shift": ols_slope(mv[same], z_tot[same]),
          "totals_mean_abs_move": r4(np.nanmean(np.abs(mv[same])))}
    sh = (d.hc_t1h_line == d.hc_close_line).to_numpy()
    mvh = (d.hc_close_fair - d.hc_t1h_fair).to_numpy()
    e2["handicap_close_move_on_shift"] = ols_slope(mvh[sh], z_hc[sh])
    # The determinable selection ties the server to the result, and late money predicts results,
    # so also control for the realised outcome (win, margin, total).
    ctrl = np.c_[d.y.to_numpy(float), d["H"].to_numpy(float), d["T"].to_numpy(float)]
    e2["totals_close_move_on_shift_ctrl_outcome"] = ols_ctrl(mv[same], z_tot[same], ctrl[same])
    e2["handicap_close_move_on_shift_ctrl_outcome"] = ols_ctrl(mvh[sh], z_hc[sh], ctrl[sh])
    out["E2_does_the_close_price_the_toss"] = e2
    # E3: post-toss bets at the close. Model probability = Pinnacle fair + model server shift.
    e3 = {}
    for mkt, fair_col, shift, ywin, push in (
            ("totals", "tot_close_fair", z_tot, yo == 1, (d["T"] == d.tot_close_line).to_numpy()),
            ("handicap", "hc_close_fair", z_hc, yc == 1, ((d["H"] + d.hc_close_line) == 0).to_numpy())):
        sa, sb = ("over", "under") if mkt == "totals" else ("p1", "p2")
        tag = "tot" if mkt == "totals" else "hc"
        fair = d[fair_col].to_numpy() + shift
        # selection-consistent model prob of the A-side outcome (what the realised rate should be)
        pm_det = po_M if mkt == "totals" else pc_M
        for thr in (0.0, 0.02, 0.04):
            for bk in ("pinnacle", "betrivers", "draftkings", "bet365", "best"):
                if bk == "best":
                    cols_a = [f"{tag}_close_{b}_{sa}" for b in ("pinnacle", "betrivers", "draftkings", "bet365") if f"{tag}_close_{b}_{sa}" in d]
                    cols_b = [f"{tag}_close_{b}_{sb}" for b in ("pinnacle", "betrivers", "draftkings", "bet365") if f"{tag}_close_{b}_{sb}" in d]
                    pr_a, pr_b = d[cols_a].max(1).to_numpy(), d[cols_b].max(1).to_numpy()
                else:
                    if f"{tag}_close_{bk}_{sa}" not in d:
                        continue
                    pr_a, pr_b = d[f"{tag}_close_{bk}_{sa}"].to_numpy(), d[f"{tag}_close_{bk}_{sb}"].to_numpy()
                ev_a, ev_b = fair * pr_a - 1, (1 - fair) * pr_b - 1
                take_a = (ev_a > thr) & (ev_a >= ev_b)
                take_b = (ev_b > thr) & (ev_b > ev_a)
                r_ = np.concatenate([ret(ywin[take_a], push[take_a], pr_a[take_a]), ret(~ywin[take_b], push[take_b], pr_b[take_b])])
                exp_det = np.concatenate([pm_det[take_a] * pr_a[take_a] - 1, (1 - pm_det[take_b]) * pr_b[take_b] - 1])
                if len(r_) < 20:
                    continue
                e3[f"{mkt}|{bk}|ev>{thr:.2f}"] = {"bets": int(len(r_)), "realised_roi": mean_se(r_),
                                                  "model_expected_roi_same_selection": r4(np.mean(exp_det)),
                                                  "claimed_ev": r4(np.mean(np.concatenate([ev_a[take_a], ev_b[take_b]])))}
    out["E3_post_toss_bets_determinable_subset"] = e3
    # model-implied ROI over ALL fixtures (a bettor who sees every toss), fair toss
    allr = {}
    for mkt, tag, sa, sb in (("totals", "tot", "over", "under"), ("handicap", "hc", "p1", "p2")):
        pA = mk.pover_A if mkt == "totals" else mk.pcov_A
        pB = mk.pover_B if mkt == "totals" else mk.pcov_B
        bl = mk.pover_blind if mkt == "totals" else mk.pcov_blind
        for bk in ("pinnacle", "betrivers", "draftkings", "bet365"):
            ca, cb = f"{tag}_close_{bk}_{sa}", f"{tag}_close_{bk}_{sb}"
            if ca not in mk:
                continue
            pra, prb = mk[ca].to_numpy(), mk[cb].to_numpy()
            base = mk[f"{tag}_close_fair"].to_numpy()
            evs, nb = [], 0
            for pM in (pA, pB):
                f_ = base + (pM - bl).to_numpy()
                ea, eb = f_ * pra - 1, (1 - f_) * prb - 1
                best = np.fmax(ea, eb)
                tk = best > 0.0
                evs.append(np.where(tk, best, 0.0))
                nb += np.nansum(tk)
            ev_all = 0.5 * (evs[0] + evs[1])
            ok = np.isfinite(pra) & np.isfinite(prb)
            allr[f"{mkt}|{bk}"] = {"fixtures": int(ok.sum()), "bet_share": r4(nb / 2 / max(ok.sum(), 1)),
                                   "model_EV_per_bet": r4(np.nansum(ev_all[ok]) / max(nb / 2, 1))}
    out["E3b_model_implied_all_fixtures_if_toss_seen"] = allr
    mk.to_pickle(os.path.join(SCRATCH, "fs_market_scored.pkl"))
    return out, mk


# ------------------------------------------------------------------ F
def part_f(t, mk, beta):
    """Strength-weighted prior pi = sigmoid(beta * logit(elo_p)) vs a fair toss.
    History: log P(exact total games) with the pre-match serve model, 2022-2026 (beta fit 2010-2021).
    2026: Pinnacle close fair over prob at the main line shifted by the prior, vs Pinnacle itself."""
    out = {}
    x = np.log(t.elo_p / (1 - t.elo_p)).to_numpy()
    pi = 1 / (1 + np.exp(-beta * x))
    p_prior = pi * t.pre_pT_A + (1 - pi) * t.pre_pT_B
    p_fair = 0.5 * (t.pre_pT_A + t.pre_pT_B)
    m = (t.year >= 2022).to_numpy() & np.isfinite(p_prior) & (p_fair > 0)
    out["history_exact_total_loglik_gain"] = mean_se(np.log(p_prior[m]) - np.log(p_fair[m]))
    out["history_mean_abs_ET_shift_games"] = r4(np.mean(np.abs((pi - 0.5) * (t.pre_ET_A - t.pre_ET_B))[m]))
    xm = np.log(mk.elo_p / (1 - mk.elo_p)).to_numpy()
    pim = 1 / (1 + np.exp(-beta * xm))
    yo = (mk["T"] > mk.tot_close_line).astype(float).to_numpy()
    base = mk.tot_close_fair.to_numpy()
    shifted = np.clip(base + (pim * mk.pover_A + (1 - pim) * mk.pover_B - mk.pover_blind).to_numpy(), 1e-4, 1 - 1e-4)
    ok = np.isfinite(base) & np.isfinite(shifted) & (mk["T"] != mk.tot_close_line).to_numpy()
    ll = lambda y, p: -(y * np.log(p) + (1 - y) * np.log(1 - p))
    out["pinnacle_totals_logloss"] = r4(np.mean(ll(yo[ok], base[ok])))
    out["prior_shifted_logloss"] = r4(np.mean(ll(yo[ok], shifted[ok])))
    out["logloss_gain_vs_pinnacle"] = mean_se(ll(yo[ok], base[ok]) - ll(yo[ok], shifted[ok]))
    out["mean_abs_shift_prob"] = r4(np.mean(np.abs(shifted - base)[ok]))
    out["beta_used"] = r4(beta)
    return out


def main():
    if "--only-ef" in sys.argv:                       # reuse A-D from results.json, redo E and F
        R.update(json.load(open(os.path.join(HERE, "results.json"))))
        t = pd.read_pickle(os.path.join(SCRATCH, "fs_table.pkl"))
        tp = pd.read_pickle(os.path.join(SCRATCH, "fs_tp.pkl"))
        return finish_ef(tp)
    t = pd.read_pickle(os.path.join(SCRATCH, "fs_table.pkl"))
    t = t[t.level.astype(str) != "D"].copy()                              # Davis Cup formats vary
    R["A_inference"] = part_a(t)
    print("A done", flush=True)
    R["B_paper_replication"] = part_b(t)
    print("B done", json.dumps(R["B_paper_replication"]["ATP"]["gap_L_minus_W"]), flush=True)
    tp = t[np.isfinite(t.pa_pre) & np.isfinite(t.pb_pre) & (t.n_min >= 10)].copy()
    tp = add_summaries(tp, "pa_pre", "pb_pre", "pre_")
    R["C_effect_from_prematch_strength"] = part_c(tp)
    print("C done", json.dumps(R["C_effect_from_prematch_strength"]["all"]["beta_total"]), flush=True)
    LA, LB = path_lik(tp, "pa_pre", "pb_pre")
    R["D_who_serves_first"] = part_d(tp, LA, LB)
    print("D done", json.dumps(R["D_who_serves_first"]["all"]), flush=True)
    tp.drop(columns=[c for c in tp.columns if c.startswith("pre_") and c not in
                     ("pre_pT_A", "pre_pT_B", "pre_ET_A", "pre_ET_B")]).to_pickle(os.path.join(SCRATCH, "fs_tp.pkl"))
    finish_ef(tp)


def finish_ef(tp):
    mk = pd.read_pickle(os.path.join(SCRATCH, "fs_market.pkl"))
    mk = mk[mk.level.astype(str) != "D"].copy()
    R["E_markets_2026"], mks = part_e(mk)
    print("E done", flush=True)
    beta = R["D_who_serves_first"]["train_2010_2021"]["full_likelihood"]["beta"]
    R["F_totals_prior"] = part_f(tp, mks, beta)
    with open(os.path.join(HERE, "results.json"), "w") as fh:
        json.dump(R, fh, indent=1)
    print(json.dumps(R, indent=1))


if __name__ == "__main__":
    main()
