"""In-play exploration: Kalshi's live price against a score-based win probability (research).

Usage:  python research_tests/inplay_score/explore_inplay.py LIVE_DIR OUT_JSON [RESULTS_JSON]

LIVE_DIR      the server's live-score logs (market_history/kalshi/live_scores/*.csv.gz)
RESULTS_JSON  optional cache {ticker: result}; fetched from Kalshi's public API when missing

Exploration on data before 2026-11-03 (allowed by the forward-test amendment); anything found
becomes a registered forward test, not a decision.

Model: each player's chance of winning a point on serve is constant through the match;
pa + pb is the tour average (ATP 1.26, WTA 1.12: about 63/37 and 56/44 serve/return), and
pa - pb is set so the model's pre-match chance equals Kalshi's mid at the first live poll.
The live chance then follows exactly from the score (sets, games, points, server, tiebreaks;
best of 3; a final-set tiebreak at 6-6). Compared with Kalshi's mid at every poll:
  1. calibration: log loss of mid vs model vs a blend, on outcomes (resampling matches);
  2. breaks of serve: the gap mid - model right after a break, and whether the mid moves
     toward the model over the next 5 and 10 minutes (reversion) or away (momentum);
  3. money: buying the side the model favours by >= X points at the ask, taker fee, held to
     the end, one entry per match at the first such moment.
"""
from __future__ import annotations

import json
import sys
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research_kit.core import boot_mean, log_loss  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))
from scripts_shim import read_log  # noqa: E402

SEED = 20261103
SUM = {"KXATPMATCH": 1.26, "KXATPCHALLENGERMATCH": 1.26, "KXWTAMATCH": 1.12}
PTS = {0: 0, 15: 1, 30: 2, 40: 3}


# ---------------------------------------------------------------- exact live win probability
@lru_cache(maxsize=None)
def p_game(p: float, a: int, b: int) -> float:
    """Server wins the game from points a-b (a = server's points; 3-3 = deuce)."""
    if a >= 4 and a - b >= 2:
        return 1.0
    if b >= 4 and b - a >= 2:
        return 0.0
    if a >= 3 and b >= 3:
        d = p * p / (p * p + (1 - p) ** 2)
        return d if a == b else (p + (1 - p) * d if a > b else p * d)
    return p * p_game(p, a + 1, b) + (1 - p) * p_game(p, a, b + 1)


@lru_cache(maxsize=None)
def p_tb(pa: float, pb: float, a: int, b: int, a_serves_next: bool) -> float:
    """A wins the tiebreak from a-b; serve changes after the first point, then every two."""
    if a >= 7 and a - b >= 2:
        return 1.0
    if b >= 7 and b - a >= 2:
        return 0.0
    if a >= 6 and b >= 6 and a == b:
        w, l = pa * (1 - pb), (1 - pa) * pb
        return w / (w + l)
    n = a + b
    p = pa if a_serves_next else 1 - pb
    nxt = (not a_serves_next) if n % 2 == 0 else a_serves_next
    return p * p_tb(pa, pb, a + 1, b, nxt) + (1 - p) * p_tb(pa, pb, a, b + 1, nxt)


@lru_cache(maxsize=None)
def p_set(pa: float, pb: float, ga: int, gb: int, a_serves: bool) -> float:
    """A wins the set from games ga-gb with A serving the next game (game start)."""
    if (ga >= 6 and ga - gb >= 2) or ga == 7:
        return 1.0
    if (gb >= 6 and gb - ga >= 2) or gb == 7:
        return 0.0
    if ga == 6 and gb == 6:
        return p_tb(pa, pb, 0, 0, a_serves)
    h = p_game(pa, 0, 0) if a_serves else 1 - p_game(pb, 0, 0)
    return h * p_set(pa, pb, ga + 1, gb, not a_serves) + (1 - h) * p_set(pa, pb, ga, gb + 1, not a_serves)


@lru_cache(maxsize=None)
def p_match_sets(pa: float, pb: float, sa: int, sb: int, a_serves: bool) -> float:
    """A wins a best-of-3 match from sets sa-sb at a set start with A serving first."""
    if sa == 2:
        return 1.0
    if sb == 2:
        return 0.0
    # who serves first next set depends on the games played; approximate with alternation by
    # averaging both (the effect is tiny), exact enough for comparison with a 1-cent price grid
    w = p_set(pa, pb, 0, 0, a_serves)
    nxt = 0.5 * (p_match_sets(pa, pb, sa + 1, sb, True) + p_match_sets(pa, pb, sa + 1, sb, False))
    nxt_l = 0.5 * (p_match_sets(pa, pb, sa, sb + 1, True) + p_match_sets(pa, pb, sa, sb + 1, False))
    return w * nxt + (1 - w) * nxt_l


