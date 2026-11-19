"""Exact game-level distributions of total games and game margin for a match with constant
serve-point probabilities, tracking who serves first (sets alternate by parity; a tiebreak
counts as one game and flips the next set's first server like any odd game count)."""
from functools import lru_cache
import numpy as np

TMAX = 70          # totals 0..69
MOFF = 40          # margin index offset (margin -40..40)
NM = 81


def hold(p):
    q = 1 - p
    return p ** 4 * (1 + 4 * q + 10 * q * q) + 20 * (p * q) ** 3 * p * p / (1 - 2 * p * q)


@lru_cache(maxsize=None)
def tiebreak(pa, pb):
    """P(A wins a tiebreak) when A serves its first point; pattern A,B,B,A,A,..."""
    @lru_cache(maxsize=None)
    def f(a, b):
        if a >= 7 and a - b >= 2:
            return 1.0
        if b >= 7 and b - a >= 2:
            return 0.0
        if a == b and a >= 6:
            w, l = pa * (1 - pb), (1 - pa) * pb
            return w / (w + l)
        n = a + b
        p = pa if (n % 4 in (0, 3)) else 1 - pb
        return p * f(a + 1, b) + (1 - p) * f(a, b + 1)
    return f(0, 0)


@lru_cache(maxsize=None)
def set_outcomes(pa, pb, a_first):
    """((games_a, games_b, prob, tiebreak?), ...) for one set; A serves game 1 iff a_first."""
    ha, hb = hold(pa), hold(pb)
    # the player who serves game 13 (= the set's first server) serves first in the tiebreak
    tb = tiebreak(pa, pb) if a_first else 1 - tiebreak(pb, pa)
    mass = {(0, 0): 1.0}
    out = []
    while mass:
        nxt = {}
        for (a, b), pr in mass.items():
            if a == 6 and b == 6:
                out += [(7, 6, pr * tb, True), (6, 7, pr * (1 - tb), True)]
                continue
            a_serving = ((a + b) % 2 == 0) == a_first
            p_a = ha if a_serving else 1 - hb
            for (na, nb), q in (((a + 1, b), p_a), ((a, b + 1), 1 - p_a)):
                if (na >= 6 and na - nb >= 2) or (nb >= 6 and nb - na >= 2):
                    out.append((na, nb, pr * q, False))
                else:
                    nxt[(na, nb)] = nxt.get((na, nb), 0.0) + pr * q
        mass = nxt
    return tuple(out)


def match_pmfs(pa, pb, best_of, a_first):
    """(pmf of total games [TMAX], pmf of margin a-b [NM], P(a wins))."""
    need = 3 if best_of == 5 else 2
    so = {True: set_outcomes(pa, pb, True), False: set_outcomes(pa, pb, False)}
    states = {(0, 0, a_first): np.zeros((NM, TMAX))}
    states[(0, 0, a_first)][MOFF, 0] = 1.0
    tot = np.zeros(TMAX); mar = np.zeros(NM); pwin = 0.0
    for _ in range(2 * need - 1):
        nxt = {}
        for (sa, sb, af), M in states.items():
            for ga, gb, q, _tb in so[af]:
                n = ga + gb
                key = (sa + (ga > gb), sb + (gb > ga), af if n % 2 == 0 else (not af))
                sh = np.zeros_like(M)
                dm = ga - gb
                if dm >= 0:
                    sh[dm:, n:] = M[:NM - dm, :TMAX - n]
                else:
                    sh[:dm, n:] = M[-dm:, :TMAX - n]
                sh *= q
                if key[0] == need or key[1] == need:
                    tot += sh.sum(0); mar += sh.sum(1)
                    if key[0] == need:
                        pwin += sh.sum()
                else:
                    if key in nxt:
                        nxt[key] += sh
                    else:
                        nxt[key] = sh
        states = nxt
        if not states:
            break
    return tot, mar, pwin


# ------------------------------------------------------------------ grid tables (fav orientation)
S_GRID = np.round(np.arange(0.45, 0.8001, 0.005), 4)
D_GRID = np.round(np.arange(0.0, 0.4001, 0.005), 4)


def build_tables(path=None):
    """TOT[bo_i, first_i, s_i, d_i, :], MAR[...], PW[bo_i, s_i, d_i]; first_i 0 = favourite serves
    first; margin is favourite minus underdog; pf = s + d/2, pd = s - d/2 (clipped)."""
    import os
    if path and os.path.exists(path):
        z = np.load(path)
        return z["TOT"], z["MAR"], z["PW"]
    ns, nd = len(S_GRID), len(D_GRID)
    TOT = np.zeros((2, 2, ns, nd, TMAX), np.float32)
    MAR = np.zeros((2, 2, ns, nd, NM), np.float32)
    PW = np.zeros((2, ns, nd))
    for bi, bo in enumerate((3, 5)):
        for si, s in enumerate(S_GRID):
            for di, dd in enumerate(D_GRID):
                pf = float(min(s + dd / 2, 0.97)); pdg = float(max(s - dd / 2, 0.2))
                pf, pdg = round(pf, 4), round(pdg, 4)
                for fi, ff in enumerate((True, False)):
                    t, m, w = match_pmfs(pf, pdg, bo, ff)
                    TOT[bi, fi, si, di] = t; MAR[bi, fi, si, di] = m
                    if fi == 0:
                        PW[bi, si, di] = w
    if path:
        np.savez_compressed(path, TOT=TOT, MAR=MAR, PW=PW)
    return TOT, MAR, PW
