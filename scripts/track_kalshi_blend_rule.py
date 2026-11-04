"""Forward test of registration 2026-11-04 (docs/registrations/2026-11-04-kalshi-blend-at-open.md):
bet the blend's side at the Kalshi opening quote; the price should move toward it by the close.

Usage:  python scripts/track_kalshi_blend_rule.py [--registered 2026-11-04T18:00:00Z] [--results PATH]

Paper only: no account, no key, no orders. Reads the server's 5-minute pre-match quotes and live log,
player names from Kalshi's public market data, match facts from TennisMyLife (history cache built by
bootstrap_v5_history.py into .tql_cache/, plus the current season's v5_results_ready/tennismylife_results.csv
from origin/main), settles with Kalshi's results, and rewrites
market_history/kalshi/registrations/kalshi_blend_2026-11-04.csv and _summary.json.

The inputs are built by the SAME functions the research used (research_tests/scout/run_scout.py,
research_tests/incentives/run_incentives.py, v5_fatigue_features.load_repo_matches), and the weights
are the frozen research_tests/open_clv/kalshi_blend_weights.json.

Facts about a match (entry code, round, ages, ranks) are read from its TennisMyLife row, which appears
after the match is played; only facts public before the match are used, and the price is the logged
opening quote. Matches without a TennisMyLife row are not decided (no bet) until the row appears;
after 14 days without one, they are recorded as "no row" and never bet.

The rule, exactly as registered:
- Series KXATPMATCH, KXWTAMATCH, KXATPCHALLENGERMATCH; scheduled start after the registration time.
- Opening snapshot: the FIRST 5-minute pre-match snapshot in which both markets have a bid and an ask
  and each spread is at most 5 cents, taken at least 60 minutes before the scheduled start and before
  the match first appears in the live log.
- Base: p_A = mid_A / (mid_A + mid_B) at that snapshot. Model: P(A) = sigmoid(w_open * logit(p_A) +
  sum w_i * (x_iA - x_iB)) with the frozen weights.
- Cost of backing a player: the cheaper of YES on them (ask) and NO on the opponent (1 - opponent's bid),
  plus the Kalshi taker fee rounded up to the cent on 100 contracts. Bet the side whose model chance
  minus cost is larger, if it is at least 3 points. 100 contracts.
- Close: the last 5-minute pre-match snapshot before the first live row (or the scheduled start if the
  match never appears live) with both markets bid and ask; p_close of the backed player = mid / (sum of mids).
- PRIMARY metric: CLV per contract = p_close(backed) - price - fee. Pass: the 95% range (2,000 resamples,
  seed 20261103) wholly above zero with at least 300 bets. Ends at 300 bets or 2027-10-31.
- Reported: realised P&L on Kalshi results (backed player's market yes/no; anything else void), the move
  in mid toward the bet, CLV hit rate, by series.
"""
from __future__ import annotations

import argparse
import io
import json
import math
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

BASE = Path(__file__).resolve().parents[1]
for sub in ("", "research_tests/scout", "research_tests/incentives"):
    sys.path.insert(0, str(BASE / sub))
from scripts.track_longshot_rule import API, first_live, load_quotes, taker_fee_per_contract  # noqa: E402
from scripts.track_season_end_rule import norm  # noqa: E402

OUT = BASE / "market_history" / "kalshi" / "registrations"
NAME = "kalshi_blend_2026-11-04"
SERIES = ("KXATPMATCH", "KXWTAMATCH", "KXATPCHALLENGERMATCH")
REGISTERED_DEFAULT = "2026-11-04T18:00:00Z"
WEIGHTS = BASE / "research_tests" / "open_clv" / "kalshi_blend_weights.json"
CACHE = BASE / ".tql_cache"
MAX_SPREAD, MIN_LEAD_MIN, EDGE, CONTRACTS = 0.05, 60, 0.03, 100
NO_ROW_DAYS = 14
MIN_BETS, WINDOW_END, SEED = 300, "2027-10-31", 20261103
HIST_FILES = ("ATP.csv", "ATPQualifiers.csv", "Challenger.csv", "WTA.csv")


