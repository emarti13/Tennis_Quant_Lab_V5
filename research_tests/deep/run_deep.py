"""Deep sequence model vs leak-free Elo vs summary-stat LightGBM, then a market test on Pinnacle.

Research script (scratchpad only). Reproducible: fixed seeds, numpy-only GRU (PyTorch's
download host is blocked here), manual backprop with a gradient check.

Leakage rules: a player's history for a match in event E at (stage, rank) holds only
- that player's matches in other events whose last tennis week < E's first week, and
- that player's matches in E at an earlier (stage, rank) (same round concurrent; unknown round
  sees nothing of its own event),
ordered by (event last week, event first week, event, stage, rank). Walkovers are dropped.
Elo comes from v5_baseline_elo.run (PRODUCTION_PARAMS); each historical row's own/opponent Elo
is the pre-match rating that run used. Matches are oriented at random. Nothing dated
2026-10-13 or later is used (one-date events starting 2026-10-12 are dropped as well).

Usage: python run_deep.py [--quick]
"""
from __future__ import annotations

import os
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")   # small matmuls: threading is 8x slower here
os.environ.setdefault("MKL_NUM_THREADS", "1")
import json
import math
import warnings
warnings.filterwarnings("ignore", category=RuntimeWarning)
import re
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path("/home/user/Tennis_Quant_Lab_V5")
sys.path.insert(0, str(REPO))
import v5_baseline_elo as elo  # noqa: E402
from v5_fatigue_features import event_table, tennis_week  # noqa: E402

HERE = Path(__file__).resolve().parent
SCRATCH = HERE.parent.parent
SEED = 20261020
K = 30                       # sequence length
CUTOFF = pd.Timestamp("2026-10-13")
QUICK = "--quick" in sys.argv
T0 = time.time()


def log(*a):
    print(f"[{time.time() - T0:7.1f}s]", *a, flush=True)


# ============================================================ data
def load() -> pd.DataFrame:
    p = SCRATCH / "matches_serve.pkl"
    m = pd.read_pickle(p) if p.exists() else elo.load_matches(REPO)
    m = m[m["date"] < CUTOFF].copy()
    g = m.groupby(["tour", "tid"])["date"]
    one_date = g.transform("nunique") == 1
    m = m[~(one_date & (g.transform("min") >= pd.Timestamp("2026-10-12")))]
    return m.reset_index(drop=True)


RAW_COLS = ["tourney_id", "round", "winner_id", "loser_id", "indoor", "winner_hand", "loser_hand", "winner_ht",
            "loser_ht", "winner_rank", "loser_rank", "winner_rank_points", "loser_rank_points", "winner_seed",
            "loser_seed", "winner_entry", "loser_entry", "w_bpSaved", "w_bpFaced", "l_bpSaved", "l_bpFaced",
            "w_SvGms", "l_SvGms"]


def raw_join(m: pd.DataFrame) -> pd.DataFrame:
    parts = []
    for f in ["ATP", "ATPQualifiers", "Challenger", "WTA"]:
        r = pd.read_csv(REPO / ".v5_history_cache" / f"{f}.csv", usecols=RAW_COLS, dtype=str, low_memory=False)
        r["tour"] = "WTA" if f == "WTA" else "MEN"
        parts.append(r)
    r = pd.read_csv(REPO / "v5_results_ready" / "tennismylife_results.csv", usecols=RAW_COLS + ["result_file"],
                    dtype=str, low_memory=False)
    r["tour"] = np.where(r["result_file"].str.contains("wta"), "WTA", "MEN")
    parts.append(r.drop(columns="result_file"))
    raw = pd.concat(parts, ignore_index=True)
    raw = raw.rename(columns={"tourney_id": "tourney_id_raw"})
    k = ["tour", "tourney_id_raw", "round", "winner_id", "loser_id"]
    raw = raw.drop_duplicates(k, keep="last")
    out = m.merge(raw, on=k, how="left", validate="m:1")
    for c in RAW_COLS[5:]:
        if c not in ("winner_hand", "loser_hand", "winner_entry", "loser_entry", "winner_seed", "loser_seed"):
            out[c] = pd.to_numeric(out[c], errors="coerce")
    return out


def elo_with_ratings(m: pd.DataFrame) -> pd.DataFrame:
    """run() plus each priced match's blended pre-match ratings (recorded via the probability call)."""
    rec = []
    orig = elo.probability
    params = elo.PRODUCTION_PARAMS

    def probe(ra, rb, surface, p):
        i = 1 + elo.SURFACES.index(surface)
        rec.append(((1 - p.blend) * ra[0] + p.blend * ra[i], (1 - p.blend) * rb[0] + p.blend * rb[i]))
        return orig(ra, rb, surface, p)

    elo.probability = probe
    try:
        res = elo.run(m, params)
    finally:
        elo.probability = orig
    assert len(rec) == len(res)
    res["elo_w"] = [a for a, _ in rec]
    res["elo_l"] = [b for _, b in rec]
    chk = 1 / (1 + 10 ** ((res["elo_l"] - res["elo_w"]) / 400))
    assert np.allclose(chk, res["p_winner"])
    return res[["key", "p_winner", "n_winner", "n_loser", "elo_w", "elo_l"]]


SET_RE = re.compile(r"(\d+)-(\d+)(?:\((\d+)\))?")


