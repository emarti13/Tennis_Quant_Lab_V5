"""First server: conditional-likelihood prior fit and a simulation null for the selection effect.

Determinability (the two first-server hypotheses predict different service-game counts) is a
function of the score alone, so P(first server | score) = pi L_fav / (pi L_fav + (1-pi) L_dog)
with L_X the model probability of the observed set scores when X serves first. Fitting pi on
that conditional likelihood removes the selection bias of a plain "who served first among
determinable matches" count (which is what the paper's odds ratio is based on)."""
from __future__ import annotations

from functools import lru_cache

import numpy as np
from scipy.optimize import minimize

import dist_lib as dl
import tmodel as tm


def _q(p):
    return round(round(min(max(p, 0.2), 0.97) / 0.005) * 0.005, 4)


@lru_cache(maxsize=None)
def set_table(pf, pd_, f_first):
    return {(a, b): p for a, b, p, _ in dl.set_outcomes(pf, pd_, f_first)}


def likelihoods(sets_fav, s, g0, tau):
    """log L_fav-first, log L_dog-first for each match. sets_fav: list of [(fav games, dog games)]."""
    lf, ld = np.zeros(len(s)), np.zeros(len(s))
    nodes = list(zip(tm.GZ5, tm.GW5)) if tau > 0 else [(0.0, 1.0)]
    for i, (sts, ss, gg) in enumerate(zip(sets_fav, s, g0)):
        acc = [0.0, 0.0]
        for z, w in nodes:
            g = gg + tau * z
            pf, pd_ = _q(ss + g / 2), _q(ss - g / 2)
            for xi, f_first in enumerate((True, False)):
                srv, L = f_first, 1.0
                for a, b in sts:
                    L *= set_table(pf, pd_, srv).get((a, b), 0.0)
                    if (a + b) % 2 == 1:
                        srv = not srv
                acc[xi] += w * L
        lf[i], ld[i] = np.log(max(acc[0], 1e-300)), np.log(max(acc[1], 1e-300))
    return lf, ld


def fit_prior(x_fav, offset, cov):
    """logit pi = a + b * cov, by the conditional likelihood (offset = log L_fav - log L_dog)."""
    x_fav = np.asarray(x_fav, float)

    def nll(w):
        z = w[0] + w[1] * cov + offset
        return np.sum(np.logaddexp(0, z) - x_fav * z)
    r = minimize(nll, np.zeros(2), method="BFGS")
    H = r.hess_inv if hasattr(r, "hess_inv") else np.eye(2)
    se = np.sqrt(np.diag(H))
    return {"a": float(r.x[0]), "b": float(r.x[1]), "se_a": float(se[0]), "se_b": float(se[1])}


def fit_naive(x_fav, cov):
    return fit_prior(x_fav, np.zeros(len(x_fav)), cov)


