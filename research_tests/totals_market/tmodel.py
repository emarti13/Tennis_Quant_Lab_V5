"""Point model pinned to the moneyline: serve level s (mean serve-point chance) from leak-free
skills + court pace, the favourite-underdog gap d solved so that P(favourite wins) equals the
market's fair price, a learned dispersion (Gauss-Hermite mixture over s with sd sigma), a level
shift delta per tour, and a prior pi = P(favourite serves first)."""
from __future__ import annotations

import numpy as np

import dist_lib as dl

GH_Z, GH_W = np.polynomial.hermite_e.hermegauss(7)
GH_W = GH_W / GH_W.sum()
S0, SSTEP, NS = float(dl.S_GRID[0]), 0.005, len(dl.S_GRID)
TOT, MAR, PW = dl.build_tables(__import__("os").path.join(__import__("os").path.dirname(__file__), "tables.npz"))


def _solve_d(bi, si, q):
    """Fractional d index where PW[bi, si, :] reaches q (monotone)."""
    curve = PW[bi, si, :]                                  # (N, ND)
    q = np.clip(q, 0.5, None)[:, None]
    above = curve >= q
    k = np.where(above.any(1), above.argmax(1), curve.shape[1] - 1)
    k = np.clip(k, 1, curve.shape[1] - 1)
    lo, hi = np.take_along_axis(curve, (k - 1)[:, None], 1)[:, 0], np.take_along_axis(curve, k[:, None], 1)[:, 0]
    fr = np.clip((q[:, 0] - lo) / np.maximum(hi - lo, 1e-12), 0, 1)
    return k - 1, fr


def mix(s, q, bo, pi, sigma, chunk=20000, want=("tot", "mar")):
    """pmfs (N, 70) of total games and (N, 81) of favourite margin."""
    n = len(s)
    out_t = np.zeros((n, dl.TMAX), np.float32) if "tot" in want else None
    out_m = np.zeros((n, dl.NM), np.float32) if "mar" in want else None
    bi_all = (np.asarray(bo) == 5).astype(int)
    for a in range(0, n, chunk):
        sl = slice(a, a + chunk)
        ss, qq, bi, pp = np.asarray(s)[sl], np.asarray(q)[sl], bi_all[sl], np.asarray(pi)[sl]
        acc_t = 0 if out_t is not None else None
        acc_m = 0 if out_m is not None else None
        for z, w in zip(GH_Z, GH_W) if sigma > 0 else [(0.0, 1.0)]:
            x = np.clip((ss + sigma * z - S0) / SSTEP, 0, NS - 1 - 1e-9)
            s0 = np.floor(x).astype(int); fs = x - s0
            for si, ws in ((s0, 1 - fs), (s0 + 1, fs)):
                si = np.minimum(si, NS - 1)
                d0, fd = _solve_d(bi, si, qq)
                for di, wd in ((d0, 1 - fd), (d0 + 1, fd)):
                    wt = (w * ws * wd)[:, None]
                    if out_t is not None:
                        t = pp[:, None] * TOT[bi, 0, si, di] + (1 - pp[:, None]) * TOT[bi, 1, si, di]
                        acc_t = acc_t + wt * t
                    if out_m is not None:
                        m = pp[:, None] * MAR[bi, 0, si, di] + (1 - pp[:, None]) * MAR[bi, 1, si, di]
                        acc_m = acc_m + wt * m
        if out_t is not None:
            out_t[sl] = acc_t
        if out_m is not None:
            out_m[sl] = acc_m
    return out_t, out_m


def p_over(pmf_t, line):
    idx = np.arange(dl.TMAX)[None, :]
    return (pmf_t * (idx > np.asarray(line)[:, None])).sum(1)


def p_cover(pmf_m, line):
    """P(favourite margin + line > 0); line is the favourite's (negative) line."""
    idx = (np.arange(dl.NM) - dl.MOFF)[None, :]
    return (pmf_m * (idx + np.asarray(line)[:, None] > 0)).sum(1)