def parse_score(s) -> tuple:
    """(games_w, games_l, sets_w, sets_l, tb_w, tb_l) from the winner's view."""
    gw = gl = sw = sl = tw = tl = 0
    if not isinstance(s, str):
        return (np.nan,) * 6
    for tok in s.split():
        mm = SET_RE.fullmatch(tok.strip("[]"))
        if not mm:
            continue
        a, b = int(mm.group(1)), int(mm.group(2))
        if a > 7 or b > 7:          # match tiebreak written as a set
            if a > b:
                sw += 1; tw += 1
            elif b > a:
                sl += 1; tl += 1
            continue
        gw += a; gl += b
        if (a, b) in ((7, 6), (6, 7)) or mm.group(3):
            tw += a > b; tl += b > a
        if (a >= 6 or b >= 6) and abs(a - b) >= 1 and max(a, b) >= 6 and (abs(a - b) >= 2 or max(a, b) == 7):
            sw += a > b; sl += b > a
    return gw, gl, sw, sl, tw, tl


LEVEL_GROUP = {"G": "G", "M": "M1000", "1000": "M1000", "PM": "M1000", "500": "500", "P5": "500",
               "250": "250", "I": "250", "P": "250", "A": "250", "C": "C"}
LGROUPS = ["G", "M1000", "500", "250", "C", "other"]
ROUND_ORD = {"Q1": 0, "Q2": 0.5, "Q3": 1, "R128": 1, "R64": 2, "R32": 3, "R16": 4, "QF": 5, "SF": 6, "F": 7,
             "RR": 5, "BR": 6, "3rd/4th": 6}


def prepare() -> dict:
    cache = HERE / "prep.pkl"
    if cache.exists():
        return pd.read_pickle(cache)
    m = load()
    log("matches", len(m), m["date"].min(), m["date"].max())
    m = raw_join(m)
    log("raw join coverage (hand present)", float(m["winner_hand"].notna().mean()))
    e = elo_with_ratings(m)
    m = m.merge(e, on="key", how="left", validate="1:1")
    m = m[~m["walkover"].astype(bool) & m["p_winner"].notna()].reset_index(drop=True)
    sc = np.array([parse_score(s) for s in m["score"]], dtype=float)
    for j, c in enumerate(["g_w", "g_l", "s_w", "s_l", "tb_w", "tb_l"]):
        m[c] = sc[:, j]
    ev = event_table(m)
    m = m.join(ev[["first_week", "last_week"]], on=["tour", "tid"])
    m["week"] = m["date"].map(tennis_week)
    m["lgroup"] = m["level"].map(LEVEL_GROUP).fillna("other")
    log("prepared", len(m))
    out = {"m": m}
    pd.to_pickle(out, cache)
    return out


# ============================================================ features
def side_frame(m: pd.DataFrame, side: str) -> pd.DataFrame:
    """One row per (match, player) from `side`'s view (side = 'w' or 'l')."""
    o = "l" if side == "w" else "w"
    S, O = ("winner", "loser") if side == "w" else ("loser", "winner")
    won = 1.0 if side == "w" else 0.0
    f = pd.DataFrame(index=m.index)
    f["won"] = won
    ownE, oppE = m[f"elo_{side}"], m[f"elo_{o}"]
    f["own_elo"] = (ownE - 1500) / 200
    f["opp_elo"] = (oppE - 1500) / 200
    pexp = 1 / (1 + 10 ** ((oppE - ownE) / 400))
    f["elo_exp"] = pexp
    f["surprise"] = won - pexp
    f["opp_n"] = np.log1p(m[f"n_{O}"])
    for s in ["Hard", "Clay", "Grass"]:
        f[f"surf_{s}"] = (m["surface"].astype(str) == s).astype(float)
    f["surf_Carpet"] = (m["surface"].astype(str) == "Carpet").astype(float)
    for g in LGROUPS:
        f[f"lvl_{g}"] = (m["lgroup"] == g).astype(float)
    f["quali"] = (m["stage"] == 0).astype(float)
    f["round"] = m["round"].map(ROUND_ORD).astype(float)
    f["bo5"] = (m["best_of"] == 5).astype(float)
    f["minutes"] = m["minutes"].where((m["minutes"] > 10) & (m["minutes"] < 400)) / 100
    f["minutes_na"] = f["minutes"].isna().astype(float)
    gs, go = (m["g_w"], m["g_l"]) if side == "w" else (m["g_l"], m["g_w"])
    ss, so = (m["s_w"], m["s_l"]) if side == "w" else (m["s_l"], m["s_w"])
    ts, to = (m["tb_w"], m["tb_l"]) if side == "w" else (m["tb_l"], m["tb_w"])
    f["games_won"], f["games_lost"] = gs / 12, go / 12
    f["game_share"] = gs / (gs + go).replace(0, np.nan)
    f["sets_won"], f["sets_lost"] = ss, so
    f["tb_won"], f["tb_lost"] = ts, to
    sv = m[f"{side}_svpt"].where(m[f"{side}_svpt"] > 0)
    osv = m[f"{o}_svpt"].where(m[f"{o}_svpt"] > 0)
    f["spw"] = (m[f"{side}_1stWon"] + m[f"{side}_2ndWon"]) / sv
    f["rpw"] = 1 - (m[f"{o}_1stWon"] + m[f"{o}_2ndWon"]) / osv
    f["first_in"] = m[f"{side}_1stIn"] / sv
    f["first_won"] = m[f"{side}_1stWon"] / m[f"{side}_1stIn"].where(m[f"{side}_1stIn"] > 0)
    f["ace_rate"] = m[f"{side}_ace"] / sv
    f["df_rate"] = m[f"{side}_df"] / sv
    f["ace_against"] = m[f"{o}_ace"] / osv
    bpf = m[f"{side}_bpFaced"]
    sg = m[f"{side}_SvGms"].where(m[f"{side}_SvGms"] > 0)
    f["bp_faced_pg"] = bpf / sg
    f["bp_saved"] = m[f"{side}_bpSaved"] / bpf.where(bpf > 0)
    obpf = m[f"{o}_bpFaced"]
    f["bp_conv"] = (obpf - m[f"{o}_bpSaved"]) / obpf.where(obpf > 0)
    f["stats_na"] = f["spw"].isna().astype(float)
    ret = m["retired"].astype(bool)
    f["self_ret"] = (ret & (won == 0)).astype(float)
    f["opp_ret"] = (ret & (won == 1)).astype(float)
    f["rank"] = np.log(m[f"{S}_rank"].where(m[f"{S}_rank"] > 0))
    f["opp_rank"] = np.log(m[f"{O}_rank"].where(m[f"{O}_rank"] > 0))
    f["rank_na"] = f["rank"].isna().astype(float)
    f["opp_rank_na"] = f["opp_rank"].isna().astype(float)
    return f.astype(np.float32)