def p_live(pa, pb, sa, sb, ga, gb, pts_a, pts_b, a_serves) -> float:
    """A wins the match from the full state (inside a game or a tiebreak)."""
    if ga == 6 and gb == 6:
        win_set = p_tb(pa, pb, pts_a, pts_b, a_serves)
    else:
        if a_serves:
            hold = p_game(pa, pts_a, pts_b)
        else:
            hold = 1 - p_game(pb, pts_b, pts_a)
        win_set = hold * p_set(pa, pb, ga + 1, gb, not a_serves) + (1 - hold) * p_set(pa, pb, ga, gb + 1, not a_serves)
    nxt = 0.5 * (p_match_sets(pa, pb, sa + 1, sb, True) + p_match_sets(pa, pb, sa + 1, sb, False))
    nxt_l = 0.5 * (p_match_sets(pa, pb, sa, sb + 1, True) + p_match_sets(pa, pb, sa, sb + 1, False))
    return win_set * nxt + (1 - win_set) * nxt_l


def fit_serve(p0: float, total: float) -> tuple[float, float]:
    """pa, pb with pa + pb = total and a pre-match chance p0 (A serving first, averaged)."""
    lo, hi = -0.4, 0.4
    for _ in range(40):
        d = (lo + hi) / 2
        pa, pb = round((total + d) / 2, 4), round((total - d) / 2, 4)
        v = 0.5 * (p_match_sets(pa, pb, 0, 0, True) + p_match_sets(pa, pb, 0, 0, False))
        lo, hi = (d, hi) if v < p0 else (lo, d)
    d = (lo + hi) / 2
    return round((total + d) / 2, 4), round((total - d) / 2, 4)


# ---------------------------------------------------------------- data
def parse_points(v):
    try:
        v = int(float(v))
    except (TypeError, ValueError):
        return None
    return v


