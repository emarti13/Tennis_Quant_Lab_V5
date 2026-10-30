"""Test T of docs/experiments/2026-10-30-prereg-kalshi-vs-pinnacle.md: take Kalshi's ask when it
is at least 2c (after the taker fee) below Pinnacle's no-vig price at the same checkpoint.

Rules are the pre-registered ones and are not changed here. Run from a checkout of main (the
data lives there): python research_tests/kalshi_pinnacle/run_take.py --data <main checkout>
-> results_take.json, qa_kalshi_pinnacle_take.json
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
from qa import QA  # noqa: E402

SEAL = pd.Timestamp("2026-10-13", tz="UTC")
CPS = ["t24h", "t12h", "t6h", "t1h"]
EDGE, MAX_GAP, MAX_SPREAD, MIN_N = 0.02, 0.10, 0.05, 100
RNG = np.random.default_rng(20261030)


def fee(p):
    return 0.07 * p * (1 - p)


def load(data: str):
    sys.path.insert(0, data)
    from v5_devig import book_lam, devig
    from v5_market_results import load_fixture_winners
    rd = lambda pat: pd.concat([pd.read_csv(f, dtype=str) for f in sorted(glob.glob(os.path.join(data, pat)))])
    fx = rd("market_history/fixtures/*.csv")
    fx = fx[fx.resolution == "ok"].drop_duplicates("fixture_id", keep="last")
    fx["start"] = pd.to_datetime(fx.cutoff_utc, utc=True, format="ISO8601")
    fx["family"] = fx.edition_key.str.split("|").str[0]
    k = rd("market_history/kalshi/price_points/*.csv")
    k = k[k.fixture_id.notna() & k.side.isin(["p1", "p2"])].drop_duplicates(["fixture_id", "side"], keep="last")
    pp = rd("market_history/price_points/*.csv")
    pin = pp[(pp.bookmaker == "pinnacle") & (pp.market_group == "moneyline") & pp.side.isin(["p1", "p2"])]
    pin = pin.drop_duplicates(["fixture_id", "side"], keep="last")
    ids = set(k.fixture_id) & set(pin.fixture_id) & set(fx[fx.start >= SEAL].fixture_id)
    lam = book_lam("pinnacle")

    def fair(col):
        w = pin[pin.fixture_id.isin(ids)].pivot(index="fixture_id", columns="side", values=col).astype(float)
        if col == "close_price":
            stale = pin[pin.fixture_id.isin(ids)].pivot(index="fixture_id", columns="side", values="close_stale")
            w[(stale == "True").any(axis=1)] = np.nan
        ok = (w.p1 > 1) & (w.p2 > 1)
        out = pd.Series(np.nan, index=w.index)
        out[ok] = [devig([a, b], lam)[0] for a, b in zip(w.p1[ok], w.p2[ok])]
        return out                                                         # P(p1) no-vig

    rows = []
    kk = k[k.fixture_id.isin(ids)]
    fairs = {c: fair(f"{c}_price") for c in CPS}
    fclose = fair("close_price")
    for _, r in kk.iterrows():
        fid, s = r.fixture_id, r.side
        flip = (lambda p: p) if s == "p1" else (lambda p: 1 - p)
        row = {"fixture_id": fid, "side": s, "fair_close": flip(fclose.get(fid, np.nan)),
               "kalshi_close_mid": np.nan}
        try:
            row["kalshi_close_mid"] = (float(r.close_bid) + float(r.close_ask)) / 2
        except (TypeError, ValueError):
            pass
        for c in CPS:
            row[f"fair_{c}"] = flip(fairs[c].get(fid, np.nan))
            row[f"bid_{c}"] = pd.to_numeric(r.get(f"{c}_bid"), errors="coerce")
            row[f"ask_{c}"] = pd.to_numeric(r.get(f"{c}_ask"), errors="coerce")
        rows.append(row)
    D = pd.DataFrame(rows).merge(fx[["fixture_id", "family", "start"]], on="fixture_id", how="left")
    w = load_fixture_winners(fx[fx.fixture_id.isin(ids)], base=data)
    w = w.drop_duplicates("fixture_id").set_index("fixture_id")
    D["void"] = D.fixture_id.map(w.void_for_measurement).fillna(True).astype(bool)
    D["won"] = D.fixture_id.map(w.winner_side) == D.side
    return D, len(ids)


def entries(D, edge):
    """The earliest checkpoint per fixture where a side signals; one contract."""
    out = []
    for fid, g in D.groupby("fixture_id"):
        for c in CPS:
            cand = []
            for _, r in g.iterrows():
                f, b, a = r[f"fair_{c}"], r[f"bid_{c}"], r[f"ask_{c}"]
                if not (np.isfinite(f) and np.isfinite(b) and np.isfinite(a)) or a <= 0 or a >= 1 or b <= 0:
                    continue
                if a - b > MAX_SPREAD or abs(f - (a + b) / 2) > MAX_GAP:
                    continue                                               # can't price: skip
                ev = f - a - fee(a)
                if ev >= edge:
                    cand.append((ev, r, a))
            if cand:
                ev, r, a = max(cand, key=lambda x: x[0])
                out.append({"fixture_id": fid, "side": r.side, "checkpoint": c, "family": r.family, "ask": a,
                            "fair": r[f"fair_{c}"], "ev_at_entry": ev, "fair_close": r.fair_close,
                            "kalshi_close_mid": r.kalshi_close_mid, "void": r.void, "won": r.won})
                break
    return pd.DataFrame(out)


def boot(x, reps=2000):
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    if len(x) == 0:
        return {"n": 0}
    m = RNG.integers(0, len(x), (reps, len(x)))
    bs = x[m].mean(1)
    return {"n": int(len(x)), "mean": round(float(x.mean()), 4), "lo": round(float(np.percentile(bs, 2.5)), 4),
            "hi": round(float(np.percentile(bs, 97.5)), 4)}


def summarize(E):
    cost = E.ask + fee(E.ask)
    clv = E.fair_close - cost
    clv_k = E.kalshi_close_mid - cost
    settled = E[~E.void]
    pnl = np.where(settled.won, 1.0, 0.0) - (settled.ask + fee(settled.ask))
    return {"clv_vs_pinnacle_close": boot(clv), "clv_vs_kalshi_close_mid": boot(clv_k),
            "settled_pnl_per_contract": boot(pnl), "mean_ask": round(float(E.ask.mean()), 4),
            "mean_ev_at_entry": round(float(E.ev_at_entry.mean()), 4)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    a = ap.parse_args()
    qa = QA("kalshi_pinnacle_take")
    D, n_fx = load(a.data)
    qa.count("sealed fixtures with Kalshi and Pinnacle", n_fx)
    qa.check("share of rows with a Pinnacle t1h fair", D.fair_t1h.notna().mean(), 0.5, 1.0)
    qa.check("share of rows with a Kalshi t1h ask", D.ask_t1h.notna().mean(), 0.5, 1.0)
    both = D.dropna(subset=["fair_t1h", "bid_t1h", "ask_t1h"])
    mid = (both.bid_t1h + both.ask_t1h) / 2
    qa.check("median |Pinnacle fair - Kalshi mid| at t1h", (both.fair_t1h - mid).abs().median(), 0.0, 0.05)
    qa.check("p1 fair + p2 fair at t1h (per fixture, median)",
             D.groupby("fixture_id").fair_t1h.sum(min_count=2).median(), 0.99, 1.01)
    qa.check("share of non-void fixtures with a winner", D[~D.void].won.groupby(D.fixture_id).any().mean(), 0.97, 1.0)
    R = {"rules": {"edge": EDGE, "max_gap": MAX_GAP, "max_spread": MAX_SPREAD, "min_n": MIN_N},
         "fixtures": n_fx, "fixture_dates": [str(D.start.min()), str(D.start.max())]}
    E = entries(D, EDGE)
    R["primary"] = summarize(E) if len(E) else {"n": 0}
    pc = R["primary"].get("clv_vs_pinnacle_close", {})
    R["pass"] = bool(pc.get("n", 0) >= MIN_N and pc.get("lo", -1) > 0)
    R["by_family"] = {f: summarize(g) for f, g in E.groupby("family")} if len(E) else {}
    R["by_checkpoint"] = {c: summarize(g) for c, g in E.groupby("checkpoint")} if len(E) else {}
    R["sensitivity"] = {}
    for e in (0.01, 0.03):
        Es = entries(D, e)
        R["sensitivity"][str(e)] = summarize(Es) if len(Es) else {"n": 0}
    qa.save(HERE)
    json.dump(R, open(os.path.join(HERE, "results_take.json"), "w"), indent=1, default=str)
    if len(E):
        E.to_csv(os.path.join(HERE, "entries_take.csv"), index=False)
    print(json.dumps(R, indent=1, default=str))


if __name__ == "__main__":
    main()
