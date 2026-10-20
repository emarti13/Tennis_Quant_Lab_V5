"""Total games and game spreads: does a serve/return point model with court pace beat the books?
(research, the spreads/totals work the user asked for)

Usage:  python scripts/measure_totals_spreads.py [--matches-cache PATH] [--out docs/experiments/data/totals_spreads.json]

Court pace changes how many games are played far more than who wins
(docs/experiments/2026-10-20-court-pace.md). Here the point model of scripts/measure_court_pace.py
(serve/return skill, court pace, same visibility rules as the Elo) gives each match a full
distribution of total games and of the game margin (games, tiebreak sets, best of 3 or 5),
so it can price any book's line, not just Pinnacle's.

Against the price store (2026, before the sealed period; one Pinnacle main line per fixture):
1) log loss on over/under and on the spread cover: the model alone, Pinnacle's open, its
   close, and the model on top of the open (logistic, fit January-June, test July to
   October 12); integer lines that land exactly are pushes and dropped;
2) the open-to-close move toward the model's side;
3) execution books (BetRivers, DraftKings, Bet365) at their own lines and closing prices:
   the model-on-open probability against their price; return per dollar of the bets it
   picks (edge above 2% and 5%), actual results.
Matches with a retirement or walkover are void for totals and spreads, as at most books.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
import v5_baseline_elo as be  # noqa: E402
import scripts.measure_court_pace as cp  # noqa: E402
import scripts.measure_open_close_edge as oc  # noqa: E402
from scripts.measure_baseline_elo import loss, paired  # noqa: E402

SEALED_FROM = pd.Timestamp("2026-10-13", tz="UTC")
TEST_FROM = pd.Timestamp("2026-07-01", tz="UTC")
EXEC_BOOKS = ("betrivers", "draftkings", "bet365")
EDGES = (0.02, 0.05)
GRID = 0.005


# ------------------------------------------------------------------ distributions
def _q(p):
    return round(round(min(max(p, 0.40), 0.92) / GRID) * GRID, 4)


@lru_cache(maxsize=None)
def set_outcomes(pa: float, pb: float, a_first: bool) -> tuple:
    """((games_a, games_b, prob), ...) for one set; a tiebreak at 6-6 counts as one game."""
    ha, hb = cp.hold(pa), cp.hold(pb)
    tb = 0.5 * (cp._tiebreak(pa, pb) + 1 - cp._tiebreak(pb, pa))
    mass = {(0, 0): 1.0}
    out = []
    for _ in range(13):
        nxt = {}
        for (a, b), pr in mass.items():
            if a == 6 and b == 6:
                out += [(7, 6, pr * tb), (6, 7, pr * (1 - tb))]
                continue
            a_serving = ((a + b) % 2 == 0) == a_first
            p_a = ha if a_serving else 1 - hb
            for (na, nb), q in (((a + 1, b), p_a), ((a, b + 1), 1 - p_a)):
                if (na >= 6 and na - nb >= 2) or (nb >= 6 and nb - na >= 2):
                    out.append((na, nb, pr * q))
                else:
                    nxt[(na, nb)] = nxt.get((na, nb), 0.0) + pr * q
        mass = nxt
        if not mass:
            break
    return tuple(out)


@lru_cache(maxsize=None)
def match_dist(pa: float, pb: float, best_of: int) -> dict:
    """{(games_a - games_b, total games): prob}, the first server of each set a coin flip."""
    sets = [(ga, gb, 0.5 * pr) for first in (True, False) for ga, gb, pr in set_outcomes(pa, pb, first)]
    need = 3 if best_of == 5 else 2
    states = {(0, 0, 0, 0): 1.0}                    # (sets a, sets b, margin, total)
    done: dict = {}
    while states:
        nxt = {}
        for (sa, sb, mg, tot), pr in states.items():
            for ga, gb, q in sets:
                key = (sa + (ga > gb), sb + (gb > ga), mg + ga - gb, tot + ga + gb)
                if key[0] == need or key[1] == need:
                    done[(key[2], key[3])] = done.get((key[2], key[3]), 0.0) + pr * q
                else:
                    nxt[key] = nxt.get(key, 0.0) + pr * q
        states = nxt
    return done


def p_over(dist: dict, line: float) -> tuple[float, float]:
    """(P(total > line), P(total == line)) ."""
    over = sum(p for (m, t), p in dist.items() if t > line)
    push = sum(p for (m, t), p in dist.items() if t == line)
    return over, push


def p_cover(dist: dict, line: float) -> tuple[float, float]:
    """P1 covers a line (p1 games + line > p2 games), and the push chance."""
    cover = sum(p for (m, t), p in dist.items() if m + line > 0)
    push = sum(p for (m, t), p in dist.items() if m + line == 0)
    return cover, push


def games_by_player(score) -> tuple[int, int] | None:
    """Winner's and loser's games from a score like '6-4 3-6 7-6(5)'."""
    if not isinstance(score, str):
        return None
    w = l_ = 0
    for a, b in re.findall(r"(\d+)-(\d+)", re.sub(r"\(\d+\)", "", score)):
        w, l_ = w + int(a), l_ + int(b)
    return (w, l_) if w + l_ > 0 else None


# ------------------------------------------------------------------ book lines
def book_lines(base: Path) -> pd.DataFrame:
    """One row per fixture, market and book: line (for p1 on spreads), de-vigged open and
    close chance of over / p1 covering, and the raw close prices of both sides."""
    pts = pd.concat([pd.read_csv(p, dtype={"fixture_id": str}) for p in sorted((base / "market_history" / "price_points").glob("*.csv"))])
    pts = pts[pts["market_group"].isin(["total_games", "game_spread"]) & (pts["close_stale"].astype(str) != "True")]
    rows = []
    for (fid, mg, book), g in pts.groupby(["fixture_id", "market_group", "bookmaker"]):
        sides = ("Over", "Under") if mg == "total_games" else ("p1", "p2")
        a, b = g[g["side"] == sides[0]], g[g["side"] == sides[1]]
        if a.empty or b.empty:
            continue
        a, b = a.iloc[0], b.iloc[0]
        row = {"fixture_id": fid, "market": mg, "book": book, "line": float(a["line"])}
        for when in ("open", "close"):
            x, y = a[f"{when}_price"], b[f"{when}_price"]
            row[f"{when}_a"], row[f"{when}_b"] = x, y
            row[f"{when}_p"] = (1 / x) / (1 / x + 1 / y) if pd.notna(x) and pd.notna(y) and x > 1 and y > 1 else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--matches-cache", default=None)
    ap.add_argument("--out", default="docs/experiments/data/totals_spreads.json")
    args = ap.parse_args()
    rng = np.random.default_rng(20261020)
    m = pd.read_pickle(args.matches_cache) if args.matches_cache and Path(args.matches_cache).exists() else be.load_matches(BASE)
    feats = cp.run(m).set_index("key")
    # fixtures <-> matches: the moneyline join of the open-close measurement (same players, dates)
    j = oc.build(BASE, args.matches_cache)
    j = j[(j["n_min"] >= 18) & (j["start"] < SEALED_FROM)]
    info = m.set_index("key")[["score", "best_of", "retired", "walkover"]]
    j = j.join(feats[["pw0", "pl0", "pace"]], on="key").join(info, on="key").dropna(subset=["pw0"])
    j = j[~j["retired"].astype(bool) & ~j["walkover"].astype(bool)]
    rows = []
    for r in j.itertuples():
        gp = games_by_player(r.score)
        if gp is None:
            continue
        p1_won = r.y == 1
        g1, g2 = (gp if p1_won else gp[::-1])
        s1, s2 = (r.pw0, r.pl0) if p1_won else (r.pl0, r.pw0)   # serve-point chances, fixture p1 first
        s1p, s2p = cp.inv(cp.logit(s1) + r.pace), cp.inv(cp.logit(s2) + r.pace)
        bo = 5 if r.best_of == 5 else 3
        rows.append({"fixture_id": r.fixture_id, "start": r.start, "family": r.family, "games1": g1, "games2": g2,
                     "dist0": match_dist(_q(s1), _q(s2), bo), "dist": match_dist(_q(s1p), _q(s2p), bo), "pace": r.pace})
    fx = pd.DataFrame(rows)
    lines = book_lines(BASE).merge(fx, on="fixture_id")
    out = {"fixtures": int(fx["fixture_id"].nunique())}
    for market in ("total_games", "game_spread"):
        L = lines[lines["market"] == market].copy()
        if market == "total_games":
            L["outcome"] = np.where(L["games1"] + L["games2"] > L["line"], 1.0, np.where(L["games1"] + L["games2"] < L["line"], 0.0, np.nan))
            calc = p_over
        else:
            L["outcome"] = np.where(L["games1"] + L["line"] > L["games2"], 1.0, np.where(L["games1"] + L["line"] < L["games2"], 0.0, np.nan))
            calc = p_cover
        for col, dcol in (("model0", "dist0"), ("model", "dist")):
            pp = [calc(d, ln) for d, ln in zip(L[dcol], L["line"])]
            L[col] = [p / (1 - push) if push < 1 else np.nan for p, push in pp]     # conditional on no push
        L = L.dropna(subset=["outcome", "model", "open_p", "close_p"])
        L["expected_total"] = [sum(p * t for (mg, t), p in d.items()) for d in L["dist"]]
        pin = L[L["book"] == "pinnacle"].copy()
        train, test = pin[pin["start"] < TEST_FROM], pin[pin["start"] >= TEST_FROM].copy()
        y = test["outcome"].to_numpy()
        ll = lambda p: loss(np.where(y == 1, p, 1 - p))  # noqa: E731
        res = {"n_train": int(len(train)), "n_test": int(len(test)),
               "log_loss": {c: round(float(ll(test[c].to_numpy()).mean()), 5) for c in ("open_p", "close_p", "model0", "model")},
               "model_minus_open": paired(ll(test["model"].to_numpy()), ll(test["open_p"].to_numpy()), rng)}
        fits = {}
        for name, cols in (("open+model(no pace)", ["gap0"]), ("open+model", ["gap"]), ("open+model+pace", ["gap", "pace"])):
            for d in (train, test):
                d.loc[:, "gap0"] = oc.logit(d["model0"]) - oc.logit(d["open_p"])
                d.loc[:, "gap"] = oc.logit(d["model"]) - oc.logit(d["open_p"])
            Xtr, mu, sd = oc.design(train, cols)
            Xte, _, _ = oc.design(test, cols, mu, sd)
            w = oc.fit_logistic(np.c_[Xtr, np.ones(len(Xtr))], train["outcome"].to_numpy(float), oc.logit(train["open_p"]))
            p = 1 / (1 + np.exp(-(oc.logit(test["open_p"]) + np.c_[Xte, np.ones(len(Xte))] @ w)))
            shift = p - test["open_p"].to_numpy()
            move = (test["close_p"] - test["open_p"]).to_numpy()
            res[name] = {"log_loss": round(float(ll(p).mean()), 5), "minus_open": paired(ll(p), ll(test["open_p"].to_numpy()), rng),
                         "minus_close": paired(ll(p), ll(test["close_p"].to_numpy()), rng),
                         "move_toward_pick": cp.boot_mean(np.sign(shift) * move, rng),
                         "weights": np.round(w, 4).tolist()}
            fits[name] = (cols, mu, sd, w)
        # execution books: the open+model probability, priced at each book's own line via the model distribution
        cols, mu, sd, w = fits["open+model"]
        pin_open = pin.set_index("fixture_id")[["open_p", "line", "model"]]
        exe = {}
        for book in EXEC_BOOKS:
            B = L[(L["book"] == book) & (L["start"] >= TEST_FROM)].join(pin_open, on="fixture_id", rsuffix="_pin").dropna(subset=["open_p_pin"])
            if B.empty:
                continue
            # Pinnacle's open moved by the fitted model signal, then shifted from Pinnacle's line to this book's line
            g = oc.logit(B["model_pin"]) - oc.logit(B["open_p_pin"])
            z = (g - mu[0]) / sd[0]
            p_pin_line = 1 / (1 + np.exp(-(oc.logit(B["open_p_pin"]) + w[0] * z + w[1])))
            p_book = np.clip(oc.logit(p_pin_line) + oc.logit(B["model"]) - oc.logit(B["model_pin"]), -8, 8)
            p_book = 1 / (1 + np.exp(-p_book))
            res_book = {"n": int(len(B))}
            for e in EDGES:
                ev_a = p_book * B["close_a"] - 1
                ev_b = (1 - p_book) * B["close_b"] - 1
                pick_a, pick_b = ev_a > e, ev_b > e
                ret = np.where(pick_a, np.where(B["outcome"] == 1, B["close_a"] - 1, -1.0),
                               np.where(pick_b, np.where(B["outcome"] == 0, B["close_b"] - 1, -1.0), np.nan))
                ret = ret[~np.isnan(ret)]
                res_book[f"edge_over_{e}"] = cp.boot_mean(ret, rng) if len(ret) else {"n": 0}
            exe[book] = res_book
        res["execution_books_close"] = exe
        res["by_family_model_minus_open"] = {f: paired(ll(test["model"].to_numpy())[test["family"].to_numpy() == f],
                                                       ll(test["open_p"].to_numpy())[test["family"].to_numpy() == f], rng)
                                             for f in ("ATP", "CHALLENGER", "WTA") if (test["family"] == f).sum() > 100}
        if market == "total_games":
            res["mean_line_vs_model_total"] = {"line": round(float(test["line"].mean()), 2),
                                               "model_expected_total": round(float(test["expected_total"].mean()), 2),
                                               "actual_total": round(float((test["games1"] + test["games2"]).mean()), 2),
                                               "corr_model_total_vs_line": round(float(test["expected_total"].corr(test["line"])), 3)}
        out[market] = res
    path = BASE / args.out
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1, default=str) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
