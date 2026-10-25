"""Is the in-play point model right, point by point? (Match Charting Project, linked to our Elo.)

At every charted point, P(player 1 wins the match) from:
  V0  pre-match Elo only (ignores the score): the floor any in-play model must beat;
  V1  iid point model from the score, serve rates set from Elo: pa = s0 + d, pb = s0 - d with d
      such that the model's pre-match probability equals Elo's; s0 = the tour's server
      point-win rate (fitted on matches before 2020);
  V2  V1, with each player's serve rate updated by the serve points played so far in the match:
      (k·p0 + won) / (k + played); k chosen on matches before 2020 only.
Train: charted matches 2011-2019 (choose s0 and k). Test: 2020 onwards, nothing tuned.
Metrics: point-weighted log loss, calibration slope (outcome on logit p), observed vs predicted
by band; match-resampled bootstrap. Residual checks for momentum: after a break of serve,
after a set is won or lost.
Run: python research_tests/inplay_charting/build_points.py, then this -> results.json
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))
from point_model import Match  # noqa: E402
from qa import QA  # noqa: E402

SCRATCH = os.environ.get("FS_SCRATCH", "/tmp/claude-0/-home-user-Tennis-Quant-Lab-V5/a0609b44-84ba-59ef-a5f1-f66b68d375ec/scratchpad")
SPLIT = pd.Timestamp("2020-01-01")
EPS = 1e-4
RNG = np.random.default_rng(2025)
GRID = 0.0025
_cache: dict = {}


def match_obj(pa, pb, bo, rule):
    key = (round(pa / GRID) * GRID, round(pb / GRID) * GRID, bo, rule)
    m = _cache.get(key)
    if m is None:
        if len(_cache) > 200000:
            _cache.clear()
        m = _cache[key] = Match(min(max(key[0], 0.3), 0.95), min(max(key[1], 0.3), 0.95), bo, rule)
    return m


def solve_d(p_elo, s0, bo, rule):
    """d with Match(s0 + d, s0 - d).pre() = p_elo (bisection on a monotone function)."""
    lo, hi = -0.3, 0.3
    for _ in range(30):
        mid = 0.5 * (lo + hi)
        if Match(s0 + mid, s0 - mid, bo, rule).pre() < p_elo:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def ll(y, p):
    p = np.clip(p, EPS, 1 - EPS)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def lg(p):
    p = np.clip(p, EPS, 1 - EPS)
    return np.log(p / (1 - p))


def predict(P: pd.DataFrame, s0: dict, k: float | None) -> np.ndarray:
    """In-play P(P1 wins) for each point row (rows sorted by match, point)."""
    out = np.empty(len(P))
    for mid, idx in P.groupby("match_id", sort=False).indices.items():
        g = P.iloc[idx]
        r = g.iloc[0]
        base = s0[r.tour]
        bo, rule = int(r.best_of), r.final_rule
        d = solve_d(float(np.clip(r.p_elo, 0.02, 0.98)), base, bo, rule)
        pa0, pb0 = base + d, base - d
        srv = g.p1_srv.to_numpy()
        srv_won = (g.p1_won_point.to_numpy() == srv)
        # serve points played / won BEFORE each point (exclusive cumulative sums)
        na = np.concatenate([[0], np.cumsum(srv)[:-1]])
        wa = np.concatenate([[0], np.cumsum(srv & srv_won)[:-1]])
        nb = np.concatenate([[0], np.cumsum(~srv)[:-1]])
        wb = np.concatenate([[0], np.cumsum(~srv & srv_won)[:-1]])
        cols = [g[c].to_numpy() for c in ("sa", "sb", "ga", "gb", "i", "j", "tb", "tb_first_p1")]
        for t in range(len(g)):
            if k is None:
                pa, pb = pa0, pb0
            else:
                pa = (k * pa0 + wa[t]) / (k + na[t])
                pb = (k * pb0 + wb[t]) / (k + nb[t])
            sa, sb, ga, gb, i, j, tb, tbf = (c[t] for c in cols)
            a_srv = bool(tbf) if tb else bool(srv[t])
            out[idx[t]] = match_obj(pa, pb, bo, rule).prob(int(sa), int(sb), int(ga), int(gb), a_srv, int(i), int(j))
    return out


def _predict_chunk(args):
    P, s0, k = args
    return predict(P, s0, k)


def predict_par(P: pd.DataFrame, s0: dict, k: float | None, workers: int = 4) -> np.ndarray:
    """predict() split by match across processes; same result, in P's row order."""
    from multiprocessing import Pool
    ids = P.match_id.drop_duplicates().to_numpy()
    parts = [ids[w::workers] for w in range(workers)]
    pos = [np.where(P.match_id.isin(set(part)).to_numpy())[0] for part in parts]
    with Pool(workers) as pool:
        res = pool.map(_predict_chunk, [(P.iloc[ix].reset_index(drop=True), s0, k) for ix in pos])
    out = np.empty(len(P))
    for ix, r in zip(pos, res):
        out[ix] = r
    return out