# ------------------------------------------------------------------ match facts (TennisMyLife)
def history_cache() -> Path:
    """The history cache (2010..last year), built once by bootstrap_v5_history.py, rebuilt after 30 days."""
    d = CACHE / ".v5_history_cache"
    stale = not (d / "ATP.csv").exists() or (time.time() - (d / "ATP.csv").stat().st_mtime) > 30 * 86400
    if stale:
        CACHE.mkdir(exist_ok=True)
        subprocess.run([sys.executable, str(BASE / "bootstrap_v5_history.py")], cwd=CACHE, check=True, timeout=3600,
                       env={**__import__("os").environ, "PYTHONPATH": str(BASE)})
    return d


def current_results(path: str | None) -> pd.DataFrame:
    if path:
        return pd.read_csv(path, low_memory=False, dtype={"tourney_id": str})
    subprocess.run(["git", "-C", str(BASE), "fetch", "-q", "origin", "main"], check=False, timeout=300)
    txt = subprocess.run(["git", "-C", str(BASE), "show", "origin/main:v5_results_ready/tennismylife_results.csv"],
                         capture_output=True, text=True, timeout=300).stdout
    return pd.read_csv(io.StringIO(txt), low_memory=False, dtype={"tourney_id": str})


def target_file(result_file: str, rnd: str) -> str:
    f = str(result_file).lower()
    if str(rnd).startswith("Q") or "quali" in f:
        return "ATPQualifiers.csv"
    if "challenger" in f:
        return "Challenger.csv"
    if "wta" in f:
        return "WTA.csv"
    return "ATP.csv"


def build_root(cache: Path, cur: pd.DataFrame, root: Path) -> Path:
    """root/.v5_history_cache = history + this season (the layout every research function reads), and
    root/v5_results_ready/tennismylife_results.csv = this season (for load_repo_matches)."""
    h = root / ".v5_history_cache"
    h.mkdir(parents=True)
    tf = [target_file(f, r) for f, r in zip(cur["result_file"], cur["round"])]
    for name in HIST_FILES:
        old = pd.read_csv(cache / name, low_memory=False, dtype={"tourney_id": str})
        add = cur[[t == name for t in tf]].drop(columns=["result_file"])
        pd.concat([old, add], ignore_index=True).to_csv(h / name, index=False)
    (root / "v5_results_ready").mkdir()
    cur.to_csv(root / "v5_results_ready" / "tennismylife_results.csv", index=False)
    return h


