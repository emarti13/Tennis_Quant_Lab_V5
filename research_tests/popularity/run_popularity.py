"""Popularity bias: is a famous player's price too short (and an unknown opponent's too long)?

Usage:  python research_tests/popularity/run_popularity.py JOINED_PKL FAME_DIR OUT_JSON

JOINED_PKL  the Kaggle odds join (2014-2025; bet365 open/close, Betfair close; the first player is the winner)
FAME_DIR    fetch_pageviews.py output: articles.csv (name -> Wikipedia title), views.csv (title, month, views)

Pre-registered 2026-11-03, before any result was seen. Idea: casual money follows famous names,
so the price may overrate fame beyond skill. The market price already includes skill, so the
test is whether fame explains what the price gets wrong.

  FAME      log(1 + English-Wikipedia page views in the calendar month BEFORE the match month);
            no article (or no tennis article) = 0, with a flag. Fame gap = A minus B.
  SET       ATP main, WTA main, Challenger; 2016-2025 (page views start 2015-07); oriented by a
            seeded coin flip, every A/B value taken from the flipped columns.
  PRIMARY   M0 = logistic on logit(Betfair close); M1 = M0 + fame gap (one coefficient); walk-forward
            by year, test 2022-2025: log loss M1 - M0, 95% range resampling matches; and the
            fitted fame coefficient (negative = fame overpriced).
  MONEY     back the less famous player when the fame gap is at least 2 (about 7x the page views),
            at Betfair close (2% commission) and at bet365 close and open; test years 2022-2025.
  SECONDARY by level; fame gap x market favourite (is the famous favourite or the famous underdog
            the mispriced one?); the same on Kalshi is a later step.
  CHECKS    swap-source; planted fame effect (results drawn with a known fame coefficient, must be
            found); market null; known answers.
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
BOOKS = {"bf_close": ("bf_w", "bf_l"), "b365_close": ("b365_w", "b365_l"), "b365_open": ("b365_w_opening", "b365_l_opening")}
COMMISSION = {"bf_close": 0.02, "b365_close": 0.0, "b365_open": 0.0}
TEST_YEARS = range(2022, 2026)
GAP = 2.0


def fame_table(fame_dir: Path) -> tuple[dict, pd.DataFrame]:
    arts = pd.read_csv(fame_dir / "articles.csv")
    views = pd.read_csv(fame_dir / "views.csv").dropna(subset=["month"])
    views["month"] = views["month"].astype(int).astype(str)
    return dict(zip(arts["name"], arts["title"])), views


def fame_lookup(names: pd.Series, months: pd.Series, title_of: dict, views: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """log1p(views) in the month before; has-article flag."""
    v = views.set_index(["title", "month"])["views"]
    prev = (pd.to_datetime(months + "01", format="%Y%m%d") - pd.offsets.MonthBegin(1)).dt.strftime("%Y%m")
    t = names.map(title_of)
    out = np.array([v.get((tt, m), 0.0) if isinstance(tt, str) else 0.0 for tt, m in zip(t, prev)], float)
    return np.log1p(out), t.map(lambda x: isinstance(x, str)).to_numpy()


def build(joined: pd.DataFrame, title_of: dict, views: pd.DataFrame) -> pd.DataFrame:
    j = joined.sort_values("match_key", kind="stable")
    month = pd.to_datetime(j["match_date"], format="%d.%m.%Y", errors="coerce").dt.strftime("%Y%m")
    ok = month.notna()
    j, month = j[ok], month[ok]
    f1, h1 = fame_lookup(j["winner_name"], month, title_of, views)
    f2, h2 = fame_lookup(j["loser_name"], month, title_of, views)
    flip = j["flip"].to_numpy(bool)
    out = pd.DataFrame({"match_key": j["match_key"].values, "year": month.str[:4].astype(int).values,
                        "level": j["odds_level"].values, "y": (~flip).astype(int)})
    out["fame_a"], out["fame_b"] = orient(f1, f2, flip)
    out["has_a"], out["has_b"] = orient(h1, h2, flip)
    out["fame_gap"] = out["fame_a"] - out["fame_b"]
    for book, (c1, c2) in BOOKS.items():
        oa, ob = orient(pd.to_numeric(j[c1], errors="coerce"), pd.to_numeric(j[c2], errors="coerce"), flip)
        out[f"p_{book}"] = devig(oa, ob)
        out[f"oa_{book}"], out[f"ob_{book}"] = oa, ob
    return out


def swap_source(joined: pd.DataFrame) -> pd.DataFrame:
    j = joined.copy()
    for a, b in [("winner_name", "loser_name"), *BOOKS.values()]:
        j[a], j[b] = joined[b].values, joined[a].values
    return j


def fit_predict(d: pd.DataFrame, book: str, cols: list[str], y=None, extra=None):
    from sklearn.linear_model import LogisticRegression
    X = pd.DataFrame({"mkt": logit(d[f"p_{book}"].to_numpy())})
    for c in cols:
        X[c] = d[c].to_numpy()
    if extra is not None:
        X["extra"] = extra
    yy = d["y"].to_numpy() if y is None else y

    def fp(tr, te):
        return LogisticRegression(C=1.0, max_iter=1000).fit(X[tr], yy[tr]).predict_proba(X[te])[:, 1]
    return walk_forward(d["year"].to_numpy(), TEST_YEARS, fp, first_train_year=2016)


def main() -> int:
    joined_pkl, fame_dir, out_json = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
    title_of, views = fame_table(fame_dir)
    joined = pd.read_pickle(joined_pkl)
    joined = joined[joined["tour"].isin(["ATP", "WTA"]) & joined["odds_level"].isin(["ATP main", "WTA main", "Challenger"])].reset_index(drop=True)
    joined = joined.assign(match_key=np.arange(len(joined)), flip=coin_flip(len(joined), SEED))
    df = build(joined, title_of, views)
    df = df[(df["year"] >= 2016) & df["p_bf_close"].notna()].reset_index(drop=True)
    df["fame_x_fav"] = df["fame_gap"] * np.sign(df["p_bf_close"] - 0.5)
    res = {"manifest": provenance.manifest({"joined": joined_pkl, "fame": str(fame_dir)}, {"orientation": SEED, "bootstrap": SEED},
                                          " ".join(["python"] + sys.argv)),
           "rows": int(len(df)), "article_coverage": {lv: round(float(((g["has_a"] == 1) & (g["has_b"] == 1)).mean()), 3) for lv, g in df.groupby("level")},
           "results": {}}
    R = res["results"]
    y = df["y"].to_numpy()
    test = df["year"].isin(TEST_YEARS).to_numpy()
    p0 = fit_predict(df, "bf_close", [])
    p1 = fit_predict(df, "bf_close", ["fame_gap"])
    m = test & np.isfinite(p1)
    R["PRIMARY M1 (fame gap) minus M0, Betfair close, 2022-25 log loss"] = [round(v, 5) for v in boot_mean(log_loss(y[m], p1[m]) - log_loss(y[m], p0[m]), seed=SEED)] + [int(m.sum())]
    from sklearn.linear_model import LogisticRegression
    X = pd.DataFrame({"mkt": logit(df["p_bf_close"]), "fame_gap": df["fame_gap"]})
    coef = LogisticRegression(C=1.0, max_iter=1000).fit(X[~test], y[~test]).coef_[0]
    g = np.random.default_rng(SEED)
    bs = []
    idx_all = np.flatnonzero(~test)
    for _ in range(200):
        i = idx_all[g.integers(0, len(idx_all), len(idx_all))]
        bs.append(LogisticRegression(C=1.0, max_iter=1000).fit(X.iloc[i], y[i]).coef_[0][1])
    R["fame coefficient 2016-21 (log-odds per unit of fame gap; negative = fame overpriced), range"] = [round(float(coef[1]), 4)] + [round(float(v), 4) for v in np.percentile(bs, [2.5, 97.5])]
    coef_t = LogisticRegression(C=1.0, max_iter=1000).fit(X[test], y[test]).coef_[0][1]
    R["fame coefficient 2022-25 (same fit on the test years, for stability)"] = round(float(coef_t), 4)
    p2 = fit_predict(df, "bf_close", ["fame_gap", "fame_x_fav"])
    R["M2 (fame gap and fame x favourite) minus M0, 2022-25"] = [round(v, 5) for v in boot_mean(log_loss(y[m], p2[m]) - log_loss(y[m], p0[m]), seed=SEED)]
    for lv in ("ATP main", "WTA main", "Challenger"):
        mm = m & (df["level"] == lv).to_numpy()
        R[f"M1 minus M0 by level: {lv}"] = [round(v, 5) for v in boot_mean(log_loss(y[mm], p1[mm]) - log_loss(y[mm], p0[mm]), seed=SEED)] + [int(mm.sum())]
    # residual by fame gap bin (raw, no model): A's result minus Betfair close, test years
    t = df[test]
    bins = pd.cut(t["fame_gap"], [-20, -3, -2, -1, -0.25, 0.25, 1, 2, 3, 20])
    R["A won minus Betfair close by fame gap (pts), 2022-25"] = {str(b): [int(len(x))] + [round(100 * v, 2) for v in boot_mean((x["y"] - x["p_bf_close"]).to_numpy(), seed=SEED)]
                                                               for b, x in t.groupby(bins, observed=True)}
    # money: back the less famous side when the gap is >= GAP
    for book in BOOKS:
        x = t[t[f"p_{book}"].notna() & (t["fame_gap"].abs() >= GAP)]
        back_a = (x["fame_gap"] <= -GAP).to_numpy()
        o = np.where(back_a, x[f"oa_{book}"], x[f"ob_{book}"])
        won = np.where(back_a, x["y"] == 1, x["y"] == 0)
        pnl = np.where(won, (o - 1) * (1 - COMMISSION[book]), -1.0)
        mean, lo, hi = boot_mean(pnl, seed=SEED)
        R[f"back the less famous (gap >= {GAP}) at {book}, 2022-25"] = {"n": int(len(x)), "roi": round(mean, 4), "range": [round(lo, 4), round(hi, 4)]}
    # checks
    C = {}
    raw = joined[joined["tour"] == "WTA"]
    cols = ["fame_a", "fame_b", "fame_gap", "p_bf_close", "oa_bf_close", "ob_bf_close"]
    C["swap_source"] = checks.swap_source(lambda r, f: build(r.assign(flip=f), title_of, views), raw, swap_source, raw["flip"].to_numpy(bool), cols)
    p_mkt = df["p_bf_close"].to_numpy()

    def run(yy, z):
        a0 = fit_predict(df, "bf_close", [], y=yy)
        a1 = fit_predict(df, "bf_close", ["fame_gap"], y=yy, extra=z)
        mm = test & np.isfinite(a1)
        return {"delta": boot_mean(log_loss(yy[mm], a1[mm]) - log_loss(yy[mm], a0[mm]), seed=SEED)}
    C["planted_edge"] = checks.planted_edge(run, p_mkt, size=0.15, seed=SEED)
    C["market_null"] = checks.market_null(run, p_mkt, seed=SEED + 1)
    C["known_answers"] = checks.known_answers(y[test], p_mkt[test], (0.55, 0.66))
    res["checks"] = C
    res["checks_passed"] = all(c["pass"] for c in C.values())
    prim = R["PRIMARY M1 (fame gap) minus M0, Betfair close, 2022-25 log loss"]
    res["alarms"] = checks.alarms(tuple(prim[:3]))
    Path(out_json).write_text(json.dumps(res, indent=1, default=str) + "\n")
    print(json.dumps({k: v for k, v in res.items() if k != "manifest"}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