def load(live_dir: Path) -> pd.DataFrame:
    frames = []
    for p in sorted(live_dir.glob("*.csv*")):
        d = read_log(p)
        if "points_1" not in d:                       # 2026-10-31 layout: games_1 held the point score
            d["points_1"], d["points_2"] = d["games_1"], d["games_2"]
            d["games_1"] = d["round_scores_1"].map(lambda s: json.loads(s)[-1] if s and s != "[]" else 0)
            d["games_2"] = d["round_scores_2"].map(lambda s: json.loads(s)[-1] if s and s != "[]" else 0)
        frames.append(d)
    df = pd.concat(frames, ignore_index=True)
    df["t"] = pd.to_datetime(df["polled_utc"], utc=True, errors="coerce")
    for c in ("bid_1", "ask_1", "bid_2", "ask_2", "sets_1", "sets_2", "games_1", "games_2"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df[(df["status"].astype(str).str.lower() == "live") & df["bid_1"].notna() & df["ask_1"].notna()]
    df = df[(df["ask_1"] > df["bid_1"]) & (df["ask_1"] - df["bid_1"] <= 0.10)]
    return df.sort_values(["event_ticker", "t"]).reset_index(drop=True)


def results(df: pd.DataFrame, cache_path: Path | None) -> dict:
    cache = json.loads(cache_path.read_text()) if cache_path and cache_path.exists() else {}
    s = requests.Session()
    for t in df["ticker_1"].dropna().unique():
        if cache.get(t) in ("yes", "no"):
            continue
        try:
            cache[t] = (s.get(f"https://api.elections.kalshi.com/trade-api/v2/markets/{t}", timeout=30).json().get("market") or {}).get("result")
        except (requests.RequestException, ValueError):
            pass
    if cache_path:
        cache_path.write_text(json.dumps(cache))
    return cache


def model_column(df: pd.DataFrame) -> pd.DataFrame:
    out = []
    for ev, g in df.groupby("event_ticker"):
        g = g.copy()
        p0 = float((g["bid_1"].iloc[0] + g["ask_1"].iloc[0]) / 2)
        first = g.iloc[0]
        if not (0.03 < p0 < 0.97) or int(first["sets_1"] or 0) + int(first["sets_2"] or 0) > 0 or \
                int(first["games_1"] or 0) + int(first["games_2"] or 0) > 2:
            continue                                        # need the price at (about) the start
        pa, pb = fit_serve(p0, SUM.get(first["series"], 1.26))
        vals = []
        for r in g.itertuples():
            pt_a, pt_b = parse_points(r.points_1), parse_points(r.points_2)
            if None in (pt_a, pt_b) or pd.isna(r.games_1) or pd.isna(r.sets_1) or not isinstance(r.server, str):
                vals.append(np.nan)
                continue
            ga, gb, sa, sb = int(r.games_1), int(r.games_2), int(r.sets_1), int(r.sets_2)
            if sa >= 2 or sb >= 2 or ga > 7 or gb > 7:
                vals.append(np.nan)
                continue
            if not (ga == 6 and gb == 6):
                pt_a, pt_b = PTS.get(pt_a), PTS.get(pt_b)
                if pt_a is None or pt_b is None:            # "A"/advantage shown separately
                    vals.append(np.nan)
                    continue
                if str(r.advantage) == str(r.competitor_1):
                    pt_a, pt_b = 4, 3
                elif str(r.advantage) == str(r.competitor_2):
                    pt_a, pt_b = 3, 4
            a_serves = r.server == r.competitor_1
            sp_a, sp_b = (pt_a, pt_b) if a_serves else (pt_a, pt_b)
            vals.append(p_live(pa, pb, sa, sb, ga, gb, sp_a, sp_b, a_serves) if a_serves
                        else p_live(pa, pb, sa, sb, ga, gb, sp_a, sp_b, a_serves))
        g["model"] = vals
        g["pa"], g["pb"], g["p0"] = pa, pb, p0
        out.append(g)
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def main() -> int:
    live_dir, out_json = Path(sys.argv[1]), Path(sys.argv[2])
    cache = Path(sys.argv[3]) if len(sys.argv) > 3 else None
    df = load(live_dir)
    res_map = results(df, cache)
    df = model_column(df)
    df["mid"] = (df["bid_1"] + df["ask_1"]) / 2
    df["y"] = df["ticker_1"].map(lambda t: {"yes": 1, "no": 0}.get(res_map.get(t)))
    d = df[df["model"].notna() & df["y"].notna()].copy()
    out = {"matches": int(d["event_ticker"].nunique()), "rows": int(len(d)),
           "median_spread_cents": round(100 * float((d["ask_1"] - d["bid_1"]).median()), 2)}
    # 1. calibration, one value per match (mean over the match's rows), resampled by match
    per = d.assign(ll_mid=log_loss(d["y"], d["mid"]), ll_model=log_loss(d["y"], d["model"]),
                   ll_blend=log_loss(d["y"], 0.5 * d["mid"] + 0.5 * d["model"])).groupby("event_ticker")[["ll_mid", "ll_model", "ll_blend"]].mean()
    out["log loss, mean of per-match means"] = {k: round(float(per[k].mean()), 4) for k in per}
    out["model minus mid (per match)"] = [round(v, 4) for v in boot_mean((per["ll_model"] - per["ll_mid"]).to_numpy(), seed=SEED)]
    out["blend minus mid (per match)"] = [round(v, 4) for v in boot_mean((per["ll_blend"] - per["ll_mid"]).to_numpy(), seed=SEED)]
    # 2. breaks: the poll where the receiver's games went up at a game change
    d["gap"] = d["mid"] - d["model"]
    rows = []
    for ev, g in d.groupby("event_ticker"):
        g = g.reset_index(drop=True)
        for i in range(1, len(g)):
            a, b = g.loc[i - 1], g.loc[i]
            if (b["sets_1"], b["sets_2"]) != (a["sets_1"], a["sets_2"]):
                continue
            dg1, dg2 = b["games_1"] - a["games_1"], b["games_2"] - a["games_2"]
            if dg1 + dg2 != 1 or not isinstance(a["server"], str):
                continue
            receiver_won = (dg1 == 1 and a["server"] != a["competitor_1"]) or (dg2 == 1 and a["server"] == a["competitor_1"])
            if not receiver_won:
                continue
            breaker_is_a = dg1 == 1
            fut = {}
            for m in (1, 2, 5, 10):
                later = g[g["t"] >= b["t"] + pd.Timedelta(minutes=m)]
                fut[m] = None if later.empty else later.iloc[0]
            sign = 1 if breaker_is_a else -1
            rows.append({"event": ev, "gap_after": sign * b["gap"], "move_mid": sign * (b["mid"] - a["mid"]),
                         "move_model": sign * (b["model"] - a["model"]),
                         **{f"rev{m}": (None if fut[m] is None else -sign * (fut[m]["mid"] - b["mid"])) for m in (5, 10)},
                         **{f"model_rev{m}": (None if fut[m] is None else -sign * (fut[m]["model"] - b["model"])) for m in (5, 10)},
                         **{f"mid_breaker_{m}": (None if fut[m] is None else (fut[m]["mid"] if breaker_is_a else 1 - fut[m]["mid"])) for m in (1, 2, 5)},
                         **{f"ask_breaker_{m}": (None if fut[m] is None else (fut[m]["ask_1"] if breaker_is_a else 1 - fut[m]["bid_1"])) for m in (1, 2, 5)},
                         "breaker_won": int(d.loc[d["event_ticker"] == ev, "y"].iloc[0] == (1 if breaker_is_a else 0)),
                         "mid_breaker": b["mid"] if breaker_is_a else 1 - b["mid"], "model_breaker": b["model"] if breaker_is_a else 1 - b["model"]})
    br = pd.DataFrame(rows)
    if len(br):
        r = lambda x: [round(100 * v, 2) for v in boot_mean(pd.Series(x).dropna().to_numpy(), seed=SEED)]  # noqa: E731
        out["breaks"] = {"n": int(len(br)), "matches": int(br["event"].nunique()),
                         "mid moved toward breaker (pts)": r(br["move_mid"]), "model moved toward breaker (pts)": r(br["move_model"]),
                         "mid minus model right after, breaker's side (pts)": r(br["gap_after"]),
                         "mid reverts over next 5 min (pts, + = back toward the victim)": r(br["rev5"]),
                         "mid reverts over next 10 min": r(br["rev10"]),
                         "model reverts over next 10 min (score moves)": r(br["model_rev10"]),
                         "breaker won minus mid right after (pts)": r(br["breaker_won"] - br["mid_breaker"]),
                         "breaker won minus model right after (pts)": r(br["breaker_won"] - br["model_breaker"]),
                         **{f"breaker won minus mid {m} min later (pts)": r(br["breaker_won"] - br[f"mid_breaker_{m}"]) for m in (1, 2, 5)}}
        # money: back the breaker at the ask m minutes after the break, hold, taker fee (all breaks; one match has several)
        for m in (1, 2, 5):
            x = br.dropna(subset=[f"ask_breaker_{m}"])
            p = x[f"ask_breaker_{m}"].to_numpy()
            pnl = np.where(x["breaker_won"] == 1, 1 - p, -p) - 0.07 * p * (1 - p)
            codes, uniq = pd.factorize(x["event"])
            g = np.random.default_rng(SEED)
            s_, n_ = np.bincount(codes, weights=pnl), np.bincount(codes).astype(float)
            draws = [s_[i].sum() / n_[i].sum() for i in (g.integers(0, len(uniq), len(uniq)) for _ in range(2000))]
            out["breaks"][f"back the breaker at the ask {m} min later, hold, after fee (cents; resampled by match)"] = \
                [round(100 * pnl.mean(), 2)] + [round(100 * v, 2) for v in np.percentile(draws, [2.5, 97.5])] + [int(len(x))]
    # 3. money: first moment per match where the model differs from the executable price by >= X
    money = {}
    for x in (0.05, 0.10):
        pnl = []
        for ev, g in d.groupby("event_ticker"):
            buy_a = g[g["model"] - g["ask_1"] >= x]
            buy_b = g[(1 - g["model"]) - (1 - g["bid_1"]) >= x]
            cands = []
            if len(buy_a):
                r0 = buy_a.iloc[0]
                cands.append((r0["t"], r0["ask_1"], r0["y"]))
            if len(buy_b):
                r0 = buy_b.iloc[0]
                cands.append((r0["t"], 1 - r0["bid_1"], 1 - r0["y"]))
            if not cands:
                continue
            _, price, won = min(cands, key=lambda c: c[0])
            pnl.append((1 - price if won else -price) - 0.07 * price * (1 - price))
        if pnl:
            money[f"model edge >= {int(100 * x)} pts, first entry per match, hold, after taker fee (cents)"] = \
                [round(100 * v, 2) for v in boot_mean(np.array(pnl), seed=SEED)] + [len(pnl)]
    out["money"] = money
    out_json.write_text(json.dumps(out, indent=1, default=str) + "\n")
    print(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
