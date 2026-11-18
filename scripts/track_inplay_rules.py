"""Forward tests of registration 2026-11-18 (docs/registrations/2026-11-18-inplay-rules.md): three in-play
rules on Kalshi tennis, scored from the server's live score-and-price log.

Usage:  python scripts/track_inplay_rules.py [--registered 2026-11-19T00:00:00Z]

Paper only: no account, no key, no orders. Reads market_history/kalshi/live_scores/*.csv* (score and both
players' best bid / ask every 10 s), each event's best-of and tournament from Kalshi's public milestones,
settles with Kalshi's market results, and rewrites market_history/kalshi/registrations/
inplay_<rule>_2026-11-18.csv and _summary.json for each rule.

Fair price: research_kit.inplay (point-level model). Serve probabilities are solved from the last quote
before the match starts, at a fixed serve level per tour (ATP 0.64, Challenger 0.62, WTA 0.56; no
surface is inferred). Best of 3 or 5 from the milestone; deciding set to a 10-point tie-break at the
Grand Slams, 7 elsewhere.

Rules (decisions only at the first row of a game, points 0-0; one decision per match per rule):
  fade        ATP, WTA, Challenger match winners. A player's de-vigged mid is 70-90c and at least 3 points
              above the fair price: buy the other player.
  serve_out   WTA match winners (ATP and Challenger reported, not scored): a player starts a game serving
              for the match: buy the receiver.
  breaker     WTA match winners (ATP and Challenger reported, not scored): the game after a failed
              serve-out (the server serving for the set or match was broken): buy the breaker.
Buying a player: the cheaper of YES on them (ask) and NO on the opponent (1 - opponent's bid), plus the
Kalshi taker fee rounded up to the cent on 100 contracts; 100 contracts.
Metric: P&L per contract at settlement (the backed player's market: yes / no; anything else void).
Reported: the backed player's mid when the set ends, the fair price at the decision.
Pass: 95% range of P&L per contract (2,000 resamples, seed 20261118) wholly above zero, at least 300 bets
(fade: ends 2027-06-30; serve_out and breaker, WTA: end 2027-12-31).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import requests

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from research_kit import inplay as ip  # noqa: E402
from scripts.log_kalshi_live import read_log  # noqa: E402
from scripts.track_longshot_rule import API, taker_fee_per_contract  # noqa: E402

LIVE = BASE / "market_history" / "kalshi" / "live_scores"
OUT = BASE / "market_history" / "kalshi" / "registrations"
REGISTERED_DEFAULT = "2026-11-19T00:00:00Z"
TOUR = {"KXATPMATCH": "ATP", "KXWTAMATCH": "WTA", "KXATPCHALLENGERMATCH": "CH"}
LEVEL = {"ATP": 0.64, "CH": 0.62, "WTA": 0.56}
SLAMS = ("australian open", "roland garros", "french open", "wimbledon", "us open")
PTS = {0: 0, 15: 1, 30: 2, 40: 3, 50: 4}
FADE_LO, FADE_HI, FADE_GAP = 0.70, 0.90, 0.03
RULES = {"fade": ("ATP", "WTA", "CH"), "serve_out": ("WTA",), "breaker": ("WTA",)}
MIN_BETS, SEED = 300, 20261118
WINDOW_END = {"fade": "2027-06-30", "serve_out": "2027-12-31", "breaker": "2027-12-31"}
IN_PLAY = ("1st_set", "2nd_set", "3rd_set", "4th_set", "5th_set")


def _num(v):
    try:
        f = float(v)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def quotes_ok(r) -> bool:
    v = [_num(getattr(r, c)) for c in ("bid_1", "ask_1", "bid_2", "ask_2")]
    return all(x is not None for x in v) and 0 < v[0] < v[1] < 1 and 0 < v[2] < v[3] < 1


def mid(r, s: int) -> float:
    return (float(getattr(r, f"bid_{s}")) + float(getattr(r, f"ask_{s}"))) / 2


def p1_devig(r) -> float:
    a, b = mid(r, 1), mid(r, 2)
    return a / (a + b)


def state(r, c1: str):
    """(sets_1, sets_2, games_1, games_2, points_1, points_2, c1_serves) or None."""
    vals = [_num(getattr(r, c)) for c in ("sets_1", "sets_2", "games_1", "games_2", "points_1", "points_2")]
    if any(v is None for v in vals) or not isinstance(r.server, str) or not r.server:
        return None
    s1, s2, g1, g2, p1, p2 = (int(v) for v in vals)
    if not (g1 == 6 and g2 == 6):
        if p1 not in PTS or p2 not in PTS:
            return None
        p1, p2 = PTS[p1], PTS[p2]
    return s1, s2, g1, g2, p1, p2, r.server == c1


def serving_for(s: int, r: int) -> bool:
    return (s == 5 and r <= 4) or (s == 6 and r == 5)


def buy(r, side: int) -> tuple[float, float, str]:
    """Price, fee and route for backing competitor `side` (1 or 2) at this row."""
    o = 3 - side
    yes, no = float(getattr(r, f"ask_{side}")), 1 - float(getattr(r, f"bid_{o}"))
    price, how = (yes, "YES") if yes <= no else (no, "NO on opponent")
    return round(price, 4), taker_fee_per_contract(price), how


def event_decisions(ev: str, m: pd.DataFrame, meta: dict, registered: pd.Timestamp) -> list[dict]:
    series = str(m["series"].iloc[0])
    tour = TOUR.get(series)
    if tour is None:
        return []
    m = m.sort_values("t")
    c1 = m["competitor_1"].dropna()
    if c1.empty:
        return []
    c1 = str(c1.iloc[0])
    live = m[m["match_status"].isin(IN_PLAY)]
    if live.empty or live["t"].iloc[0] <= registered:
        return []
    pre = [r for r in m[m["t"] < live["t"].iloc[0]].itertuples() if quotes_ok(r)]
    if not pre:
        return []
    bo = int(meta.get("best_of") or 3)
    stw = (bo + 1) // 2
    ftb = 10 if any(s in str(meta.get("tournament_name", "")).lower() for s in SLAMS) else 7
    p0 = p1_devig(pre[-1])
    try:
        pa, pb = ip.solve_serve(p0, LEVEL[tour], best_of=bo, final_set_tb=ftb)
    except ValueError:
        return []
    out, done, prev = [], set(), None
    rows = list(live.itertuples())
    for i, r in enumerate(rows):
        st = state(r, c1)
        if st is None:
            continue
        s1, s2, g1, g2, p1, p2, c1_srv = st
        new_game = prev is None or (s1, s2, g1, g2) != prev[:4]
        last = prev
        prev = st
        if not new_game or (p1, p2) != (0, 0) or not quotes_ok(r):
            continue
        fair1 = ip.p_match(pa, pb, (s1, s2), (g1, g2), (0, 0), c1_srv, bo, ftb)
        mk1 = p1_devig(r)
        srv = 1 if c1_srv else 2
        s_games, r_games = (g1, g2) if srv == 1 else (g2, g1)
        s_sets = s1 if srv == 1 else s2
        cands = []
        if "fade" not in done:
            for x in (1, 2):
                mx, fx = (mk1, fair1) if x == 1 else (1 - mk1, 1 - fair1)
                if FADE_LO <= mx <= FADE_HI and mx - fx >= FADE_GAP:
                    cands.append(("fade", 3 - x))
                    break
        if serving_for(s_games, r_games) and s_sets == stw - 1:
            cands.append(("serve_out", 3 - srv))
        if last is not None and last[0:2] == (s1, s2):
            ls1, ls2, lg1, lg2, _, _, l_c1 = last
            lsrv = 1 if l_c1 else 2
            ls, lr = (lg1, lg2) if lsrv == 1 else (lg2, lg1)
            ns, nr = (g1, g2) if lsrv == 1 else (g2, g1)
            if serving_for(ls, lr) and ns == ls and nr == lr + 1:
                cands.append(("breaker", 3 - lsrv))
        for rule, side in cands:
            if rule in done:
                continue
            done.add(rule)
            price, fee, how = buy(r, side)
            set_end = next((q for q in rows[i + 1:] if state(q, c1) is not None and state(q, c1)[0:2] != (s1, s2) and quotes_ok(q)), None)
            p_side = (lambda q: p1_devig(q) if side == 1 else 1 - p1_devig(q))
            out.append({"rule": rule, "event_ticker": ev, "series": series, "tour": tour, "decided_utc": r.t.isoformat(),
                        "score": f"sets {s1}-{s2} games {g1}-{g2}", "backed": side,
                        "backed_ticker": getattr(r, f"ticker_{side}"), "how": how, "price": price, "fee_per_contract": fee,
                        "mid_backed": round(p_side(r), 4), "fair_backed": round(fair1 if side == 1 else 1 - fair1, 4),
                        "mid_backed_at_set_end": None if set_end is None else round(p_side(set_end), 4),
                        "scored": tour in RULES[rule]})
    return out


def milestone_meta(events, cache_path: Path, get) -> dict:
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    for ev in events:
        if ev in cache:
            continue
        try:
            ms = get("/milestones", {"related_event_ticker": ev, "limit": 5}).get("milestones", [])
            ms = [x for x in ms if ev in (x.get("primary_event_tickers") or [])] or ms
            det = (ms[0].get("details") or {}) if ms else {}
            cache[ev] = {"best_of": det.get("best_of"), "tournament_name": det.get("tournament_name")}
        except (requests.RequestException, ValueError, KeyError):
            continue
    cache_path.write_text(json.dumps(cache, indent=0, sort_keys=True))
    return cache


def settle(d: pd.DataFrame, prior: pd.DataFrame, get) -> pd.DataFrame:
    known = dict(zip(prior["backed_ticker"], prior["result"])) if len(prior) and "result" in prior else {}
    res = []
    for t in d["backed_ticker"]:
        r = known.get(t)
        if r not in ("yes", "no"):
            try:
                r = (get(f"/markets/{t}").get("market") or {}).get("result") or ""
            except (requests.RequestException, RuntimeError, ValueError):
                r = ""
        res.append(r)
    d = d.assign(result=res)
    ok = d["result"].isin(["yes", "no"])
    d["pnl_per_contract"] = np.where(ok, np.where(d["result"] == "yes", 1 - d["price"], -d["price"]) - d["fee_per_contract"], np.nan)
    return d


def summary(rule: str, d: pd.DataFrame) -> dict:
    s = d[d["scored"].astype(bool) & d["pnl_per_contract"].notna()] if len(d) else d
    out = {"registration": "docs/registrations/2026-11-18-inplay-rules.md", "rule": rule, "decisions": int(len(d)),
           "settled": int(len(s)), "min_matches": MIN_BETS, "window_end": WINDOW_END[rule], "status": "running"}
    if len(s):
        x = s["pnl_per_contract"].to_numpy(float)
        g = np.random.default_rng(SEED)
        lo, hi = np.percentile([x[g.integers(0, len(x), len(x))].mean() for _ in range(2000)], [2.5, 97.5])
        out.update({"cents_per_contract": round(100 * float(x.mean()), 3), "range_cents": [round(100 * lo, 3), round(100 * hi, 3)],
                    "status": ("PASS" if lo > 0 else "FAIL") if len(s) >= MIN_BETS else "running"})
    other = d[~d["scored"].astype(bool) & d["pnl_per_contract"].notna()] if len(d) else d
    if len(other):
        out["reported, not scored"] = {t: {"n": int(len(g)), "cents_per_contract": round(100 * float(g["pnl_per_contract"].mean()), 3)}
                                      for t, g in other.groupby("tour")}
    out["note"] = f"{len(s)} scored" + (f"; other tours {len(other)}" if len(other) else "")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--registered", default=REGISTERED_DEFAULT)
    args = ap.parse_args()
    registered = pd.Timestamp(args.registered)
    OUT.mkdir(parents=True, exist_ok=True)
    frames = []
    for p in sorted(LIVE.glob("*.csv*")):
        try:
            frames.append(read_log(p))
        except (OSError, ValueError):
            continue
    rows = []
    if frames:
        d = pd.concat(frames, ignore_index=True)
        d = d[d["series"].isin(list(TOUR))].copy()
        d["t"] = pd.to_datetime(d["polled_utc"], utc=True, errors="coerce")
        d = d.dropna(subset=["t"])
        if "competitor_1" in d:
            d["server"] = d["server"].astype(object).where(d["server"].notna(), None)
            sess = requests.Session()
            get = lambda p, params=None: sess.get(API + p, params=params, timeout=30).json()  # noqa: E731
            evs = sorted(d["event_ticker"].unique())
            meta = milestone_meta(evs, OUT / "inplay_2026-11-18_milestones.json", get)
            for ev, m in d.groupby("event_ticker"):
                rows += event_decisions(ev, m, meta.get(ev, {}), registered)
    else:
        get = None
    allr = pd.DataFrame(rows)
    for rule in RULES:
        path = OUT / f"inplay_{rule}_2026-11-18.csv"
        prior = pd.read_csv(path) if path.exists() else pd.DataFrame()
        d = allr[allr["rule"] == rule].reset_index(drop=True) if len(allr) else pd.DataFrame()
        if len(d):
            d = settle(d, prior, get)
            d.to_csv(path, index=False)
        s = summary(rule, d)
        (OUT / f"inplay_{rule}_2026-11-18_summary.json").write_text(json.dumps(s, indent=1, default=str) + "\n")
        print(json.dumps(s, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
