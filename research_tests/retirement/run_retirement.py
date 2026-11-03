"""Retirement risk: does the price miss a player who recently retired hurt or gave a walkover?

Usage:  python research_tests/retirement/run_retirement.py JOINED_PKL HISTORY_DIR OUT_JSON

Pre-registered 2026-11-03, before any result was seen. From the history file (ATP, WTA, Challenger),
each player's matches ordered by tournament date then round (never file order); for each match, the
player's earlier matches within 30 days:

  retired_recent   lost one of their previous two matches by retirement (score ends "RET") within 30 days
  walkover_recent  gave a walkover (score "W/O", as the loser) within 30 days
Both as A's minus B's.

  SET       ATP main, WTA main, Challenger with odds, 2016-2025; walk-forward, test 2022-2025.
  PRIMARY   M0 = logistic on logit(Betfair close); M1 = M0 + both differences (L2): log loss M1 - M0,
            2022-2025, 95% range resampling matches.
  SECONDARY each flag: flagged player won minus Betfair close (completed and retired matches as the
            odds file settles them), 2016-2025 and 2016-2021; how often the flagged player retires again;
            money (Betfair close, 2% commission; bet365 close) on 2022-2025 if a 2016-21 residual is
            beyond 2 points.
  CHECKS    swap-source; planted edge; market null; known answers.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research_kit import checks, provenance  # noqa: E402
from research_kit.core import boot_mean, coin_flip, devig, log_loss, logit, orient, walk_forward  # noqa: E402

SEED = 20261103
TEST_YEARS = range(2022, 2026)
FLAGS = ["retired_recent", "walkover_recent"]
BOOKS = {"bf_close": ("bf_w", "bf_l"), "b365_close": ("b365_w", "b365_l")}
COMMISSION = {"bf_close": 0.02, "b365_close": 0.0}
RR = {"Q1": 0, "Q2": 1, "Q3": 2, "R128": 3, "R64": 4, "R32": 5, "R16": 6, "QF": 7, "SF": 8, "BR": 9, "F": 9, "RR": 4}


def flags_per_match(hist_dir: Path) -> pd.DataFrame:
    h = pd.concat([pd.read_csv(hist_dir / f, low_memory=False) for f in ("ATP.csv", "WTA.csv", "Challenger.csv")], ignore_index=True)
    h["date"] = pd.to_datetime(h["tourney_date"].astype(str).str[:8], format="%Y%m%d", errors="coerce")
    h = h.dropna(subset=["date"])
    sc = h["score"].astype(str)
    h["ret"], h["wo"] = sc.str.contains("RET"), sc.str.contains("W/O")
    rows = pd.concat([pd.DataFrame({"tid": h["tourney_id"], "round": h["round"], "w": h["winner_name"], "l": h["loser_name"], "date": h["date"],
                                    "name": h[c], "lost": c == "loser_name", "ret": h["ret"], "wo": h["wo"]})
                      for c in ("winner_name", "loser_name")], ignore_index=True)
    rows["rr"] = rows["round"].map(RR).fillna(4)
    rows = rows.sort_values(["name", "date", "rr"]).reset_index(drop=True)
    rows["quit"] = rows["lost"] & rows["ret"]
    rows["gave_wo"] = rows["lost"] & rows["wo"]
    g = rows.groupby("name")
    out = {f: np.zeros(len(rows), int) for f in FLAGS}
    for k in (1, 2):
        d_prev = g["date"].shift(k)
        recent = ((rows["date"] - d_prev).dt.days <= 30) & ((rows["date"] - d_prev).dt.days >= 0)
        out["retired_recent"] |= (recent & g["quit"].shift(k).fillna(False).astype(bool)).to_numpy().astype(int)
        out["walkover_recent"] |= (recent & g["gave_wo"].shift(k).fillna(False).astype(bool)).to_numpy().astype(int)
    for f in FLAGS:
        rows[f] = out[f]
    rows["quit_now"] = rows["quit"].astype(int)
    w = rows[~rows["lost"]][["tid", "round", "w", "l"] + FLAGS].rename(columns={f: f"{f}_w" for f in FLAGS})
    l = rows[rows["lost"]][["tid", "round", "w", "l", "quit_now"] + FLAGS].rename(columns={f: f"{f}_l" for f in FLAGS})
    return w.merge(l, on=["tid", "round", "w", "l"]).drop_duplicates(["tid", "round", "w", "l"])


def build(joined, fm):
    j = joined.merge(fm, left_on=["tid", "wh_round", "winner_name", "loser_name"], right_on=["tid", "round", "w", "l"], how="inner")
    j = j.sort_values("match_key", kind="stable")
    flip = j["flip"].to_numpy(bool)
    out = pd.DataFrame({"match_key": j["match_key"].values, "year": pd.to_datetime(j["wh_date"]).dt.year.values, "level": j["odds_level"].values,
                        "y": (~flip).astype(int), "loser_quit": j["quit_now"].values})
    for f in FLAGS:
        a, b = orient(j[f"{f}_w"].to_numpy(), j[f"{f}_l"].to_numpy(), flip)
        out[f"a_{f}"], out[f"b_{f}"], out[f"d_{f}"] = a, b, a - b
    for book, (c1, c2) in BOOKS.items():
        oa, ob = orient(pd.to_numeric(j[c1], errors="coerce"), pd.to_numeric(j[c2], errors="coerce"), flip)
        out[f"p_{book}"] = devig(oa, ob)
        out[f"oa_{book}"], out[f"ob_{book}"] = oa, ob
    return out


def fit_predict(d, cols, y=None, extra=None):
    from sklearn.linear_model import LogisticRegression
    X = pd.DataFrame({"mkt": logit(d["p_bf_close"].to_numpy())})
    for c in cols:
        X[c] = d[c].to_numpy()
    if extra is not None:
        X["extra"] = extra
    yy = d["y"].to_numpy() if y is None else y
    return walk_forward(d["year"].to_numpy(), TEST_YEARS,
                        lambda tr, te: LogisticRegression(C=0.3, max_iter=1000).fit(X[tr], yy[tr]).predict_proba(X[te])[:, 1],
                        first_train_year=2016)


def swap_source(joined):
    j = joined.copy()
    for a, b in [("winner_name", "loser_name"), *BOOKS.values()]:
        j[a], j[b] = joined[b].values, joined[a].values
    return j.assign(_swapped=1)


def main() -> int:
    joined_pkl, hist_dir, out_json = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
    joined = pd.read_pickle(joined_pkl)
    joined = joined[joined["tour"].isin(["ATP", "WTA"]) & joined["odds_level"].isin(["ATP main", "WTA main", "Challenger"])].reset_index(drop=True)
    joined = joined.assign(match_key=np.arange(len(joined)), flip=coin_flip(len(joined), SEED))
    fm = flags_per_match(hist_dir)
    df = build(joined, fm)
    df = df[(df["year"] >= 2016) & df["p_bf_close"].notna()].reset_index(drop=True)
    res = {"manifest": provenance.manifest({"joined": joined_pkl, "history": str(hist_dir)}, {"orientation": SEED, "bootstrap": SEED}, " ".join(["python"] + sys.argv)),
           "rows": int(len(df)), "flag_rates": {f: round(float((df[f"d_{f}"] != 0).mean()), 4) for f in FLAGS},
           "base_retirement_rate": round(float(df["loser_quit"].mean()), 4), "results": {}}
    R = res["results"]
    y = df["y"].to_numpy()
    test = df["year"].isin(TEST_YEARS).to_numpy()
    early = (df["year"] < 2022).to_numpy()
    cols = [f"d_{f}" for f in FLAGS]
    p0, p1 = fit_predict(df, []), fit_predict(df, cols)
    m = test & np.isfinite(p1)
    R["PRIMARY M1 (retirement flags) minus M0, Betfair close, 2022-25"] = [round(v, 5) for v in boot_mean(log_loss(y[m], p1[m]) - log_loss(y[m], p0[m]), seed=SEED)] + [int(m.sum())]
    for f in FLAGS:
        a_only, b_only = (df[f"d_{f}"] == 1).to_numpy(), (df[f"d_{f}"] == -1).to_numpy()
        resid = np.where(a_only, y - df["p_bf_close"], np.where(b_only, (1 - y) - (1 - df["p_bf_close"]), np.nan))
        ra, re = resid[np.isfinite(resid)], resid[np.isfinite(resid) & early]
        lost = np.where(a_only, y == 0, np.where(b_only, y == 1, False))
        quit_again = (lost & (df["loser_quit"].to_numpy() == 1))[a_only | b_only].mean() if (a_only | b_only).any() else np.nan
        R[f"{f}: flagged player won minus Betfair close (pts)"] = {
            "all": [round(100 * v, 2) for v in boot_mean(ra, seed=SEED)] + [int(len(ra))],
            "2016-21": [round(100 * v, 2) for v in boot_mean(re, seed=SEED)] + [int(len(re))],
            "flagged player retires again in this match": round(float(quit_again), 4)}
        e = R[f"{f}: flagged player won minus Betfair close (pts)"]["2016-21"]
        if len(re) and abs(e[0]) >= 2:
            back_flagged = e[0] > 0
            for book in BOOKS:
                sel = test & (a_only | b_only) & df[f"p_{book}"].notna().to_numpy()
                x = df[sel]
                back_a = a_only[sel] if back_flagged else ~a_only[sel]
                o = np.where(back_a, x[f"oa_{book}"], x[f"ob_{book}"])
                won = np.where(back_a, x["y"] == 1, x["y"] == 0)
                pnl = np.where(won, (o - 1) * (1 - COMMISSION[book]), -1.0)
                mm, lo, hi = boot_mean(pnl, seed=SEED)
                R[f"MONEY {f}: back the {'flagged' if back_flagged else 'other'} player at {book}, 2022-25"] = {"n": int(len(x)), "roi": round(mm, 4), "range": [round(lo, 4), round(hi, 4)]}
    C = {}
    raw = joined[joined["tour"] == "WTA"]
    fm_sw = fm.rename(columns={"w": "l", "l": "w", **{f"{f}_w": f"{f}_l" for f in FLAGS}, **{f"{f}_l": f"{f}_w" for f in FLAGS}})
    C["swap_source"] = checks.swap_source(lambda r, f: build(r.assign(flip=f), fm_sw if "_swapped" in r else fm), raw, swap_source,
                                          raw["flip"].to_numpy(bool), cols + ["p_bf_close", "oa_bf_close", "ob_bf_close"])
    p_mkt = df["p_bf_close"].to_numpy()

    def run(yy, z):
        a0, a1 = fit_predict(df, [], y=yy), fit_predict(df, cols, y=yy, extra=z)
        mm = test & np.isfinite(a1)
        return {"delta": boot_mean(log_loss(yy[mm], a1[mm]) - log_loss(yy[mm], a0[mm]), seed=SEED)}
    C["planted_edge"] = checks.planted_edge(run, p_mkt, size=0.15, seed=SEED)
    C["market_null"] = checks.market_null(run, p_mkt, seed=SEED + 1)
    C["known_answers"] = checks.known_answers(y[test], p_mkt[test], (0.55, 0.66))
    res["checks"] = C
    res["checks_passed"] = all(c["pass"] for c in C.values())
    Path(out_json).write_text(json.dumps(res, indent=1, default=str) + "\n")
    print(json.dumps({k: v for k, v in res.items() if k != "manifest"}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