def player_ctx(m: pd.DataFrame, side: str) -> pd.DataFrame:
    S = "winner" if side == "w" else "loser"
    f = pd.DataFrame(index=m.index)
    f["elo"] = (m[f"elo_{side}"] - 1500) / 200
    f["n"] = np.log1p(m[f"n_{S}"])
    hand = m[f"{S}_hand"].astype(str)
    f["left"] = (hand == "L").astype(float)
    f["hand_na"] = (~hand.isin(["L", "R"])).astype(float)
    f["ht"] = (m[f"{S}_ht"].where(m[f"{S}_ht"].between(150, 215)) - 183) / 8
    f["ht_na"] = f["ht"].isna().astype(float)
    f["rank"] = np.log(m[f"{S}_rank"].where(m[f"{S}_rank"] > 0))
    f["rank_na"] = f["rank"].isna().astype(float)
    f["pts"] = np.log1p(m[f"{S}_rank_points"].where(m[f"{S}_rank_points"] >= 0))
    # seed / entry left out: in the historical qualifying files the seed is missing far more often for
    # winners than losers (12.7% vs 29.7% seeded, 2023-25), i.e. it is rewritten after the result (leak).
    f["age"] = (m[f"{S}_age"] - 26) / 4
    return f.astype(np.float32)


def match_ctx(m: pd.DataFrame) -> pd.DataFrame:
    f = pd.DataFrame(index=m.index)
    for s in ["Hard", "Clay", "Grass", "Carpet"]:
        f[f"surf_{s}"] = (m["surface"].astype(str) == s).astype(float)
    for g in LGROUPS:
        f[f"lvl_{g}"] = (m["lgroup"] == g).astype(float)
    f["quali"] = (m["stage"] == 0).astype(float)
    f["round"] = m["round"].map(ROUND_ORD).astype(float)
    f["bo5"] = (m["best_of"] == 5).astype(float)
    ind = m["indoor"].astype(str)
    f["indoor"] = (ind == "I").astype(float)
    f["indoor_na"] = (~ind.isin(["I", "O"])).astype(float)
    f["wta"] = (m["tour"] == "WTA").astype(float)
    return f.astype(np.float32)


def build_sequences(m: pd.DataFrame):
    """For each match row i and side (0 = winner, 1 = loser): indices (into the per-side row table,
    row id = i for winner side, n + i for loser side) of the last K visible matches, -1 padded on the
    left, and days since each."""
    n = len(m)
    pk = np.concatenate([m["winner_key"].to_numpy(), m["loser_key"].to_numpy()])
    lastw = np.concatenate([m["last_week"].to_numpy()] * 2)
    firstw = np.concatenate([m["first_week"].to_numpy()] * 2)
    stage = np.concatenate([m["stage"].to_numpy()] * 2).astype(float)
    rank = np.concatenate([m["rank"].to_numpy()] * 2).astype(float)
    ev = np.concatenate([(m["tour"] + "|" + m["tid"]).to_numpy()] * 2)
    dates = np.concatenate([m["date"].to_numpy()] * 2).astype("datetime64[D]").astype(np.int64)
    rows = pd.DataFrame({"pk": pk, "lw": lastw, "fw": firstw, "ev": ev, "st": stage,
                         "rk": np.nan_to_num(rank, nan=99.0), "r": np.arange(2 * n)})
    rows = rows.sort_values(["pk", "lw", "fw", "ev", "st", "rk"], kind="mergesort")
    idx = np.full((2 * n, K), -1, dtype=np.int32)
    for key, g in rows.groupby("pk", sort=False):
        r = g["r"].to_numpy()
        lw = g["lw"].to_numpy()
        evs = g["ev"].to_numpy()
        st = stage[r]; rk = rank[r]
        # target t: prefix = rows with lw < fw(t); plus same event with (st, rk) < target's, rank known
        cut = np.searchsorted(lw, firstw[r], side="left")
        ev_start = {}
        for j, e_ in enumerate(evs):
            ev_start.setdefault(e_, []).append(j)
        for j in range(len(r)):
            pre = list(range(max(0, cut[j] - K), cut[j]))
            if not np.isnan(rk[j]):
                same = [q for q in ev_start[evs[j]] if not np.isnan(rk[q]) and (st[q], rk[q]) < (st[j], rk[j])]
                pre = pre + same
            pre = pre[-K:]
            if pre:
                idx[r[j], K - len(pre):] = r[pre]
    days = np.where(idx >= 0, dates[:, None] - dates[np.maximum(idx, 0)], 0).astype(np.float32)
    days = np.maximum(days, 0)
    return idx, days