# ------------------------------------------------------------------ simulation (game level)
def simulate(s, g0, tau, pi, bo, k, rng):
    """Simulate k matches per row. Returns dict of arrays (n*k): fav_first, total, margin (fav),
    fav_won, determinable, inferred (1 fav, 0 dog, -1 none), fav_svgms, dog_svgms."""
    n = len(s)
    S = np.repeat(s, k); G = np.repeat(g0, k) + tau * rng.standard_normal(n * k)
    P = np.repeat(pi, k); B = np.repeat(bo, k)
    pf, pd_ = np.clip(S + G / 2, 0.2, 0.97), np.clip(S - G / 2, 0.2, 0.97)
    q = 1 - pf
    hf = pf ** 4 * (1 + 4 * q + 10 * q * q) + 20 * (pf * q) ** 3 * pf * pf / (1 - 2 * pf * q)
    q = 1 - pd_
    hd = pd_ ** 4 * (1 + 4 * q + 10 * q * q) + 20 * (pd_ * q) ** 3 * pd_ * pd_ / (1 - 2 * pd_ * q)
    qf = np.round(np.round(pf / 0.005) * 0.005, 4); qd = np.round(np.round(pd_ / 0.005) * 0.005, 4)
    keys = np.round(qf * 1000).astype(int) * 10000 + np.round(qd * 1000).astype(int)
    uk, first_idx, inv = np.unique(keys, return_index=True, return_inverse=True)
    tf = np.array([dl.tiebreak(float(qf[j]), float(qd[j])) for j in first_idx])
    td = np.array([1 - dl.tiebreak(float(qd[j]), float(qf[j])) for j in first_idx])
    tb_f_first, tb_d_first = tf[inv], td[inv]      # fav's tiebreak chance: fav / underdog serves first
    m = n * k
    fav_first = rng.random(m) < P
    srv_first = fav_first.copy()                 # True: fav serves first in the current set
    need = np.where(B == 5, 3, 2)
    sf = np.zeros(m, int); sd = np.zeros(m, int)
    total = np.zeros(m, int); margin = np.zeros(m, int)
    svf = np.zeros(m, int); svd = np.zeros(m, int)
    done = np.zeros(m, bool)
    set_scores = []
    for _set in range(5):
        a = np.zeros(m, int); b = np.zeros(m, int); fin = done.copy(); tb = np.zeros(m, bool)
        for gi in range(13):
            live = ~fin
            if not live.any():
                break
            at66 = live & (a == 6) & (b == 6)
            if at66.any():
                p = np.where(srv_first, tb_f_first, tb_d_first)
                w = rng.random(m) < p
                a = np.where(at66 & w, 7, a); b = np.where(at66 & ~w, 7, b)
                tb |= at66; fin |= at66
                live = ~fin
            fav_srv = (((a + b) % 2) == 0) == srv_first
            p = np.where(fav_srv, hf, 1 - hd)
            w = rng.random(m) < p
            svf += (live & fav_srv); svd += (live & ~fav_srv)
            a = np.where(live & w, a + 1, a); b = np.where(live & ~w, b + 1, b)
            ended = live & (((a >= 6) & (a - b >= 2)) | ((b >= 6) & (b - a >= 2)))
            fin |= ended
        play = ~done
        set_scores.append(np.where(play, a, -1) * 100 + np.where(play, b, -1))
        total += np.where(play, a + b, 0); margin += np.where(play, a - b, 0)
        sf += play & (a > b); sd += play & (b > a)
        srv_first = np.where(play & ((a + b) % 2 == 1), ~srv_first, srv_first)
        done |= (sf == need) | (sd == need)
    # inference from (set scores, service-game counts), as on the real data
    det = np.zeros(m, bool); inferred = np.full(m, -1)
    pred = []
    for hyp in (True, False):
        cur, pf_cnt, pd_cnt = np.full(m, hyp), np.zeros(m, int), np.zeros(m, int)
        for sc in set_scores:
            a, b = sc // 100, sc % 100
            play = sc >= 0
            n_ = np.where(play, a + b, 0)
            tbk = play & (((a == 7) & (b == 6)) | ((a == 6) & (b == 7)))
            reg = n_ - tbk
            fn, sn = (reg + 1) // 2, reg // 2
            pf_cnt += np.where(cur, fn, sn); pd_cnt += np.where(cur, sn, fn)
            cur = np.where(play & (n_ % 2 == 1), ~cur, cur)
        pred.append((pf_cnt, pd_cnt))
        # the true counts must equal the true-hypothesis prediction (sanity)
    mf = (pred[0][0] == svf) & (pred[0][1] == svd)
    md = (pred[1][0] == svf) & (pred[1][1] == svd)
    det = mf ^ md
    inferred = np.where(det, np.where(mf, 1, 0), -1)
    return {"fav_first": fav_first, "total": total, "margin": margin, "fav_won": sf > sd,
            "determinable": det, "inferred": inferred, "consistent": (mf | md)}