def boot_match(P, vals, reps=1000):
    """Mean of a per-point quantity, resampling whole matches."""
    g = pd.DataFrame({"m": P.match_id.to_numpy(), "v": vals}).groupby("m").v.agg(["sum", "count"])
    s, c = g["sum"].to_numpy(), g["count"].to_numpy()
    est = s.sum() / c.sum()
    bs = []
    for _ in range(reps):
        i = RNG.integers(0, len(s), len(s))
        bs.append(s[i].sum() / c[i].sum())
    return {"est": round(float(est), 5), "lo": round(float(np.percentile(bs, 2.5)), 5), "hi": round(float(np.percentile(bs, 97.5)), 5)}


def slope(y, p):
    X = np.c_[np.ones(len(y)), lg(p)]
    b = np.zeros(2)
    for _ in range(30):
        q = 1 / (1 + np.exp(-X @ b))
        H = (X * (q * (1 - q))[:, None]).T @ X
        b += np.linalg.solve(H, X.T @ (y - q))
    return float(b[1])


def slope_boot(P, p, reps=200):
    mids = P.match_id.to_numpy()
    um, inv = np.unique(mids, return_inverse=True)
    y = P.y.to_numpy()
    est = slope(y, p)
    bs = []
    order = np.argsort(inv, kind="stable")
    starts = np.r_[0, np.cumsum(np.bincount(inv))]
    for _ in range(reps):
        pick = RNG.integers(0, len(um), len(um))
        idx = np.concatenate([order[starts[g]:starts[g + 1]] for g in pick])
        bs.append(slope(y[idx], p[idx]))
    return {"est": round(est, 3), "lo": round(float(np.percentile(bs, 2.5)), 3), "hi": round(float(np.percentile(bs, 97.5)), 3)}


def bands(P, p):
    y = P.y.to_numpy()
    out = {}
    for lo in np.arange(0.0, 1.0, 0.1):
        m = (p >= lo) & (p < lo + 0.1)
        if m.sum() < 500:
            continue
        r = boot_match(P[m], y[m] - p[m], reps=300)
        out[f"{lo:.1f}-{lo + 0.1:.1f}"] = {"points": int(m.sum()), "predicted": round(float(p[m].mean()), 4),
                                           "observed": round(float(y[m].mean()), 4), "obs_minus_pred": r}
    return out


def momentum(P, p):
    """Residual y - p at points right after an event, from P1's view (positive = P1 does better
    than the model says)."""
    g = P.groupby("match_id", sort=False)
    prev_ga, prev_gb = g.ga.shift(), g.gb.shift()
    prev_srv = g.p1_srv.shift()
    prev_sa, prev_sb = g.sa.shift(), g.sb.shift()
    new_game = (P.i == 0) & (P.j == 0) & ((prev_ga != P.ga) | (prev_gb != P.gb)) & (prev_sa == P.sa) & (prev_sb == P.sb)
    p1_won_game = P.ga > prev_ga
    broke = new_game & p1_won_game & (prev_srv == False)          # noqa: E712  P1 broke P2
    was_broken = new_game & ~p1_won_game & (prev_srv == True)     # noqa: E712  P2 broke P1
    won_set = (P.sa > prev_sa)
    lost_set = (P.sb > prev_sb)
    res = P.y.to_numpy() - p
    out = {}
    for name, m in (("just broke serve", broke), ("just lost serve", was_broken), ("just won a set", won_set),
                    ("just lost a set", lost_set)):
        m = m.to_numpy(bool)
        if m.sum() >= 300:
            out[name] = {"n": int(m.sum()), "mean_p": round(float(p[m].mean()), 4), **boot_match(P[m], res[m], reps=500)}
    return out