# ============================================================ numpy GRU model
def sig(x):
    return 1 / (1 + np.exp(-np.clip(x, -30, 30)))


class Net:
    def __init__(self, F, P, C, H=48, M=48, seed=SEED, dtype=np.float32):
        rng = np.random.default_rng(seed)
        D = 2 * H + 2 * P + C
        s = 1 / math.sqrt(H)
        self.p = {
            "Wx": rng.uniform(-s, s, (F, 3 * H)), "bx": np.zeros(3 * H), "U": rng.uniform(-s, s, (H, 3 * H)),
            "bun": np.zeros(H), "W1": rng.normal(0, math.sqrt(2 / D), (D, M)), "b1": np.zeros(M),
            "w2": rng.normal(0, math.sqrt(1 / M), (M,)), "w0": np.array([1.0]),
        }
        self.p = {k: v.astype(dtype) for k, v in self.p.items()}
        self.H, self.P, self.C, self.dtype = H, P, C, dtype

    # ---- encoder
    def enc_fwd(self, X, mask):
        p, H = self.p, self.H
        B, T, F = X.shape
        XP = (X.reshape(B * T, F) @ p["Wx"] + p["bx"]).reshape(B, T, 3 * H)
        h = np.zeros((B, H), dtype=self.dtype)
        cache = []
        for t in range(T):
            hu = h @ p["U"]
            r = sig(XP[:, t, :H] + hu[:, :H])
            z = sig(XP[:, t, H:2 * H] + hu[:, H:2 * H])
            hn = hu[:, 2 * H:] + p["bun"]
            nn_ = np.tanh(XP[:, t, 2 * H:] + r * hn)
            mt = mask[:, t:t + 1]
            hc = (1 - z) * nn_ + z * h
            cache.append((h, r, z, nn_, hn, mt))
            h = mt * hc + (1 - mt) * h
        return h, (X, cache)

    def enc_bwd(self, dh, st, g):
        p, H = self.p, self.H
        X, cache = st
        B, T, F = X.shape
        dXP = np.zeros((B, T, 3 * H), dtype=self.dtype)
        dU = np.zeros_like(p["U"]); dbun = np.zeros_like(p["bun"])
        for t in range(T - 1, -1, -1):
            h, r, z, nn_, hn, mt = cache[t]
            dhc = mt * dh
            dprev = (1 - mt) * dh + dhc * z
            dn = dhc * (1 - z)
            dz = dhc * (h - nn_)
            dan = dn * (1 - nn_ ** 2)
            dr = dan * hn
            dhn = dan * r
            daz = dz * z * (1 - z)
            dar = dr * r * (1 - r)
            dG = np.concatenate([dar, daz, dhn], axis=1)
            dU += h.T @ dG
            dbun += dhn.sum(0)
            dprev += dG @ p["U"].T
            dXP[:, t, :H] = dar; dXP[:, t, H:2 * H] = daz; dXP[:, t, 2 * H:] = dan
            dh = dprev
        dXPf = dXP.reshape(B * T, 3 * H)
        g["Wx"] += X.reshape(B * T, F).T @ dXPf
        g["bx"] += dXPf.sum(0)
        g["U"] += dU; g["bun"] += dbun

    # ---- full
    def forward(self, XA, mA, XB, mB, pA, pB, c, el, train=False):
        B = XA.shape[0]
        hAB, st = self.enc_fwd(np.concatenate([XA, XB]), np.concatenate([mA, mB]))
        hA, hB = hAB[:B], hAB[B:]
        p = self.p
        u1 = np.concatenate([hA, pA, hB, pB, c], 1)
        u2 = np.concatenate([hB, pB, hA, pA, c], 1)
        a1, a2 = u1 @ p["W1"] + p["b1"], u2 @ p["W1"] + p["b1"]
        r1, r2 = np.maximum(a1, 0), np.maximum(a2, 0)
        zz = p["w0"][0] * el + r1 @ p["w2"] - r2 @ p["w2"]
        if not train:
            return zz
        return zz, (st, u1, u2, a1, a2, r1, r2, el, B)

    def backward(self, dz, cache):
        st, u1, u2, a1, a2, r1, r2, el, B = cache
        p, H, P = self.p, self.H, self.P
        g = {k: np.zeros_like(v) for k, v in p.items()}
        g["w0"][0] = (dz * el).sum()
        g["w2"] = r1.T @ dz - r2.T @ dz
        da1 = np.outer(dz, p["w2"]) * (a1 > 0)
        da2 = -np.outer(dz, p["w2"]) * (a2 > 0)
        g["W1"] = u1.T @ da1 + u2.T @ da2
        g["b1"] = da1.sum(0) + da2.sum(0)
        du1, du2 = da1 @ p["W1"].T, da2 @ p["W1"].T
        dhA = du1[:, :H] + du2[:, H + P:2 * H + P]
        dhB = du1[:, H + P:2 * H + P] + du2[:, :H]
        self.enc_bwd(np.concatenate([dhA, dhB]).astype(self.dtype), st, g)
        return g


