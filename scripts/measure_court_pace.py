"""Court pace and serve/return: do they beat or predict Pinnacle's opener? (research)

Usage:  python scripts/measure_court_pace.py [--matches-cache PATH] [--out docs/experiments/data/court_pace.json]

The user's question (2026-10-19): some "indoor hard" courts play much faster than others
(Brussels 76.7% first-serve points won, Almaty 73.2%, Lyon's qualifying 71.4%); big servers
should gain on fast courts. Measured here from our own results only (no outside labels):

- Serve and return skill per player: the share of service points won and of return points
  won, decayed with a one-year half-life, shrunk toward the tour average, as log-odds against
  the tour average.
- Court pace per event: how many more (or fewer) service points were won there than the two
  players' serve/return skills predict, per point, in log-odds. From earlier editions of the
  same tournament (same tour, level and name) plus the rounds of this edition already played
  (qualifying included: the Lyon case), shrunk toward zero.
- A point model: each player's chance of winning a point on serve = tour average + server's
  serve skill - returner's return skill (+ the court pace), turned into a match probability
  (games, tiebreak sets, best of 3 or 5).

Same visibility rules as v5_baseline_elo (one ordering): rounds in order, the same round
concurrent, other events only once their last week is before this event's first week.

Tests (nothing from the sealed period, 2026-10-13 on):
1) the point model alone, with and without pace, against the Elo, on 2026 matches;
2) is the pace stable (an edition's own residual against what earlier editions predicted)?
3) on top of Pinnacle's opener, as in docs/experiments/2026-10-18-open-close-edge.md (fit
   January-June, test July to October 12; both players with 18+ rated matches): open + Elo +
   fatigue, then + the point model, then + pace; log loss against the open and the close,
   and the open-to-close move toward the model's side.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
import v5_baseline_elo as be  # noqa: E402
import scripts.measure_open_close_edge as oc  # noqa: E402
from scripts.measure_baseline_elo import loss, paired  # noqa: E402

HALF_LIFE_WEEKS = 52.0
SHRINK_POINTS = 300.0          # player skill: pseudo-points at the tour average
PACE_SHRINK_POINTS = 3000.0    # event pace: pseudo-points at zero
MIN_PACE_POINTS = 0.0
SEALED_FROM = pd.Timestamp("2026-10-13")


def logit(p):
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def inv(x):
    return 1.0 / (1.0 + math.exp(-x))


# ------------------------------------------------------------------ point -> match
def hold(p: float) -> float:
    q = 1 - p
    return p ** 4 * (1 + 4 * q + 10 * q * q) + 20 * (p * q) ** 3 * p * p / (1 - 2 * p * q)


@lru_cache(maxsize=None)
def _tiebreak(pa: float, pb: float) -> float:
    """A serves first; serve pattern A, B, B, A, A, ... First to 7, two clear."""
    @lru_cache(maxsize=None)
    def f(a, b):
        if a >= 7 and a - b >= 2:
            return 1.0
        if b >= 7 and b - a >= 2:
            return 0.0
        if a == b and a >= 6:
            win_both = pa * (1 - pb)
            lose_both = (1 - pa) * pb
            return win_both / (win_both + lose_both)
        n = a + b
        server_a = (n % 4 in (0, 3))
        p = pa if server_a else 1 - pb
        return p * f(a + 1, b) + (1 - p) * f(a, b + 1)
    return f(0, 0)


@lru_cache(maxsize=None)
def _set(pa: float, pb: float) -> float:
    """A serves the first game; games alternate; tiebreak at 6-6."""
    ga, gb = hold(pa), 1 - hold(pb)        # A wins a game on own serve / on B's serve

    @lru_cache(maxsize=None)
    def f(a, b):
        if a >= 6 and a - b >= 2 or a == 7:
            return 1.0
        if b >= 6 and b - a >= 2 or b == 7:
            return 0.0
        if a == 6 and b == 6:
            return _tiebreak(pa, pb)
        p = ga if (a + b) % 2 == 0 else gb
        return p * f(a + 1, b) + (1 - p) * f(a, b + 1)
    return f(0, 0)


def match_prob(pa: float, pb: float, best_of: int) -> float:
    """P(A wins) from A's and B's chances of winning a point on serve (who serves first
    averaged out)."""
    pa, pb = round(min(max(pa, 0.3), 0.95), 3), round(min(max(pb, 0.3), 0.95), 3)
    s = 0.5 * (_set(pa, pb) + 1 - _set(pb, pa))
    need = 3 if best_of == 5 else 2
    out, n = 0.0, 2 * need - 1
    for k in range(need, n + 1):                       # P(win at least `need` of n sets)
        out += math.comb(n, k) * s ** k * (1 - s) ** (n - k)
    return out


# ------------------------------------------------------------------ ratings
def _w(week: float) -> float:
    return 2.0 ** (week / HALF_LIFE_WEEKS)            # contributions grow; ratios cancel the scale


class Book:
    """Decayed sums. players: [serve won, serve pts, return won, return pts]; tours: [won, pts];
    paces: [residual, pts] (residual in probability units)."""

    def __init__(self):
        self.players, self.tours, self.paces = {}, {}, {}

    @staticmethod
    def add(store, key, vec):
        cur = store.get(key)
        store[key] = vec.copy() if cur is None else cur + vec


def event_name(tour, level, name) -> tuple:
    return (tour, str(level), " ".join(str(name).lower().split()))


def features(view, tour, pkey, w_key, l_key, best_of):
    """Point-model probabilities for w beating l (with and without pace), the pace, and the
    skills, from the visible sums."""
    t = view("tours", tour)
    mu = (t[0] / t[1]) if t is not None and t[1] > 0 else 0.62
    out = {}
    for side, k in (("w", w_key), ("l", l_key)):
        s = view("players", k)
        sw, sp, rw, rp = (s if s is not None else np.zeros(4))
        out[f"S_{side}"] = logit((sw + SHRINK_POINTS * mu) / (sp + SHRINK_POINTS)) - logit(mu)
        out[f"R_{side}"] = logit((rw + SHRINK_POINTS * (1 - mu)) / (rp + SHRINK_POINTS)) - logit(1 - mu)
        out[f"pts_{side}"] = sp
    pc = view("paces", pkey)
    res, pts = (pc if pc is not None else np.zeros(2))
    pace = (res / (pts + PACE_SHRINK_POINTS)) / (mu * (1 - mu))
    out.update(pace=pace, pace_pts=pts, mu=mu)
    base = logit(mu)
    pw0, pl0 = inv(base + out["S_w"] - out["R_l"]), inv(base + out["S_l"] - out["R_w"])
    pw1, pl1 = inv(base + out["S_w"] - out["R_l"] + pace), inv(base + out["S_l"] - out["R_w"] + pace)
    bo = 5 if best_of == 5 else 3
    out.update(p_pt0=match_prob(pw0, pl0, bo), p_pt=match_prob(pw1, pl1, bo), pw0=pw0, pl0=pl0)
    return out


def run(matches: pd.DataFrame) -> pd.DataFrame:
    order, weeks = be._events(matches)
    by_event = {e: g for e, g in matches.groupby(["tour", "tid"], sort=False)}
    book = Book()
    pending = []                                       # (last_week, {store: {key: vec}})
    rows = []
    for e in order:
        first = weeks[e]["first_week"]
        still = []
        for last, deltas in sorted(pending, key=lambda x: x[0]):
            if last < first:
                for store, d in deltas.items():
                    for k, v in d.items():
                        Book.add(getattr(book, store), k, v)
            else:
                still.append((last, deltas))
        pending = still
        g = by_event[e]
        g = g[~g["walkover"].astype(bool)]
        if g.empty:
            continue
        r0 = g.iloc[0]
        pkey = event_name(r0["tour"], r0["level"], r0["tourney_name"])
        scale = _w(first)
        local = {"players": {}, "tours": {}, "paces": {}}

        def view(store, key, use_local=True):
            base_v = getattr(book, store).get(key)
            loc = local[store].get(key) if use_local else None
            if base_v is None and loc is None:
                return None
            v = (base_v if base_v is not None else 0) + (loc if loc is not None else 0)
            return v / scale

        def contributions(m, f):
            """This match's sums, scaled to the event's week."""
            wsp, lsp = m.w_svpt, m.l_svpt
            if not (wsp > 0 and lsp > 0) or pd.isna(m.w_1stWon) or pd.isna(m.l_1stWon):
                return None
            wsw = m.w_1stWon + (0 if pd.isna(m.w_2ndWon) else m.w_2ndWon)
            lsw = m.l_1stWon + (0 if pd.isna(m.l_2ndWon) else m.l_2ndWon)
            if wsw > wsp or lsw > lsp:
                return None
            res = (wsw - f["pw0"] * wsp) + (lsw - f["pl0"] * lsp)
            return {"players": {m.winner_key: np.array([wsw, wsp, lsp - lsw, lsp]) * scale,
                                m.loser_key: np.array([lsw, lsp, wsp - wsw, wsp]) * scale},
                    "tours": {m.tour: np.array([wsw + lsw, wsp + lsp]) * scale},
                    "paces": {pkey: np.array([res, wsp + lsp]) * scale}}

        event_deltas = {"players": {}, "tours": {}, "paces": {}}
        known = g[g["rank"].notna()]
        for _, grp in sorted(known.groupby(["stage", "rank"], sort=False), key=lambda kv: kv[0]):
            updates = []
            for m in grp.itertuples():
                f = features(view, m.tour, pkey, m.winner_key, m.loser_key, m.best_of)
                rows.append({"key": m.key, **f})
                c = contributions(m, f)
                if c:
                    updates.append(c)
            for c in updates:                          # same round: concurrent
                for store, d in c.items():
                    for k, v in d.items():
                        Book.add(local[store], k, v)
                        Book.add(event_deltas[store], k, v)
        for m in g[g["rank"].isna()].itertuples():      # unknown round: event start only
            f = features(lambda s, k: view(s, k, use_local=False), m.tour, pkey, m.winner_key, m.loser_key, m.best_of)
            rows.append({"key": m.key, **f})
            c = contributions(m, f)
            if c:
                for store, d in c.items():
                    for k, v in d.items():
                        Book.add(event_deltas[store], k, v)
        pending.append((weeks[e]["last_week"], event_deltas))
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ evaluation
def boot_mean(x, rng):
    x = np.asarray(x, float)
    b = x[rng.integers(0, len(x), size=(1000, len(x)))].mean(axis=1)
    return {"n": int(len(x)), "mean": round(float(x.mean()), 5),
            "ci95": [round(float(np.percentile(b, 2.5)), 5), round(float(np.percentile(b, 97.5)), 5)]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--matches-cache", default=None, help="a pickled v5_baseline_elo.load_matches frame with serve columns")
    ap.add_argument("--out", default="docs/experiments/data/court_pace.json")
    args = ap.parse_args()
    rng = np.random.default_rng(20261020)
    cache = Path(args.matches_cache) if args.matches_cache else None
    if cache and cache.exists():
        m = pd.read_pickle(cache)
    else:
        m = be.load_matches(BASE)
        if cache:
            m.to_pickle(cache)
    if "w_svpt" not in m:
        raise SystemExit("the match table has no serve columns (v5_fatigue_features.SERVE_COLUMNS)")
    feats = run(m).set_index("key")
    elo = be.run(m, be.PRODUCTION_PARAMS).set_index("key")
    t = elo.join(feats, how="inner")
    test = t[(t["date"].dt.year == 2026) & (t["date"] < SEALED_FROM) & (t["n_winner"] >= 18) & (t["n_loser"] >= 18)]
    report = {"params": {"half_life_weeks": HALF_LIFE_WEEKS, "shrink_points": SHRINK_POINTS,
                         "pace_shrink_points": PACE_SHRINK_POINTS}}
    report["alone_2026"] = {"n": int(len(test)), **{c: round(float(loss(test[c]).mean()), 5) for c in ("p_winner", "p_pt0", "p_pt")},
                            "pt_minus_elo": paired(loss(test["p_pt0"]), loss(test["p_winner"]), rng),
                            "pace_minus_no_pace": paired(loss(test["p_pt"]), loss(test["p_pt0"]), rng)}
    # pace stability: an edition's final residual per point vs the prior-editions estimate at its first match
    mm = m.set_index("key")[["tour", "tid", "level", "tourney_name", "date", "stage", "rank"]]
    tt = t.join(mm[["level", "tourney_name", "stage", "rank"]], how="left")
    ed = tt.sort_values(["tour", "tid", "stage", "rank"]).groupby(["tour", "tid"]).agg(
        prior=("pace", "first"), prior_pts=("pace_pts", "first"), level=("level", "first"), year=("date", lambda s: s.dt.year.iloc[0]))
    last = tt.sort_values(["tour", "tid", "stage", "rank"]).groupby(["tour", "tid"])["pace"].last()
    ed["final"] = last
    ok = ed[(ed["prior_pts"] > 5000) & (ed["year"] >= 2015)]
    report["pace_stability"] = {"editions": int(len(ok)), "corr_prior_vs_final": round(float(ok["prior"].corr(ok["final"])), 3),
                                "pace_sd_logit": round(float(ok["prior"].std()), 4),
                                "by_level_corr": {str(k): round(float(g["prior"].corr(g["final"])), 3)
                                                  for k, g in ok.groupby("level") if len(g) > 50}}
    # on top of Pinnacle's open
    j = oc.build(BASE, str(cache) if cache else None)
    j = j[j["n_min"] >= 18].copy()
    j = j.join(feats[["p_pt0", "p_pt", "pace", "S_w", "S_l", "R_w", "R_l"]], on="key")
    j = j.dropna(subset=["p_pt0"])
    flip = j["y"] == 0                                 # features are winner-first; turn them to fixture p1
    for c0, c1 in (("p_pt0", None), ("p_pt", None)):
        j[c0] = np.where(flip, 1 - j[c0], j[c0])
    j["serve_gap"] = np.where(flip, -1, 1) * ((j["S_w"] - j["R_l"]) - (j["S_l"] - j["R_w"]))
    j["elo_gap"] = oc.logit(j["elo_p1"]) - oc.logit(j["open_p1"])
    j["pt_gap"] = oc.logit(j["p_pt0"]) - oc.logit(j["open_p1"])
    j["pace_gap"] = oc.logit(j["p_pt"]) - oc.logit(j["p_pt0"])
    j["pace_x_serve"] = j["pace"] * j["serve_gap"]
    fat = [f"d_{c}" for c in oc.FATIGUE] + [f"d_{c}_missing" for c in oc.FATIGUE]
    sets = {"open+elo+fatigue": ["elo_gap"] + fat,
            "+point model": ["elo_gap", "pt_gap"] + fat,
            "+point model+pace": ["elo_gap", "pt_gap", "pace_gap", "pace_x_serve"] + fat}
    train, test = j[j["start"] < oc.TEST_FROM], j[j["start"] >= oc.TEST_FROM].copy()
    y = test["y"].to_numpy()
    ll = lambda p: loss(np.where(y == 1, p, 1 - p))  # noqa: E731
    open_l, close_l = ll(test["open_p1"].to_numpy()), ll(test["close_p1"].to_numpy())
    move = (test["close_p1"] - test["open_p1"]).to_numpy()
    res = {"n_train": int(len(train)), "n_test": int(len(test)),
           "open": round(float(open_l.mean()), 5), "close": round(float(close_l.mean()), 5), "models": {}}
    shifts = {}
    for name, cols in sets.items():
        Xtr, mu, sd = oc.design(train, cols)
        Xte, _, _ = oc.design(test, cols, mu, sd)
        w = oc.fit_logistic(np.c_[Xtr, np.ones(len(Xtr))], train["y"].to_numpy(float), oc.logit(train["open_p1"]))
        p = 1 / (1 + np.exp(-(oc.logit(test["open_p1"]) + np.c_[Xte, np.ones(len(Xte))] @ w)))
        shift = p - test["open_p1"].to_numpy()
        shifts[name] = shift
        fam = test["family"].to_numpy()
        res["models"][name] = {
            "log_loss": round(float(ll(p).mean()), 5),
            "model_minus_open": paired(ll(p), open_l, rng),
            "move_toward_pick": boot_mean(np.sign(shift) * move, rng),
            "move_toward_pick_by_family": {f: boot_mean((np.sign(shift) * move)[fam == f], rng)
                                           for f in ("ATP", "CHALLENGER", "WTA") if (fam == f).sum() > 50},
            "weights": dict(zip(cols[:4] + ["..."], np.round(w[:4], 4).tolist())),
        }
    gain = np.sign(shifts["+point model+pace"]) * move - np.sign(shifts["open+elo+fatigue"]) * move
    res["pace_model_minus_baseline_move"] = boot_mean(gain, rng)
    report["on_pinnacle_open"] = res
    out = BASE / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1, default=str) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
