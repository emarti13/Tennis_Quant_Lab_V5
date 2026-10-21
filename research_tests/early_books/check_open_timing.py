"""Check the book-opener result: model vs Pinnacle's open alone, and timing (was Pinnacle's
open known when the book opened?). Same data and blend as run_early_books.py, July-October."""
import glob, json, sys
from pathlib import Path
import numpy as np, pandas as pd
S = Path(sys.argv[1])
rng = np.random.default_rng(1)
lg = lambda p: np.log(np.clip(p, 1e-6, 1-1e-6)/(1-np.clip(p, 1e-6, 1-1e-6)))
m = pd.read_pickle(S/"tests/features/market_join.pkl"); m["start"] = pd.to_datetime(m["start"], utc=True)
m = m[m["start"] < pd.Timestamp("2026-10-13", tz="UTC")]
w = json.load(open(Path(__file__).with_name("results.json")))["blend_weights"]
m["pb"] = 1/(1+np.exp(-(w[0]*lg(m["open_p1"]) + w[1]*lg(m["pm"]) + w[2])))
pts = pd.concat([pd.read_csv(f, dtype={"fixture_id": str}) for f in glob.glob("market_history/price_points/*.csv")])
pts = pts[(pts["market_group"] == "moneyline") & pts["fixture_id"].isin(m["fixture_id"])]
pin = pts[(pts["bookmaker"] == "pinnacle") & (pts["side"] == "p1")].drop_duplicates("fixture_id").set_index("fixture_id")["open_utc"]
rows = []
for (fid, book), g in pts[pts["bookmaker"].isin(["draftkings", "betrivers"])].groupby(["fixture_id", "bookmaker"]):
    if set(g["side"]) != {"p1", "p2"}: continue
    a, b = g[g["side"] == "p1"].iloc[0], g[g["side"] == "p2"].iloc[0]
    if pd.notna(a["open_price"]) and pd.notna(b["open_price"]):
        rows.append({"fixture_id": fid, "book": book, "o1": a["open_price"], "o2": b["open_price"], "book_open": a["open_utc"]})
q = pd.DataFrame(rows).merge(m, on="fixture_id")
q["pin_open"] = pd.to_datetime(q["fixture_id"].map(pin), utc=True); q["book_open"] = pd.to_datetime(q["book_open"], utc=True)
q = q[q["start"] >= pd.Timestamp("2026-07-01", tz="UTC")]
q["pin_known"] = q["pin_open"] <= q["book_open"]
out = {"fixtures_book_rows": int(len(q)), "share_pinnacle_open_known_at_book_open": round(float(q["pin_known"].mean()), 3),
       "median_book_open_minus_pin_open_hours": round(float(((q["book_open"]-q["pin_open"]).dt.total_seconds()/3600).median()), 2)}
def run(d, fair, thr):
    p = d[fair].to_numpy(); r, clv, ids = [], [], []
    for side, oc in ((1, "o1"), (0, "o2")):
        pp = p if side == 1 else 1-p
        pick = pp*d[oc] - 1 > thr; part = d[pick]
        won = part["y"] == side
        r += list(np.where(won, part[oc]-1, -1.0)); fc = part["close_p1"] if side == 1 else 1-part["close_p1"]
        clv += list(fc*part[oc]-1); ids += list(part["fixture_id"])
    r, clv, ids = map(np.asarray, (r, clv, ids))
    if len(r) < 20: return {"bets": int(len(r))}
    u, inv = np.unique(ids, return_inverse=True); idx = rng.integers(0, len(u), size=(2000, len(u)))
    def ci(x):
        s, c = np.bincount(inv, x), np.bincount(inv); mm = s[idx].sum(1)/c[idx].sum(1)
        return [round(float(np.percentile(mm, 2.5)), 4), round(float(np.percentile(mm, 97.5)), 4)]
    return {"bets": int(len(r)), "ret": round(float(r.mean()), 4), "ret_ci95": ci(r), "clv": round(float(clv.mean()), 4), "clv_ci95": ci(clv)}
for book in ("draftkings", "betrivers"):
    for known in (None, True):
        d = q[q["book"] == book]
        if known: d = d[d["pin_known"]]
        for fair in ("open_p1", "pb"):
            out[f"{book}|pin_known_only={bool(known)}|fair={fair}|ev>3%"] = run(d, fair, 0.03)
Path(__file__).with_name("timing_check.json").write_text(json.dumps(out, indent=1)+"\n")
print(json.dumps(out, indent=1))