def bce(z, y):
    return np.logaddexp(0, z) - y * z


def grad_check():
    rng = np.random.default_rng(1)
    B, T, F, P, C = 5, 4, 3, 2, 2
    net = Net(F, P, C, H=4, M=5, seed=2, dtype=np.float64)
    XA, XB = rng.normal(size=(B, T, F)), rng.normal(size=(B, T, F))
    mA = (rng.random((B, T)) > 0.3).astype(float); mB = np.ones((B, T)); mA[:, :2] = 0
    pA, pB, c = rng.normal(size=(B, P)), rng.normal(size=(B, P)), rng.normal(size=(B, C))
    el, y = rng.normal(size=B), (rng.random(B) > 0.5).astype(float)

    def loss():
        return bce(net.forward(XA, mA, XB, mB, pA, pB, c, el), y).sum()

    z, cache = net.forward(XA, mA, XB, mB, pA, pB, c, el, train=True)
    g = net.backward(sig(z) - y, cache)
    worst = 0.0
    for k, v in net.p.items():
        for ii in range(min(v.size, 12)):
            old = v.flat[ii]
            v.flat[ii] = old + 1e-6; lp = loss()
            v.flat[ii] = old - 1e-6; lm = loss()
            v.flat[ii] = old
            num = (lp - lm) / 2e-6
            worst = max(worst, abs(num - g[k].flat[ii]) / max(1e-6, abs(num) + abs(g[k].flat[ii])))
    # antisymmetry: swapping players flips the logit
    z1 = net.forward(XA, mA, XB, mB, pA, pB, c, el)
    z2 = net.forward(XB, mB, XA, mA, pB, pA, c, -el)
    return worst, float(np.abs(z1 + z2).max())


# ============================================================ helpers
def ll(p, y):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def logit(p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def boot_ci(x, rng, reps=2000):
    x = np.asarray(x, dtype=float)
    n = len(x)
    if n == 0:
        return [np.nan, np.nan]
    means = np.array([x[rng.integers(0, n, n)].mean() for _ in range(reps)])
    return [float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))]


def fit_logit(X, y, off=None, ridge=1e-6, iters=50):
    X = np.asarray(X, float); y = np.asarray(y, float)
    off = np.zeros(len(y)) if off is None else off
    w = np.zeros(X.shape[1])
    for _ in range(iters):
        p = sig(X @ w + off)
        gr = X.T @ (p - y) + ridge * w
        Hs = X.T @ (X * (p * (1 - p))[:, None]) + ridge * np.eye(X.shape[1])
        step = np.linalg.solve(Hs, gr)
        w -= step
        if np.abs(step).max() < 1e-10:
            break
    return w


