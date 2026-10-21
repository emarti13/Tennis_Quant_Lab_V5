"""First-server effect (Mohammadi 2026, arXiv 2605.04867): score parsing, first-server inference,
and an exact constant-serve-probability (iid points) model conditioned on who serves first.

Inference (paper section 4.4, restated exactly). Serve alternates game by game across the whole
match; a tiebreak takes one slot. With T total games (a 7-6 set counts 13) the match's first
server F owns the odd slots. Tiebreaks are not service games in the data, so

    SG_F = ceil(T/2) - k_F,  SG_O = floor(T/2) - k_O,

where k_F (k_O) counts the tiebreaks whose set F (the other player) served first in. The two
hypotheses (winner first / loser first) are distinguishable exactly when SG_F != SG_O, that is
when (T mod 2) != k_F - k_O. For a match without tiebreaks: exactly when T is odd. That is a
selection on the score itself, so every comparison below is made against the model's
prediction under the SAME selection (the paper's Tables 2 and 4 are not).

Model. Points on each serve are iid (pa = P(A wins a point on A's serve), pb likewise for B).
Everything is computed exactly by dynamic programming, vectorised over matches.
"""
from __future__ import annotations

import math
import re

import numpy as np

# ------------------------------------------------------------------ score parsing
_BAD = ("RET", "W/O", "WALKOVER", "DEF", "ABD", "ABN", "[", "UNK", "?", "PLAYED")


def parse_sets(score, best_of=None):
    """[(a, b, tb)] per set from the winner's side for a cleanly completed match, else None.

    tb is True when the set ended in a tiebreak (a "(n)" suffix, or a 7-6 set)."""
    if not isinstance(score, str):
        return None
    s = score.strip().upper()
    if not s or any(t in s for t in _BAD):
        return None
    out = []
    for tok in s.split():
        m = re.fullmatch(r"(\d+)-(\d+)(?:\((\d+)(?:-\d+)?\))?", tok)
        if not m:
            return None
        a, b = int(m.group(1)), int(m.group(2))
        tb = m.group(3) is not None or {a, b} == {6, 7}
        hi, lo = max(a, b), min(a, b)
        if tb:
            if hi - lo != 1 or hi < 7:
                return None
        elif not (hi >= 6 and hi - lo >= 2 and (hi == 6 or hi - lo == 2)):
            return None
        out.append((a, b, tb))
    sw = sum(a > b for a, b, _ in out)
    sl = len(out) - sw
    need = None if best_of is None or not np.isfinite(best_of) else (int(best_of) + 1) // 2
    if sw <= sl or (need is not None and (sw != need or len(out) > int(best_of))):
        return None
    if need is None and sw not in (2, 3):
        return None
    return out


def implied_service_games(sets, winner_first: bool):
    """(SG winner, SG loser) implied by the set scores if the winner (or loser) served first."""
    sg = {True: 0, False: 0}
    first_is_w = winner_first
    for a, b, tb in sets:
        n = a + b - (1 if tb else 0)
        sg[first_is_w] += (n + 1) // 2
        sg[not first_is_w] += n // 2
        if (a + b) % 2 == 1:
            first_is_w = not first_is_w
    return sg[True], sg[False]


def infer_first_server(sets, w_sv=np.nan, l_sv=np.nan, w_bpf=np.nan, w_bps=np.nan, l_bpf=np.nan, l_bps=np.nan):
    """("W" | "L" | None, method). None with method "indeterminate" when the score cannot tell,
    "no_data" when no usable service-game or break counts, "inconsistent" when the counts fit
    neither hypothesis."""
    hw, hl = implied_service_games(sets, True), implied_service_games(sets, False)
    if hw == hl:
        return None, "indeterminate"
    tried = False
    if np.isfinite(w_sv) and np.isfinite(l_sv):
        tried = True
        obs = (int(w_sv), int(l_sv))
        if obs == hw:
            return "W", "svgms"
        if obs == hl:
            return "L", "svgms"
    if all(np.isfinite(x) for x in (w_bpf, w_bps, l_bpf, l_bps)):
        tried = True
        brk_w, brk_l = l_bpf - l_bps, w_bpf - w_bps          # breaks made by winner / by loser
        gw = sum(a - (1 if (tb and a > b) else 0) for a, b, tb in sets)
        gl = sum(b - (1 if (tb and b > a) else 0) for a, b, tb in sets)
        obs = (int(gw - brk_w + brk_l), int(gl - brk_l + brk_w))
        if obs == hw:
            return "W", "breaks"
        if obs == hl:
            return "L", "breaks"
    return None, ("inconsistent" if tried else "no_data")