def loglik_totals(pmf_t, T):
    T = np.asarray(T).astype(int)
    p = pmf_t[np.arange(len(T)), np.clip(T, 0, dl.TMAX - 1)]
    return np.log(np.maximum(p, 1e-9))


# ------------------------------------------------------------------ with match-day form dispersion
GZ5, GW5 = np.polynomial.hermite_e.hermegauss(5)
GW5 = GW5 / GW5.sum()
DSTEP, ND = 0.005, len(dl.D_GRID)


def _pw_signed(bi, si, g):
    """P(fav wins) at signed gap g (negative: the underdog is the better server on the day)."""
    x = np.clip(np.abs(g) / DSTEP, 0, ND - 1 - 1e-9)
    k = np.floor(x).astype(int); f = x - k
    p = (1 - f) * PW[bi, si, k] + f * PW[bi, si, np.minimum(k + 1, ND - 1)]
    return np.where(g >= 0, p, 1 - p)


def mix2(s, q, bo, pi, sigma, tau, chunk=10000, want=("tot", "mar")):
    """As mix, plus a normal match-day spread tau on the serve-point gap; the centre gap is
    solved so that the mixture's P(favourite wins) equals q."""
    n = len(s)
    out_t = np.zeros((n, dl.TMAX), np.float32) if "tot" in want else None
    out_m = np.zeros((n, dl.NM), np.float32) if "mar" in want else None
    bi_all = (np.asarray(bo) == 5).astype(int)
    znodes = list(zip(GZ5, GW5)) if sigma > 0 else [(0.0, 1.0)]
    tnodes = list(zip(GZ5, GW5)) if tau > 0 else [(0.0, 1.0)]
    for a in range(0, n, chunk):
        sl = slice(a, a + chunk)
        ss, qq, bi, pp = np.asarray(s)[sl], np.clip(np.asarray(q)[sl], 0.5, 0.995), bi_all[sl], np.asarray(pi)[sl]
        m_ = len(ss)
        acc_t = np.zeros((m_, dl.TMAX)); acc_m = np.zeros((m_, dl.NM))
        for z, w in znodes:
            x = np.clip((ss + sigma * z - S0) / SSTEP, 0, NS - 1 - 1e-9)
            s0 = np.floor(x).astype(int); fs = x - s0
            for si, ws in ((s0, 1 - fs), (np.minimum(s0 + 1, NS - 1), fs)):
                lo, hi = np.zeros(m_), np.full(m_, 0.4)
                for _ in range(22):                                    # bisection on the centre gap
                    mid = 0.5 * (lo + hi)
                    pwm = sum(tw * _pw_signed(bi, si, mid + tau * tz) for tz, tw in tnodes)
                    hi = np.where(pwm > qq, mid, hi); lo = np.where(pwm > qq, lo, mid)
                g0 = 0.5 * (lo + hi)
                for tz, tw in tnodes:
                    g = g0 + tau * tz
                    xd = np.clip(np.abs(g) / DSTEP, 0, ND - 1 - 1e-9)
                    d0 = np.floor(xd).astype(int); fd = xd - d0
                    neg = g < 0
                    # underdog better on the day: swap roles (first-server label and margin sign)
                    pf_first = np.where(neg, 1 - pp, pp)[:, None]
                    for di, wd in ((d0, 1 - fd), (np.minimum(d0 + 1, ND - 1), fd)):
                        wt = (w * ws * tw * wd)[:, None]
                        if out_t is not None:
                            acc_t += wt * (pf_first * TOT[bi, 0, si, di] + (1 - pf_first) * TOT[bi, 1, si, di])
                        if out_m is not None:
                            mm = pf_first * MAR[bi, 0, si, di] + (1 - pf_first) * MAR[bi, 1, si, di]
                            mm = np.where(neg[:, None], mm[:, ::-1], mm)
                            acc_m += wt * mm
        if out_t is not None:
            out_t[sl] = acc_t
        if out_m is not None:
            out_m[sl] = acc_m
    return out_t, out_m