def evaluate(P, preds):
    y = P.y.to_numpy()
    R = {"matches": int(P.match_id.nunique()), "points": int(len(P))}
    for name, p in preds.items():
        R[name] = {"log_loss": boot_match(P, ll(y, p)), "slope": slope_boot(P, p)}
    for name in [n for n in preds if n != "V0_elo_only"]:
        R[f"gain_{name}_vs_V0"] = boot_match(P, ll(y, preds["V0_elo_only"]) - ll(y, preds[name]))
    if "V2_updating" in preds:
        R["gain_V2_vs_V1"] = boot_match(P, ll(y, preds["V1_iid_from_elo"]) - ll(y, preds["V2_updating"]))
    return R


def main():
    qa = QA("inplay_charting_calibration")
    P = pd.read_pickle(os.path.join(SCRATCH, "inplay_points.pkl")).sort_values(["match_id", "pt"]).reset_index(drop=True)
    tr, te = P[P.date < SPLIT].reset_index(drop=True), P[P.date >= SPLIT].reset_index(drop=True)
    qa.count("train matches", tr.match_id.nunique()); qa.count("test matches", te.match_id.nunique())
    s0 = {t: float((g.p1_won_point == g.p1_srv).mean()) for t, g in tr.groupby("tour")}
    for t, v in s0.items():
        qa.check(f"server point-win rate, {t} (train)", v, 0.52 if t == "WTA" else 0.58, 0.60 if t == "WTA" else 0.68)
    # choose k on a subsample of training matches (every 2nd match)
    sub_ids = tr.match_id.drop_duplicates().iloc[::2]
    trs = tr[tr.match_id.isin(sub_ids)].reset_index(drop=True)
    k_scores = {}
    for k in (25, 50, 100, 200, 400, 800):
        k_scores[k] = float(ll(trs.y.to_numpy(), predict_par(trs, s0, k)).mean())
        print("k", k, round(k_scores[k], 5), flush=True)
    v1_train = float(ll(trs.y.to_numpy(), predict_par(trs, s0, None)).mean())
    k_best = min(k_scores, key=k_scores.get)
    preds = {"V0_elo_only": te.p_elo.to_numpy(), "V1_iid_from_elo": predict_par(te, s0, None),
             "V2_updating": predict_par(te, s0, k_best)}
    qa.check("V1 at the first point equals Elo (median abs diff)",
             np.median(np.abs(preds["V1_iid_from_elo"][te.pt.to_numpy() == 0] - te.p_elo.to_numpy()[te.pt.to_numpy() == 0])), 0, 0.03)
    R = {"s0_train": s0, "k_scores_train": k_scores, "v1_train_log_loss": v1_train, "k_chosen": k_best,
         "test": evaluate(te, preds)}
    for t in ("MEN", "WTA"):
        m = (te.tour == t).to_numpy()
        R[f"test_{t}"] = evaluate(te[m].reset_index(drop=True), {k: v[m] for k, v in preds.items()})
    R["bands_V2"] = bands(te, preds["V2_updating"])
    R["bands_V1"] = bands(te, preds["V1_iid_from_elo"])
    R["momentum_V2"] = momentum(te, preds["V2_updating"])
    R["momentum_V1"] = momentum(te, preds["V1_iid_from_elo"])
    qa.save(HERE)
    json.dump(R, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    te.assign(**{f"p_{k}": v for k, v in preds.items()}).to_pickle(os.path.join(SCRATCH, "inplay_test_preds.pkl"))
    print(json.dumps({k: R["test"][k] for k in R["test"]}, indent=1))
    print(json.dumps(R["momentum_V2"], indent=1))


if __name__ == "__main__":
    main()