def player_inputs(root: Path, hdir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Per (canonical match key, player name): every frozen input; and the canonical match list."""
    import run_incentives as inc
    import run_scout as sc
    import v5_fatigue_features as F
    canon = F.load_repo_matches(str(root))
    cf = sc.canon_match_flags(sc.player_table(canon, sc.history_attrs(hdir)))
    p = inc.player_rows(inc.history(hdir))
    fl = p[["tourney_id", "round", "name", "w", "l", "qualifier", "season_end", "wildcard", "defending"]].drop_duplicates(["tourney_id", "round", "w", "l", "name"])
    raw = pd.concat([pd.read_csv(hdir / f, low_memory=False, dtype={"tourney_id": str}) for f in HIST_FILES], ignore_index=True)
    ages = pd.concat([pd.DataFrame({"tourney_id": raw["tourney_id"], "round": raw["round"], "w": raw["winner_name"], "l": raw["loser_name"],
                                    "name": raw[f"{s}_name"], "age": pd.to_numeric(raw[f"{s}_age"], errors="coerce")})
                      for s in ("winner", "loser")], ignore_index=True)
    ages = ages.drop_duplicates(["tourney_id", "round", "w", "l", "name"])
    m = canon[["key", "tid", "tourney_id_raw", "round", "date", "level", "winner_name", "loser_name"]]
    rows = []
    for nm_col in ("winner_name", "loser_name"):
        x = m.assign(name=m[nm_col])
        x = x.merge(fl, left_on=["tourney_id_raw", "round", "winner_name", "loser_name", "name"],
                    right_on=["tourney_id", "round", "w", "l", "name"], how="left").drop(columns=["tourney_id", "w", "l"])
        x = x.merge(ages, left_on=["tourney_id_raw", "round", "winner_name", "loser_name", "name"],
                    right_on=["tourney_id", "round", "w", "l", "name"], how="left").drop(columns=["tourney_id", "w", "l"])
        rows.append(x)
    x = pd.concat(rows, ignore_index=True)
    x = x.join(cf, on=["key", "name"]).drop_duplicates(["key", "name"])
    return x.set_index(["key", "name"]), m


def match_row(m: pd.DataFrame, a: str, b: str, start: pd.Timestamp) -> str | None:
    """Canonical key of the match between players a and b around the scheduled start (None if absent)."""
    na, nb = norm(a), norm(b)
    day = start.tz_convert(None).normalize()
    c = m[(m["date"] <= day) & (m["date"] >= day - pd.Timedelta(days=16))]
    w, l = c["winner_name"].map(norm), c["loser_name"].map(norm)
    hit = c[((w == na) & (l == nb)) | ((w == nb) & (l == na))]
    return None if hit.empty else str(hit.sort_values("date").iloc[-1]["key"])


def inputs_for(px: pd.DataFrame, key: str, a_canon: str, b_canon: str, level: str, inputs: list[str]) -> dict:
    ra, rb = px.loc[(key, a_canon)], px.loc[(key, b_canon)]
    main = level != "C"
    out = {}
    for f in inputs:
        if f == "age_gap":
            aa, ab = float(ra["age"]), float(rb["age"])
            out[f] = float(np.clip((aa - ab) / 5, -3, 3)) if np.isfinite(aa) and np.isfinite(ab) else 0.0
        else:
            va, vb = float(np.nan_to_num(ra[f])), float(np.nan_to_num(rb[f]))
            out[f] = (va - vb) * (1.0 if (f != "qualifier" or main) else 0.0)
    return out


# ------------------------------------------------------------------ Kalshi side
def snapshots(g: pd.DataFrame) -> list[tuple[pd.Timestamp, pd.DataFrame]]:
    return [(t, s) for t, s in g.groupby("polled_utc", sort=True)]


def quoted(s: pd.DataFrame, max_spread: float | None) -> bool:
    if s["ticker"].nunique() != 2 or s[["bid", "ask"]].isna().any().any():
        return False
    if (s["bid"] <= 0).any() or (s["ask"] >= 1).any():
        return False
    return max_spread is None or bool(((s["ask"] - s["bid"]) <= max_spread + 1e-9).all())


def mids(s: pd.DataFrame) -> dict:
    s = s.drop_duplicates("ticker")
    return {t: (b + a) / 2 for t, b, a in zip(s["ticker"], s["bid"], s["ask"])}


def decide(ev: str, g: pd.DataFrame, start: pd.Timestamp, live_t, registered: pd.Timestamp) -> dict | None:
    """Opening and closing snapshots for one match, from quotes only (no model)."""
    if pd.isna(start) or start <= registered:
        return None
    pre = g[g["polled_utc"] < (live_t if live_t is not None else start)]
    snaps = snapshots(pre)
    open_ = next(((t, s) for t, s in snaps if t <= start - pd.Timedelta(minutes=MIN_LEAD_MIN) and quoted(s, MAX_SPREAD)), None)
    close = next(((t, s) for t, s in reversed(snaps) if quoted(s, None)), None)
    if open_ is None or close is None:
        return None
    return {"open_t": open_[0], "open": open_[1].drop_duplicates("ticker").set_index("ticker"),
            "close_t": close[0], "close_mid": mids(close[1])}


def sigmoid(z: float) -> float:
    return 1 / (1 + math.exp(-z))


def bet_for(open_q: pd.DataFrame, ta: str, tb: str, x: dict, w: dict) -> dict:
    ma = (open_q.loc[ta, "bid"] + open_q.loc[ta, "ask"]) / 2
    mb = (open_q.loc[tb, "bid"] + open_q.loc[tb, "ask"]) / 2
    pa = ma / (ma + mb)
    z = w["open"] * math.log(pa / (1 - pa)) + sum(w[k] * v for k, v in x.items())
    p = sigmoid(z)
    out = {"p_open_a": round(pa, 4), "p_model_a": round(p, 4)}
    sides = []
    for t, o, pt in ((ta, tb, p), (tb, ta, 1 - p)):
        yes, no = float(open_q.loc[t, "ask"]), 1 - float(open_q.loc[o, "bid"])
        how, price = ("YES", yes) if yes <= no else ("NO on opponent", no)
        fee = taker_fee_per_contract(price)
        sides.append({"backed_ticker": t, "other_ticker": o, "how": how, "price": round(price, 4), "fee_per_contract": fee,
                      "model_chance": round(pt, 4), "edge": round(pt - price - fee, 4)})
    best = max(sides, key=lambda s: s["edge"])
    out.update(best)
    out["bet"] = bool(best["edge"] >= EDGE)
    return out


def settle(d: pd.DataFrame, prior: pd.DataFrame, get) -> pd.DataFrame:
    known = dict(zip(prior["backed_ticker"], prior["result"])) if len(prior) and "result" in prior else {}
    res = []
    for t, b in zip(d["backed_ticker"], d["bet"]):
        r = known.get(t)
        if b and r not in ("yes", "no"):
            try:
                r = (get(f"/markets/{t}").get("market") or {}).get("result") or ""
            except (requests.RequestException, RuntimeError, ValueError):
                r = ""
        res.append(r if b else "")
    d = d.assign(result=res)
    ok = d["result"].isin(["yes", "no"])
    d["pnl_per_contract"] = np.where(ok, np.where(d["result"] == "yes", 1 - d["price"], -d["price"]) - d["fee_per_contract"], np.nan)
    return d


def summary(d: pd.DataFrame, counts: dict) -> dict:
    b = d[d["bet"].astype(bool)] if len(d) else d
    out = {"registration": "docs/registrations/2026-11-04-kalshi-blend-at-open.md", "decisions": int(len(d)), "bets": int(len(b)),
           "settled": int(len(b)), "min_matches": MIN_BETS, "window_end": WINDOW_END, "counts": counts,
           "metric": "CLV cents per contract (close mid of the backed player minus price and fee)"}
    if len(b):
        x = b["clv_per_contract"].to_numpy(float)
        g = np.random.default_rng(SEED)
        lo, hi = np.percentile([x[g.integers(0, len(x), len(x))].mean() for _ in range(2000)], [2.5, 97.5])
        pnl = b["pnl_per_contract"].dropna().to_numpy(float)
        out.update({"cents_per_contract": round(100 * float(x.mean()), 3), "range_cents": [round(100 * lo, 3), round(100 * hi, 3)],
                    "clv_hit": round(float((b["p_close_backed"] > b["p_open_backed"]).mean()), 3),
                    "move_cents": round(100 * float((b["p_close_backed"] - b["p_open_backed"]).mean()), 3),
                    "results_settled": int(len(pnl)),
                    "pnl_cents_per_contract": round(100 * float(pnl.mean()), 3) if len(pnl) else None,
                    "dollars_at_100_contracts": round(float(100 * pnl.sum()), 2) if len(pnl) else None,
                    "by_series": {s: int(n) for s, n in b["series"].value_counts().items()},
                    "status": ("PASS" if lo > 0 else "FAIL") if len(b) >= MIN_BETS else "running"})
        out["note"] = f"P&L {out['pnl_cents_per_contract']}c on {len(pnl)} settled" if len(pnl) else ""
    else:
        out["status"] = "running"
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--registered", default=REGISTERED_DEFAULT)
    ap.add_argument("--results", default=None)
    args = ap.parse_args()
    registered = pd.Timestamp(args.registered)
    w = json.loads(WEIGHTS.read_text())
    weights, inputs = w["weights"], w["inputs"]
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{NAME}.csv"
    prior = pd.read_csv(path) if path.exists() else pd.DataFrame()
    done = set(prior["event_ticker"]) if len(prior) else set()
    q = load_quotes()
    counts = {"no_quotes": 0, "no_row_yet": 0, "no_row": 0, "decided": 0}
    rows = [] if prior.empty else prior.to_dict("records")
    sess = requests.Session()
    get = lambda p: sess.get(API + p, timeout=30).json()  # noqa: E731
    if not q.empty:
        q = q[q["series"].isin(SERIES)]
        start = q.groupby("event_ticker")["start_date"].max()
        live = first_live()
        cand = []
        for ev, g in q.groupby("event_ticker"):
            if ev in done:
                continue
            snap = decide(ev, g, start.get(ev), live.get(ev), registered)
            if snap is None:
                counts["no_quotes"] += 1
                continue
            cand.append((ev, g, snap))
        if cand:
            names = {}
            cache = OUT / f"{NAME}_names.json"
            if cache.exists():
                names.update(json.loads(cache.read_text()))
            for ev, g, snap in cand:
                for t in snap["open"].index:
                    if t not in names:
                        try:
                            m = get(f"/markets/{t}").get("market") or {}
                            nm = m.get("yes_sub_title") or ""
                            if nm:
                                names[t] = nm
                        except (requests.RequestException, RuntimeError, ValueError):
                            pass
            cache.write_text(json.dumps(names, indent=0, sort_keys=True))
            with tempfile.TemporaryDirectory() as tmp:
                hdir = build_root(history_cache(), current_results(args.results), Path(tmp))
                px, m = player_inputs(Path(tmp), hdir)
                for ev, g, snap in cand:
                    st = start.get(ev)
                    ta, tb = sorted(snap["open"].index)
                    a, b = names.get(ta), names.get(tb)
                    key = match_row(m, a, b, st) if a and b else None
                    if key is None:
                        if pd.Timestamp.now(tz="UTC") - st > pd.Timedelta(days=NO_ROW_DAYS):
                            counts["no_row"] += 1
                            rows.append({"event_ticker": ev, "series": g["series"].iloc[0], "start_date": st.isoformat(), "bet": False, "status": "no row"})
                        else:
                            counts["no_row_yet"] += 1
                        continue
                    mr = m[m["key"] == key].iloc[0]
                    ca = mr["winner_name"] if norm(mr["winner_name"]) == norm(a) else mr["loser_name"]
                    cb = mr["loser_name"] if ca == mr["winner_name"] else mr["winner_name"]
                    try:
                        x = inputs_for(px, key, ca, cb, str(mr["level"]), inputs)
                    except KeyError:                                   # fail closed: an input is missing, no bet
                        counts["no_inputs"] = counts.get("no_inputs", 0) + 1
                        rows.append({"event_ticker": ev, "series": g["series"].iloc[0], "start_date": st.isoformat(), "bet": False, "status": "no inputs"})
                        continue
                    bt = bet_for(snap["open"], ta, tb, x, weights)
                    pc = snap["close_mid"]
                    po_b = (snap["open"].loc[bt["backed_ticker"], ["bid", "ask"]].mean()) / snap["open"][["bid", "ask"]].mean(axis=1).sum()
                    pc_b = pc[bt["backed_ticker"]] / sum(pc.values())
                    rows.append({"event_ticker": ev, "series": g["series"].iloc[0], "start_date": st.isoformat(),
                                 "open_utc": snap["open_t"].isoformat(), "close_utc": snap["close_t"].isoformat(), "match_key": key,
                                 "player_a": a, "player_b": b, **{f"x_{k}": round(v, 4) for k, v in x.items()}, **bt,
                                 "p_open_backed": round(float(po_b), 4), "p_close_backed": round(float(pc_b), 4),
                                 "clv_per_contract": round(float(pc_b - bt["price"] - bt["fee_per_contract"]), 4), "status": "decided"})
                    counts["decided"] += 1
    d = pd.DataFrame(rows)
    if len(d):
        d["bet"] = d["bet"].fillna(False).astype(bool)
        d = settle(d, prior, get)
        d.to_csv(path, index=False)
    s = summary(d[d.get("status", pd.Series(dtype=str)) == "decided"] if len(d) else d, counts)
    (OUT / f"{NAME}_summary.json").write_text(json.dumps(s, indent=1, default=str) + "\n")
    print(json.dumps(s, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