# ============================================================ main
def main():
    rng = np.random.default_rng(SEED)
    worst, asym = grad_check()
    log(f"grad check worst rel err {worst:.2e}, antisymmetry {asym:.1e}")
    assert worst < 1e-4 and asym < 1e-9

    m = prepare()["m"]
    n = len(m)
    # per-(match, side) feature rows: winner side rows 0..n-1, loser side n..2n-1
    rows = pd.concat([side_frame(m, "w"), side_frame(m, "l")], ignore_index=True)
    feat_names = list(rows.columns)
    seq_cache = HERE / f"seq_K{K}.npz"
    if seq_cache.exists():
        z_ = np.load(seq_cache); idx, days = z_["idx"], z_["days"]
    else:
        idx, days = build_sequences(m)
        np.savez(seq_cache, idx=idx, days=days)
    log("sequences built", idx.shape, "mean visible length", float((idx >= 0).sum(1).mean()))

    # leak self-test: every history row is from an earlier-visible slot
    tchk = np.random.default_rng(3).integers(0, 2 * n, 3000)
    fw = np.concatenate([m["first_week"].to_numpy()] * 2); lw = np.concatenate([m["last_week"].to_numpy()] * 2)
    evk = np.concatenate([(m["tour"] + "|" + m["tid"]).to_numpy()] * 2)
    stg = np.concatenate([m["stage"].to_numpy()] * 2).astype(float); rk = np.concatenate([m["rank"].to_numpy()] * 2)
    pk = np.concatenate([m["winner_key"].to_numpy(), m["loser_key"].to_numpy()])
    bad = 0
    for t in tchk:
        for q in idx[t][idx[t] >= 0]:
            assert pk[q] == pk[t]
            if evk[q] == evk[t]:
                bad += not (not np.isnan(rk[t]) and not np.isnan(rk[q]) and (stg[q], rk[q]) < (stg[t], rk[t]))
            else:
                bad += not (lw[q] < fw[t])
    assert bad == 0, bad
    log("leak self-test passed on 3000 targets")

    year = m["date"].dt.year.to_numpy()
    tr = (year >= 2012) & (year <= 2021)
    va = year == 2022
    te1 = (year >= 2023) & (year <= 2025)
    te2 = year == 2026
    # standardize sequence features with train-period stats (rows from matches before 2022)
    R = rows.to_numpy(np.float32)
    row_year = np.concatenate([year, year])
    base = R[row_year < 2022]
    mu, sd = np.nanmean(base, 0), np.nanstd(base, 0) + 1e-6
    binary = [i for i, c in enumerate(feat_names) if np.isin(np.unique(base[:, i][~np.isnan(base[:, i])]), [0, 1]).all()]
    mu[binary] = 0; sd[binary] = 1
    Rz = np.clip(np.nan_to_num((R - mu) / sd, nan=0.0), -6, 6).astype(np.float32)
    Rz = np.concatenate([Rz, np.zeros((1, Rz.shape[1]), np.float32)])     # padding row at -1
    dfeat = (np.log1p(days) / 3 - 1.5).astype(np.float32)

    pc = pd.concat([player_ctx(m, "w"), player_ctx(m, "l")], ignore_index=True)
    pc["hist_len"] = (idx >= 0).sum(1) / K
    PC = pc.to_numpy(np.float32)
    pmu, psd = np.nanmean(PC[row_year < 2022], 0), np.nanstd(PC[row_year < 2022], 0) + 1e-6
    pbin = [i for i in range(PC.shape[1]) if np.isin(np.unique(PC[row_year < 2022][:, i][~np.isnan(PC[row_year < 2022][:, i])]), [0, 1]).all()]
    pmu[pbin] = 0; psd[pbin] = 1
    PCz = np.clip(np.nan_to_num((PC - pmu) / psd, nan=0.0), -6, 6).astype(np.float32)
    MC = np.nan_to_num(match_ctx(m).to_numpy(np.float32))
    assert np.isfinite(Rz).all() and np.isfinite(PCz).all() and np.isfinite(MC).all()
    MC[:, list(match_ctx(m).columns).index("round")] /= 7

    # random orientation: A = winner if flip == 1
    flip = rng.integers(0, 2, n)
    a_row = np.where(flip == 1, np.arange(n), n + np.arange(n))
    b_row = np.where(flip == 1, n + np.arange(n), np.arange(n))
    y = flip.astype(np.float64)
    p_elo_A = np.where(flip == 1, m["p_winner"], 1 - m["p_winner"]).astype(np.float64)
    el_A = logit(p_elo_A)

    def gather(rows_):
        ii = idx[rows_]
        X = Rz[ii]                                          # -1 -> padding row
        X = np.concatenate([X, dfeat[rows_][:, :, None]], axis=2)
        return X, (ii >= 0).astype(np.float32)

    # ---------------- baseline 1: logistic on Elo logit
    w_e = fit_logit(np.c_[np.ones(tr.sum()), el_A[tr]], y[tr])
    p_elo_fit = sig(np.c_[np.ones(n), el_A] @ w_e)
    log("elo logistic", w_e)

    # ---------------- baseline 2: LightGBM on summary stats (masked means of the sequence features)
    import lightgbm as lgb
    Rn = np.concatenate([R, np.full((1, R.shape[1]), np.nan, np.float32)])

    def summary(rows_):
        ii = idx[rows_]
        X = Rn[ii]                                           # nan where padded or missing
        with np.errstate(all="ignore"):
            mean_all = np.nanmean(X, 1)
            mean5 = np.nanmean(X[:, -5:, :], 1)
        dd = np.where(ii >= 0, days[rows_], np.nan)
        with np.errstate(all="ignore"):
            extra = np.c_[np.nanmin(dd, 1), np.nanmean(dd, 1), (ii >= 0).sum(1)]
        return np.c_[mean_all, mean5[:, :5], extra]

    snames = [f"mean_{c}" for c in feat_names] + [f"last5_{c}" for c in feat_names[:5]] + ["days_min", "days_mean", "hist_n"]          # last-5 form: won, elos, exp, surprise

    SA, SB = summary(a_row), summary(b_row)
    Xg = np.c_[SA, SB, SA - SB, PC[a_row], PC[b_row], MC, el_A].astype(np.float32)
    Xg_sw = np.c_[SB, SA, SB - SA, PC[b_row], PC[a_row], MC, -el_A].astype(np.float32)
    params = dict(objective="binary", learning_rate=0.03, num_leaves=31, min_data_in_leaf=200,
                  feature_fraction=0.7, bagging_fraction=0.8, bagging_freq=1, lambda_l2=10.0,
                  seed=SEED, deterministic=True, num_threads=4, verbose=-1)
    dtr = lgb.Dataset(Xg[tr], y[tr], init_score=el_A[tr])
    dva = lgb.Dataset(Xg[va], y[va], init_score=el_A[va], reference=dtr)
    gbm = lgb.train(params, dtr, num_boost_round=3000, valid_sets=[dva],
                    callbacks=[lgb.early_stopping(100, verbose=False)])
    zg = (gbm.predict(Xg, raw_score=True) + el_A - gbm.predict(Xg_sw, raw_score=True) + el_A) / 2
    p_gbm = sig(zg)
    log("lgbm best iter", gbm.best_iteration)
    gain = dict(zip(gnames := [f"A_{c}" for c in snames] + [f"B_{c}" for c in snames] + [f"D_{c}" for c in snames]
                    + [f"A_{c}" for c in pc.columns] + [f"B_{c}" for c in pc.columns] + list(match_ctx(m).columns)
                    + ["elo_logit"], gbm.feature_importance("gain")))
    top_gain = sorted(gain.items(), key=lambda kv: -kv[1])[:20]
    # ablation: same LightGBM without any ranking information (rank, opp rank, ranking points)
    keep = [i for i, c in enumerate(gnames) if "rank" not in c and not c.endswith("_pts")]
    dtr2 = lgb.Dataset(Xg[tr][:, keep], y[tr], init_score=el_A[tr])
    dva2 = lgb.Dataset(Xg[va][:, keep], y[va], init_score=el_A[va], reference=dtr2)
    gbm2 = lgb.train(params, dtr2, num_boost_round=3000, valid_sets=[dva2],
                     callbacks=[lgb.early_stopping(100, verbose=False)])
    p_gbm_norank = sig((gbm2.predict(Xg[:, keep], raw_score=True) + el_A
                        - gbm2.predict(Xg_sw[:, keep], raw_score=True) + el_A) / 2)
    log("lgbm no-rank best iter", gbm2.best_iteration)

    # ---------------- deep model
    F = Rz.shape[1] + 1
    net = Net(F, PCz.shape[1], MC.shape[1], H=48, M=48)
    adam_m = {k: np.zeros_like(v) for k, v in net.p.items()}
    adam_v = {k: np.zeros_like(v) for k, v in net.p.items()}
    lr, b1_, b2_, wd, bs = 2e-3, 0.9, 0.999, 1e-5, 512
    tr_i = np.where(tr)[0]
    if QUICK:
        tr_i = tr_i[::10]

    def predict(sel):
        out = np.empty(len(sel))
        for s0 in range(0, len(sel), 4096):
            ii = sel[s0:s0 + 4096]
            XA, mA = gather(a_row[ii]); XB, mB = gather(b_row[ii])
            out[s0:s0 + 4096] = net.forward(XA, mA, XB, mB, PCz[a_row[ii]], PCz[b_row[ii]], MC[ii],
                                            el_A[ii].astype(np.float32))
        return out

    va_i = np.where(va)[0]
    best, best_p, bad_ep, step, hist = 9.0, None, 0, 0, []
    max_ep = 3 if QUICK else 30
    for ep in range(max_ep):
        perm = np.random.default_rng(SEED + ep).permutation(tr_i)
        tl = 0.0
        for s0 in range(0, len(perm), bs):
            ii = perm[s0:s0 + bs]
            XA, mA = gather(a_row[ii]); XB, mB = gather(b_row[ii])
            zz, cache = net.forward(XA, mA, XB, mB, PCz[a_row[ii]], PCz[b_row[ii]], MC[ii],
                                    el_A[ii].astype(np.float32), train=True)
            yy = y[ii].astype(np.float32)
            tl += bce(zz.astype(np.float64), yy).sum()
            g = net.backward(((sig(zz) - yy) / len(ii)).astype(np.float32), cache)
            step += 1
            for k in net.p:
                gk = g[k] + wd * net.p[k]
                adam_m[k] = b1_ * adam_m[k] + (1 - b1_) * gk
                adam_v[k] = b2_ * adam_v[k] + (1 - b2_) * gk * gk
                mh = adam_m[k] / (1 - b1_ ** step); vh = adam_v[k] / (1 - b2_ ** step)
                net.p[k] -= (lr * mh / (np.sqrt(vh) + 1e-8)).astype(net.p[k].dtype)
        vl = float(bce(predict(va_i), y[va_i]).mean())
        hist.append({"epoch": ep, "train_ll": tl / len(perm), "val_ll": vl})
        log(f"epoch {ep} train {tl / len(perm):.4f} val {vl:.4f}")
        if vl < best - 1e-5:
            best, best_p, bad_ep = vl, {k: v.copy() for k, v in net.p.items()}, 0
        else:
            bad_ep += 1
            if bad_ep >= 4:
                break
        if ep in (8, 16):
            lr *= 0.5
    net.p = best_p
    all_i = np.arange(n)
    p_deep = sig(predict(all_i))
    log("deep done")

    # ---------------- evaluation
    preds = {"elo_raw": p_elo_A, "elo_logistic": p_elo_fit, "lgbm_summary": p_gbm, "lgbm_summary_norank": p_gbm_norank,
             "deep_gru": p_deep}
    res = {"setup": {"K": K, "n_matches": int(n), "train": int(tr.sum()), "val": int(va.sum()),
                     "test_2023_2025": int(te1.sum()), "test_2026": int(te2.sum()),
                     "seq_features": feat_names + ["days_ago"], "player_ctx": list(pc.columns),
                     "match_ctx": list(match_ctx(m).columns), "grad_check_rel_err": worst,
                     "elo_logistic_w": w_e.tolist(), "lgbm_best_iter": int(gbm.best_iteration),
                     "lgbm_norank_best_iter": int(gbm2.best_iteration), "lgbm_top_gain": top_gain,
                     "deep_history": hist, "date_max": str(m["date"].max()),
                     "raw_join_coverage": float(m["winner_hand"].notna().mean())}}
    brng = np.random.default_rng(SEED + 7)

    def block(mask):
        out = {"n": int(mask.sum())}
        if mask.sum() == 0:
            return out
        L0 = ll(p_elo_fit[mask], y[mask])
        for k, p in preds.items():
            Lk = ll(p[mask], y[mask])
            out[k] = {"ll": float(Lk.mean())}
            if k != "elo_logistic":
                d = Lk - L0
                out[k]["d_vs_elo"] = float(d.mean()); out[k]["ci95"] = boot_ci(d, brng, 1000)
        d = ll(p_deep[mask], y[mask]) - ll(p_gbm[mask], y[mask])
        out["deep_minus_lgbm"] = {"d": float(d.mean()), "ci95": boot_ci(d, brng, 1000)}
        return out

    tour = m["tour"].to_numpy(); lg = m["lgroup"].to_numpy(); q = (m["stage"] == 0).to_numpy()
    for name, msk in [("val_2022", va), ("test_2023_2025", te1), ("test_2026", te2)]:
        res[name] = {"all": block(msk)}
        if name == "val_2022":
            continue
        for t in ["MEN", "WTA"]:
            res[name][t] = block(msk & (tour == t))
            for g_ in LGROUPS:
                sub = msk & (tour == t) & (lg == g_) & ~q
                if sub.sum() >= 300:
                    res[name][f"{t}_{g_}_main"] = block(sub)
            if (msk & (tour == t) & q).sum() >= 300:
                res[name][f"{t}_quali"] = block(msk & (tour == t) & q)
        thin = np.minimum(m["n_winner"], m["n_loser"]).to_numpy() < 18
        res[name]["thin_lt18"] = block(msk & thin)
        res[name]["rated_ge18"] = block(msk & ~thin)
    log("eval", json.dumps(res["test_2023_2025"]["all"]), json.dumps(res["test_2026"]["all"]))

    # ---------------- market test
    oc = pd.read_pickle(SCRATCH / "oc_j.pkl")
    oc = oc[oc["start"] < pd.Timestamp("2026-10-13", tz="UTC")]
    pos = pd.Series(np.arange(n), index=m["key"])
    have = oc["key"].isin(pos.index)
    mk = {"oc_rows": int(len(oc)), "with_prediction": int(have.sum())}
    oc = oc[have].copy()
    i_ = pos.loc[oc["key"]].to_numpy()
    p1_is_w = (oc["player1_id"].to_numpy() == m["winner_key"].to_numpy()[i_])
    assert (p1_is_w == (oc["y"].to_numpy() == 1)).all()
    for k, p in preds.items():
        pw = np.where(flip[i_] == 1, p[i_], 1 - p[i_])          # P(winner wins)
        oc[k] = np.where(p1_is_w, pw, 1 - pw)
    oc["month"] = oc["start"].dt.month
    fit_m = oc["month"] <= 6
    test_m = oc["month"] >= 7
    yo = oc["y"].to_numpy(float)
    lo = logit(oc["open_p1"].to_numpy()); lc = logit(oc["close_p1"].to_numpy())
    mk["fit_n"], mk["test_n"] = int(fit_m.sum()), int(test_m.sum())
    Lopen = ll(oc["open_p1"].to_numpy(), yo); Lclose = ll(oc["close_p1"].to_numpy(), yo)
    T_ = test_m.to_numpy()
    mk["test_ll_open"] = float(Lopen[T_].mean()); mk["test_ll_close"] = float(Lclose[T_].mean())
    for k in ["deep_gru", "lgbm_summary", "lgbm_summary_norank", "elo_logistic"]:
        lm = logit(oc[k].to_numpy())
        X = np.c_[lo, lm - lo]
        fm = fit_m.to_numpy()
        w = fit_logit(X[fm], yo[fm], off=lo[fm], ridge=1.0)      # shrinks toward the open price
        pcomb = sig(lo + X @ w)
        Lc = ll(pcomb, yo)
        d_o, d_c = Lc[T_] - Lopen[T_], Lc[T_] - Lclose[T_]
        side = np.sign(lm - lo)[T_]
        move = (oc["close_p1"].to_numpy() - oc["open_p1"].to_numpy())[T_] * side
        moveL = (lc - lo)[T_] * side
        mk[k] = {"w_open_logit": float(w[0]), "w_model_minus_open": float(w[1]),
                 "test_ll_combo": float(Lc[T_].mean()), "d_vs_open": float(d_o.mean()), "ci95_vs_open": boot_ci(d_o, brng),
                 "d_vs_close": float(d_c.mean()), "ci95_vs_close": boot_ci(d_c, brng),
                 "model_alone_test_ll": float(ll(oc[k].to_numpy()[T_], yo[T_]).mean()),
                 "move_toward_model_prob": float(move.mean()), "move_ci95": boot_ci(move, brng),
                 "move_toward_model_logit": float(moveL.mean()), "move_logit_ci95": boot_ci(moveL, brng),
                 "move_all_2026_prob": float(((oc["close_p1"] - oc["open_p1"]).to_numpy() * np.sign(lm - lo)).mean())}
        big = T_ & (np.abs(lm - lo) > 0.3)
        mvb = (oc["close_p1"].to_numpy() - oc["open_p1"].to_numpy())[big] * np.sign(lm - lo)[big]
        mk[k]["move_disagree_gt0.3logit"] = {"n": int(big.sum()), "mean": float(mvb.mean()) if big.any() else None,
                                              "ci95": boot_ci(mvb, brng)}
    res["market"] = mk
    res["runtime_s"] = time.time() - T0
    (HERE / ("results_quick.json" if QUICK else "results.json")).write_text(json.dumps(res, indent=1, default=float))
    log("market", json.dumps(mk, default=float))


if __name__ == "__main__":
    main()