# ------------------------------------------------------------------ format rules
def final_set_rule(level, tourney_name, year, best_of) -> str:
    """Final-set format: 'tb7' (7-point tiebreak at 6-6), 'tb10' (10-point at 6-6),
    'tb7@12' (7-point at 12-12) or 'adv' (no tiebreak)."""
    name = str(tourney_name).lower()
    if str(level) != "G":
        return "tb7"
    if year >= 2022:
        return "tb10"
    if "us open" in name:
        return "tb7"
    if "australian" in name:
        return "tb10" if year >= 2019 else "adv"
    if "wimbledon" in name:
        return "tb7@12" if year >= 2019 else "adv"
    return "adv"                                           # Roland Garros before 2022


# ------------------------------------------------------------------ exact iid model
def hold(p):
    """P(server wins a game) at point probability p (vectorised)."""
    p = np.asarray(p, float)
    q = 1 - p
    return p ** 4 * (1 + 4 * q + 10 * q * q) + 20 * p ** 3 * q ** 3 * p * p / (1 - 2 * p * q)


def tiebreak_first(pf, po, target=7):
    """P(the player serving the tiebreak's first point wins it); pf, po: point-on-serve probabilities
    of that player and of the other one. First server serves point 1, then two each."""
    pf, po = np.asarray(pf, float), np.asarray(po, float)
    n = pf.shape
    S = {(0, 0): np.ones(n)}
    win = np.zeros(n)
    t = target
    for tot in range(0, 2 * t - 2):
        for a in range(0, tot + 1):
            b = tot - a
            pr = S.pop((a, b), None)
            if pr is None:
                continue
            f_serves = ((tot + 1) // 2) % 2 == 0
            pw = pf if f_serves else 1 - po
            for na, nb, w in ((a + 1, b, pw), (a, b + 1, 1 - pw)):
                v = pr * w
                if na == t and nb <= t - 2:
                    win = win + v
                elif nb == t and na <= t - 2:
                    pass
                else:
                    S[(na, nb)] = S.get((na, nb), 0) + v
    tie = S.get((t - 1, t - 1), np.zeros(n))
    ww, ll = pf * (1 - po), (1 - pf) * po
    return win + tie * ww / (ww + ll)


def set_outcomes(pa, pb, a_first: bool, rule: str = "tb7", cap: int = 30):
    """{(games A, games B, tiebreak): probability array} for one set; A serves the first game when a_first."""
    pa, pb = np.asarray(pa, float), np.asarray(pb, float)
    ga, gb = hold(pa), hold(pb)
    tb_at = {"tb7": 6, "tb10": 6, "tb7@12": 12, "adv": None}[rule]
    target = 10 if rule == "tb10" else 7
    out = {}
    S = {(0, 0): np.ones(pa.shape)}
    lim = tb_at if tb_at is not None else cap
    for tot in range(0, 2 * lim + 1):
        for a in range(0, tot + 1):
            b = tot - a
            pr = S.pop((a, b), None)
            if pr is None:
                continue
            a_serves = (tot % 2 == 0) == a_first
            if tb_at is not None and a == tb_at and b == tb_at:
                # tiebreak: first point served by whoever's turn it is (game 2*tb_at+1)
                if a_serves:
                    pwin = tiebreak_first(pa, pb, target)
                else:
                    pwin = 1 - tiebreak_first(pb, pa, target)
                out[(a + 1, b, True)] = out.get((a + 1, b, True), 0) + pr * pwin
                out[(a, b + 1, True)] = out.get((a, b + 1, True), 0) + pr * (1 - pwin)
                continue
            pw = ga if a_serves else 1 - gb
            for na, nb, w in ((a + 1, b, pw), (a, b + 1, 1 - pw)):
                v = pr * w
                if na >= 6 and na - nb >= 2:
                    out[(na, nb, False)] = out.get((na, nb, False), 0) + v
                elif nb >= 6 and nb - na >= 2:
                    out[(na, nb, False)] = out.get((na, nb, False), 0) + v
                elif na <= lim and nb <= lim:
                    S[(na, nb)] = S.get((na, nb), 0) + v
                # beyond the cap (advantage sets only): mass dropped, reported by match_dist
    return out


def match_dist(pa, pb, best_of=3, final_rule="tb7", a_first=True, tmax=None, cap=30):
    """Exact joint pieces of a match where A serves the match's first game when a_first.

    Returns dict with
      pwin  : P(A wins)
      T_det, T_ind : arrays [n, tmax+1] of P(total games = t, first server determinable / not)
      H_det, H_ind : arrays [n, 2*hmax+1] of P(A games - B games = h, ...), index h + hmax
      T_det_aw, T_ind_aw : the same as T_det, T_ind restricted to A winning
      lost  : mass truncated (advantage sets beyond the cap)
    Determinable: (T mod 2) != k_F - k_O (see the module docstring)."""
    pa, pb = np.atleast_1d(np.asarray(pa, float)), np.atleast_1d(np.asarray(pb, float))
    n = len(pa)
    need = (best_of + 1) // 2
    if tmax is None:
        tmax = 13 * best_of + (2 * cap if final_rule == "adv" else 12 if final_rule == "tb7@12" else 0) + 2
    hmax = tmax
    normal = {af: set_outcomes(pa, pb, af, "tb7") for af in (True, False)}
    final = normal if final_rule == "tb7" else {af: set_outcomes(pa, pb, af, final_rule, cap) for af in (True, False)}
    # state: (sets A, sets B, A serves next set first, d = k_F - k_O) -> (PT[n, tmax+1], PH[n, 2hmax+1])
    F_is_a = a_first
    states = {(0, 0, a_first, 0): (np.zeros((n, tmax + 1)), np.zeros((n, 2 * hmax + 1)))}
    states[(0, 0, a_first, 0)][0][:, 0] = 1.0
    states[(0, 0, a_first, 0)][1][:, hmax] = 1.0
    done = {}
    for _ in range(best_of):
        nxt = {}
        for (sa, sb, af, d), (PT, PH) in states.items():
            is_final = sa == need - 1 and sb == need - 1
            outs = final[af] if is_final else normal[af]
            for (ga_, gb_, tb), pr in outs.items():
                tg, hg = ga_ + gb_, ga_ - gb_
                if tg > tmax:
                    continue
                nd = d + ((1 if (af == F_is_a) else -1) if tb else 0)
                naf = af if tg % 2 == 0 else (not af)
                ns = (sa + (ga_ > gb_), sb + (gb_ > ga_), naf, nd)
                nPT = np.zeros_like(PT)
                nPT[:, tg:] = PT[:, :tmax + 1 - tg] * pr[:, None]
                nPH = np.zeros_like(PH)
                if hg >= 0:
                    nPH[:, hg:] = PH[:, :PH.shape[1] - hg] * pr[:, None]
                else:
                    nPH[:, :hg] = PH[:, -hg:] * pr[:, None]
                tgt = done if (ns[0] == need or ns[1] == need) else nxt
                if ns in tgt:
                    tgt[ns][0][...] += nPT
                    tgt[ns][1][...] += nPH
                else:
                    tgt[ns] = (nPT, nPH)
        states = nxt
    T_det = np.zeros((n, tmax + 1)); T_ind = np.zeros((n, tmax + 1))
    H_det = np.zeros((n, 2 * hmax + 1)); H_ind = np.zeros((n, 2 * hmax + 1))
    T_det_aw = np.zeros((n, tmax + 1)); T_ind_aw = np.zeros((n, tmax + 1))
    pwin = np.zeros(n)
    tpar = np.arange(tmax + 1) % 2
    hpar = np.abs(np.arange(-hmax, hmax + 1)) % 2
    for (sa, sb, af, d), (PT, PH) in done.items():
        det_t = tpar != d
        det_h = hpar != d
        T_det += PT * det_t; T_ind += PT * ~det_t
        H_det += PH * det_h; H_ind += PH * ~det_h
        if sa == need:
            pwin += PT.sum(1)
            T_det_aw += PT * det_t; T_ind_aw += PT * ~det_t
    lost = 1 - (T_det.sum(1) + T_ind.sum(1))
    return {"pwin": pwin, "T_det": T_det, "T_ind": T_ind, "H_det": H_det, "H_ind": H_ind, "lost": lost,
            "T_det_aw": T_det_aw, "T_ind_aw": T_ind_aw,
            "tmax": tmax, "hmax": hmax}


def path_likelihood(pa, pb, sets_a, best_of, final_rule, a_first):
    """P(observed set-score sequence | A served the match's first game), per match.

    sets_a: per match [(games A, games B, tb)] from A's side; one best_of and final_rule for all rows."""
    pa, pb = np.asarray(pa, float), np.asarray(pb, float)
    n = len(pa)
    out = np.ones(n)
    af = np.full(n, bool(a_first))
    need = (best_of + 1) // 2
    L = np.array([len(s) for s in sets_a])
    for j in range(int(L.max())):
        has = L > j
        for first in (True, False):
            for fin in (False, True):
                rows = np.where(has & (af == first) & ((j == 2 * need - 2) == fin))[0]
                if len(rows) == 0:
                    continue
                so = set_outcomes(pa[rows], pb[rows], first, final_rule if fin else "tb7")
                out[rows] *= np.array([so[k][i] if k in so else 0.0
                                       for i, k in enumerate(tuple(sets_a[r][j]) for r in rows)])
        flip = np.array([bool(has[r]) and (sets_a[r][j][0] + sets_a[r][j][1]) % 2 == 1 for r in range(n)])
        af = np.where(flip, ~af, af)
    return out


# ------------------------------------------------------------------ helpers on distributions
def expect_T(d, which=("T_det", "T_ind")):
    P = sum(d[w] for w in which)
    t = np.arange(P.shape[1])
    m = P.sum(1)
    return (P * t).sum(1) / np.where(m > 0, m, np.nan)


def p_over(d, line, which=("T_det", "T_ind")):
    """P(T > line | selection) for half-point lines."""
    P = sum(d[w] for w in which)
    t = np.arange(P.shape[1])
    m = P.sum(1)
    return (P * (t > line)).sum(1) / np.where(m > 0, m, np.nan)


def p_cover_a(d, line, which=("H_det", "H_ind")):
    """P(A games - B games + line > 0 | selection) (A's handicap line, half points)."""
    P = sum(d[w] for w in which)
    h = np.arange(P.shape[1]) - d["hmax"]
    m = P.sum(1)
    return (P * (h + line > 0)).sum(1) / np.where(m > 0, m, np.nan)


def expect_H(d, which=("H_det", "H_ind")):
    P = sum(d[w] for w in which)
    h = np.arange(P.shape[1]) - d["hmax"]
    m = P.sum(1)
    return (P * h).sum(1) / np.where(m > 0, m, np.nan)


def mix(dA, dB, pi_a):
    """Mixture of the two first-server cases with P(A serves first) = pi_a (array or scalar)."""
    pi_a = np.asarray(pi_a, float)
    out = {"tmax": dA["tmax"], "hmax": dA["hmax"]}
    for k in ("T_det", "T_ind", "H_det", "H_ind", "T_det_aw", "T_ind_aw"):
        out[k] = dA[k] * pi_a[..., None] + dB[k] * (1 - pi_a)[..., None]
    out["pwin"] = dA["pwin"] * pi_a + dB["pwin"] * (1 - pi_a)
    return out
