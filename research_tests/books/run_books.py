"""Execution books and Kalshi vs Pinnacle: taker-return tests on pre-sealed fixtures.

Run: python run_books.py  (from any cwd). Writes results.json next to this file.
Uses only fixtures with true start < 2026-10-13 (sealed period excluded).
"""
from __future__ import annotations

import glob
import json
import math
import re
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path("/home/user/Tennis_Quant_Lab_V5")
HERE = Path(__file__).resolve().parent
SCRATCH = HERE.parent.parent
SEAL = pd.Timestamp("2026-10-13", tz="UTC")
SPLIT = pd.Timestamp("2026-07-01", tz="UTC")
BOOKS = ["betrivers", "draftkings", "bet365"]
CPS = ["t24h", "t12h", "t6h", "t1h", "close"]
THRS = [0.0, 0.02, 0.04, 0.06]
B = 2000
RNG = np.random.default_rng(20261020)


def boot(ret: np.ndarray, cluster: np.ndarray) -> dict:
    """Mean return per dollar, 95% bootstrap range resampling fixtures (clusters)."""
    n = len(ret)
    if n == 0:
        return {"n": 0}
    df = pd.DataFrame({"r": ret, "c": cluster}).groupby("c")["r"].agg(["sum", "count"])
    s, c = df["sum"].to_numpy(), df["count"].to_numpy()
    k = len(s)
    idx = RNG.integers(0, k, size=(B, k))
    means = s[idx].sum(1) / c[idx].sum(1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return {"n": int(n), "fixtures": int(k), "mean": round(float(ret.mean()), 4),
            "lo": round(float(lo), 4), "hi": round(float(hi), 4)}


def summarize(bets: pd.DataFrame, ret_col: str = "ret") -> dict:
    out = {"all": boot(bets[ret_col].to_numpy(), bets["fixture_id"].to_numpy())}
    for half, m in (("H1_JanJun", bets.start < SPLIT), ("H2_JulOct12", bets.start >= SPLIT)):
        out[half] = boot(bets.loc[m, ret_col].to_numpy(), bets.loc[m, "fixture_id"].to_numpy())
    for fam, g in bets.groupby("family"):
        if len(g) >= 100:
            out["fam_" + fam] = boot(g[ret_col].to_numpy(), g["fixture_id"].to_numpy())
    return out


# ---------------------------------------------------------------- load
def load():
    fx = pd.concat([pd.read_csv(f) for f in sorted(glob.glob(str(REPO / "market_history/fixtures/*.csv")))])
    fx = fx[fx.resolution == "ok"].drop_duplicates("fixture_id", keep="last")
    fx["start"] = pd.to_datetime(fx.cutoff_utc, utc=True)
    fx = fx[fx.start < SEAL]
    fx["family"] = fx.edition_key.str.split("|").str[0]
    pp = pd.concat([pd.read_csv(f) for f in sorted(glob.glob(str(REPO / "market_history/price_points/*.csv")))])
    pp = pp[pp.fixture_id.isin(fx.fixture_id)]
    # close: missing when stale (spec 5.4)
    pp.loc[pp.close_stale.astype(str) == "True", "close_price"] = np.nan
    oc = pd.read_pickle(SCRATCH / "oc_j.pkl")[["fixture_id", "y", "key", "player1_id", "player2_id", "winner_key"]]
    oc = oc[oc.fixture_id.isin(fx.fixture_id)]
    return fx, pp, oc


def parse_games(score: str):
    """Winner games, loser games, sets won by winner, sets won by loser; None if unparseable."""
    if not isinstance(score, str):
        return None
    w = l = sw = sl = 0
    for tok in score.split():
        m = re.fullmatch(r"(\d+)-(\d+)(\(\d+\))?", tok)
        if not m:
            return None
        a, b = int(m.group(1)), int(m.group(2))
        w += a; l += b
        sw += a > b; sl += b > a
    return w, l, sw, sl


def game_results(oc):
    ms = pd.read_pickle(SCRATCH / "matches_serve.pkl")[["key", "score", "retired", "walkover"]]
    ms = ms[ms.key.isin(oc.key)].drop_duplicates("key")
    ms = ms[(~ms.retired.astype(bool)) & (~ms.walkover.astype(bool))]
    g = ms.score.map(parse_games)
    ms = ms[g.notna()].copy()
    g = g[g.notna()]
    ms["wg"] = [x[0] for x in g]; ms["lg"] = [x[1] for x in g]
    ms["ok"] = [x[2] > x[3] and x[2] >= 2 for x in g]  # winner must have won more sets
    ms = ms[ms.ok]
    r = oc.merge(ms[["key", "wg", "lg"]], on="key")
    p1won = r.winner_key == r.player1_id
    r["g1"] = np.where(p1won, r.wg, r.lg)
    r["g2"] = np.where(p1won, r.lg, r.wg)
    r["total"] = r.g1 + r.g2
    return r[["fixture_id", "g1", "g2", "total"]]


# ---------------------------------------------------------------- tests 1-2
def book_vs_pinnacle(pp, fx, res, market, side_a, side_b, outcome_fn):
    """Generic: per (fixture, line, checkpoint) Pinnacle fair from two sides; book EV; bets."""
    m = pp[pp.market_group == market].copy()
    m["line"] = m.line.fillna(0.0) if market == "moneyline" else m.line
    # key for pairing: for spreads p2 line = -p1 line; use p1's line as the market line
    if market == "game_spread":
        m["mline"] = np.where(m.side == "p1", m.line, -m.line)
    else:
        m["mline"] = m.line
    m = m.drop_duplicates(["fixture_id", "bookmaker", "mline", "side"], keep="last")
    rows = []
    for cp in CPS:
        col = f"{cp}_price"
        w = m.pivot_table(index=["fixture_id", "mline"], columns=["bookmaker", "side"], values=col, aggfunc="first")
        if ("pinnacle", side_a) not in w or ("pinnacle", side_b) not in w:
            continue
        pa, pb = w[("pinnacle", side_a)], w[("pinnacle", side_b)]
        ia, ib = 1 / pa, 1 / pb
        fa = ia / (ia + ib)
        for bk in BOOKS:
            for side, fair in ((side_a, fa), (side_b, 1 - fa)):
                if (bk, side) not in w or (bk, side_a) not in w or (bk, side_b) not in w:
                    continue
                price = w[(bk, side)]
                ok = fair.notna() & price.notna() & w[(bk, side_a)].notna() & w[(bk, side_b)].notna()
                d = pd.DataFrame({"fair": fair[ok], "price": price[ok]}).reset_index()
                d["book"], d["side"], d["cp"] = bk, side, cp
                rows.append(d)
    q = pd.concat(rows, ignore_index=True)
    q["ev"] = q.fair * q.price - 1
    q = q.merge(res, on="fixture_id").merge(fx[["fixture_id", "start", "family"]], on="fixture_id")
    q["ret"] = outcome_fn(q)
    q = q[q.ret.notna()]
    out = {}
    for cp in CPS:
        for thr in THRS:
            sel = q[(q.cp == cp) & (q.ev > thr)]
            cell = {}
            for bk in BOOKS:
                cell[bk] = summarize(sel[sel.book == bk])
            # pooled: best price per fixture-line-side
            best = sel.sort_values("price").drop_duplicates(["fixture_id", "mline", "side"], keep="last")
            cell["best_of_books"] = summarize(best)
            cell["mean_ev_claimed"] = round(float(sel.ev.mean()), 4) if len(sel) else None
            out[f"{cp}|ev>{thr:.2f}"] = cell
    # baseline: all quoted sides (no filter) per book & checkpoint -> book margin vs results
    base = {f"{cp}|{bk}": boot(g.ret.to_numpy(), g.fixture_id.to_numpy())
            for (cp, bk), g in q.groupby(["cp", "book"])}
    return out, base, q


def ml_outcome(q):
    won = np.where(q.side == "p1", q.y == 1, q.y == 0)
    return np.where(won, q.price - 1, -1.0)


def tot_outcome(q):
    diff = np.where(q.side == "Over", q.total - q.mline, q.mline - q.total)
    return np.where(diff > 0, q.price - 1, np.where(diff == 0, 0.0, -1.0))


def spr_outcome(q):
    # mline is p1's handicap: p1 covers if g1 - g2 + mline > 0
    marg = q.g1 - q.g2 + q.mline
    diff = np.where(q.side == "p1", marg, -marg)
    return np.where(diff > 0, q.price - 1, np.where(diff == 0, 0.0, -1.0))


# ---------------------------------------------------------------- test 3 Kalshi
def kalshi_fee(price, contracts=100):
    return math.ceil(0.07 * contracts * price * (1 - price) * 100 - 1e-9) / 100.0 / contracts


def kalshi(pp, fx):
    kp = pd.concat([pd.read_csv(f) for f in sorted(glob.glob(str(REPO / "market_history/kalshi/price_points/*.csv")))])
    km = pd.concat([pd.read_csv(f) for f in sorted(glob.glob(str(REPO / "market_history/kalshi/markets/*.csv")))])
    fm = pd.read_csv(REPO / "market_history/kalshi/fixture_map.csv")
    fm = fm[fm.match_method == "names"][["ticker", "fixture_id", "side"]]
    km = km.drop_duplicates("ticker", keep="last")[["ticker", "result", "cutoff_source", "cutoff_utc", "family"]]
    k = kp.drop(columns=["fixture_id", "side"]).drop_duplicates("ticker", keep="last").merge(fm, on="ticker").merge(km, on="ticker")
    n_occ = int((k.cutoff_source == "kalshi_occurrence").sum())
    k = k[(k.cutoff_source != "kalshi_occurrence") & k.result.isin(["yes", "no"])]
    k["start"] = pd.to_datetime(k.cutoff_utc, utc=True)
    k = k[k.start < SEAL]
    k["win"] = (k.result == "yes").astype(float)
    pin = pp[(pp.bookmaker == "pinnacle") & (pp.market_group == "moneyline")].drop_duplicates(["fixture_id", "side"], keep="last")
    snap = snapshot_fair(k)
    rows, conv = [], []
    for cp in ["t24h", "t12h", "t6h", "t1h"]:
        w = pin.pivot(index="fixture_id", columns="side", values=f"{cp}_price")
        f1 = (1 / w.p1) / (1 / w.p1 + 1 / w.p2)
        fair = pd.concat([pd.DataFrame({"fixture_id": f1.index, "side": "p1", "fair": f1.values}),
                          pd.DataFrame({"fixture_id": f1.index, "side": "p2", "fair": 1 - f1.values})])
        fair["src"] = "price_points"
        s2 = snap[snap.cp == cp][["fixture_id", "side", "fair"]].assign(src="snapshot")
        s2 = s2[~s2.fixture_id.isin(fair.dropna().fixture_id)]
        fair = pd.concat([fair.dropna(), s2])
        d = k.merge(fair, on=["fixture_id", "side"])
        d = d[d.fair.notna() & d[f"{cp}_ask"].between(0.01, 0.99) & d[f"{cp}_bid"].notna()]
        d = d.assign(cp=cp, ask=d[f"{cp}_ask"], bid=d[f"{cp}_bid"])
        d["fee"] = d.ask.map(kalshi_fee)
        d["edge"] = d.fair - d.ask - d.fee
        d["ret"] = (d.win - d.ask - d.fee) / (d.ask + d.fee)  # per dollar spent
        rows.append(d)
        # convergence: mid now vs mid at the close (pre-start, true_start cutoff only)
        nxt = d[d.close_bid.notna() & d.close_ask.notna()].copy()
        nxt["mid"] = (nxt.bid + nxt.ask) / 2
        nxt["mid_close"] = (nxt.close_bid + nxt.close_ask) / 2
        nxt["gap"] = nxt.fair - nxt.mid
        conv.append(nxt)
    q = pd.concat(rows, ignore_index=True)
    out = {"n_excluded_occurrence_cut": n_occ, "fair_source_counts": {f"{a}|{b}": int(v) for (a, b), v in q.drop_duplicates(["fixture_id", "cp"]).groupby(["cp", "src"]).size().items()}, "fixtures": int(q.fixture_id.nunique()),
           "date_range": [str(q.start.min()), str(q.start.max())]}
    for cp in ["t24h", "t12h", "t6h", "t1h"]:
        for thr in [0.0, 0.02, 0.04]:
            sel = q[(q.cp == cp) & (q.edge > thr)]
            r = summarize(sel)
            r["mean_edge_claimed_c"] = round(float(sel.edge.mean() * 100), 2) if len(sel) else None
            out[f"{cp}|edge>{thr:.2f}"] = r
    c = pd.concat(conv, ignore_index=True)
    cv = {}
    for cp, g in c.groupby("cp"):
        g = g[g.gap.abs() >= 0.02]
        g = g.drop_duplicates("fixture_id")  # one side per fixture (sides mirror)
        move = (g.mid_close - g.mid) * np.sign(g.gap)
        cv[cp] = {"n_gap_ge_2c": int(len(g)), "mean_gap_c": round(float(g.gap.abs().mean() * 100), 2),
                  "mean_move_toward_pin_c": round(float(move.mean() * 100), 2),
                  "share_closed_toward": round(float((move > 0).mean()), 3),
                  "share_moved_away": round(float((move < 0).mean()), 3),
                  "frac_gap_closed": round(float(move.sum() / g.gap.abs().sum()), 3)}
    out["convergence_to_kalshi_close"] = cv
    # who is closer to the result: Kalshi mid vs Pinnacle fair log loss at each cp
    ll = {}
    for cp, g in c.groupby("cp"):
        g = g.drop_duplicates("fixture_id")
        pm = g.mid.clip(0.01, 0.99); pf = g.fair.clip(0.01, 0.99)
        ll[cp] = {"n": int(len(g)),
                  "kalshi_mid": round(float(-(g.win * np.log(pm) + (1 - g.win) * np.log(1 - pm)).mean()), 4),
                  "pinnacle": round(float(-(g.win * np.log(pf) + (1 - g.win) * np.log(1 - pf)).mean()), 4)}
    out["logloss_kalshi_vs_pinnacle"] = ll
    return out


SNAP = REPO / "v5_daily_ready/market_snapshot_history.csv"
FROZEN = REPO / "v5_daily_ready/frozen_predictions.csv"


def snapshot_fair(k):
    """Pinnacle de-vigged moneyline from the production snapshot ledger (Sep 13 on), where the
    OddsPapi price store has a gap. A snapshot is assigned to Kalshi checkpoint N when it was
    taken 0-1.5 h BEFORE start-N (Pinnacle info never later than the Kalshi quote)."""
    m = pd.concat([pd.read_csv(SNAP, low_memory=False), pd.read_csv(FROZEN, low_memory=False)])
    m = m[(m.market_group == "moneyline") & (m.best_bookmaker == "pinnacle") & (m.books_in_consensus == 1)]
    m = m[m.fixture_id.isin(k.fixture_id)].copy()
    m["side"] = np.where(m.selection == m.player1, "p1", np.where(m.selection == m.player2, "p2", None))
    m = m[m.side.notna()].drop_duplicates(["fixture_id", "side", "snapshot_utc"])
    st = k.drop_duplicates("fixture_id").set_index("fixture_id").start
    m["lead_h"] = (m.fixture_id.map(st) - pd.to_datetime(m.snapshot_utc, utc=True, format="ISO8601")).dt.total_seconds() / 3600
    out = []
    for cp, h in (("t24h", 24), ("t12h", 12), ("t6h", 6), ("t1h", 1)):
        g = m[(m.lead_h >= h) & (m.lead_h <= h + 1.5)].sort_values("lead_h")
        g = g.drop_duplicates(["fixture_id", "side"], keep="first")  # latest snapshot before cp
        out.append(g.assign(cp=cp, fair=g.best_book_no_vig_prob)[["fixture_id", "side", "cp", "fair"]])
    o = pd.concat(out)
    # side mapping checked against Kalshi player_name surnames: 308/308 agree
    return o


# ---------------------------------------------------------------- test 4
def pinnacle_time(pp, fx, oc):
    pin = pp[(pp.bookmaker == "pinnacle") & (pp.market_group == "moneyline")].drop_duplicates(["fixture_id", "side"], keep="last")
    probs = {}
    for cp in ["open", "t24h", "t12h", "t6h", "t1h", "close"]:
        w = pin.pivot(index="fixture_id", columns="side", values=f"{cp}_price")
        probs[cp] = (1 / w.p1) / (1 / w.p1 + 1 / w.p2)
    P = pd.DataFrame(probs).reset_index().merge(oc[["fixture_id", "y"]], on="fixture_id").merge(fx[["fixture_id", "family"]], on="fixture_id")

    def ll(p, y):
        p = p.clip(1e-4, 1 - 1e-4)
        return -(y * np.log(p) + (1 - y) * np.log(1 - p))

    out = {}
    for cp in ["open", "t24h", "t12h", "t6h", "t1h"]:
        sub = P[P[cp].notna() & P.close.notna()]
        d = (ll(sub[cp], sub.y) - ll(sub.close, sub.y)).to_numpy()
        bs = boot(d, sub.fixture_id.to_numpy())
        out[f"{cp}_vs_close"] = {"n": len(sub), f"ll_{cp}": round(float(ll(sub[cp], sub.y).mean()), 4),
                                 "ll_close": round(float(ll(sub.close, sub.y).mean()), 4),
                                 "diff_mean": bs.get("mean"), "diff_lo": bs.get("lo"), "diff_hi": bs.get("hi"),
                                 "mean_abs_move_pp": round(float((sub[cp] - sub.close).abs().mean() * 100), 2)}
        for fam, g in sub.groupby("family"):
            out[f"{cp}_vs_close"][f"{fam}_diff"] = round(float((ll(g[cp], g.y) - ll(g.close, g.y)).mean()), 4)
    return out


def main():
    fx, pp, oc = load()
    res_ml = oc[["fixture_id", "y"]]
    games = game_results(oc)
    results = {"meta": {"fixtures_ok_pre_seal": int(len(fx)), "fixtures_with_ml_result": int(len(res_ml)),
                        "fixtures_with_game_scores": int(len(games)),
                        "price_point_months": sorted(Path(f).stem for f in glob.glob(str(REPO / "market_history/price_points/*.csv"))),
                        "bootstrap": f"{B} resamples by fixture", "seal": str(SEAL)}}
    ml, ml_base, _ = book_vs_pinnacle(pp, fx, res_ml, "moneyline", "p1", "p2", ml_outcome)
    results["test1_moneyline"] = ml
    results["test1_baseline_all_sides"] = ml_base
    tot, tot_base, _ = book_vs_pinnacle(pp, fx, games, "total_games", "Over", "Under", tot_outcome)
    results["test2_total_games"] = tot
    results["test2_total_baseline"] = tot_base
    spr, spr_base, _ = book_vs_pinnacle(pp, fx, games, "game_spread", "p1", "p2", spr_outcome)
    results["test2_game_spread"] = spr
    results["test2_spread_baseline"] = spr_base
    results["test3_kalshi"] = kalshi(pp, fx)
    results["test4_pinnacle_time"] = pinnacle_time(pp, fx, oc)
    (HERE / "results.json").write_text(json.dumps(results, indent=1, default=str))
    print("wrote", HERE / "results.json")


if __name__ == "__main__":
    main()
