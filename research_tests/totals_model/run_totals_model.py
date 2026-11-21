"""Total games: does the winner price, through the point model, say something the totals line misses?

Usage:  python research_tests/totals_model/run_totals_model.py ODDS_CSV OUT_JSON

ODDS_CSV  the Kaggle file tennis_matches_2014_2025.csv (alimoh89/tennis-results-and-betting-odds-20142025):
          bet365 winner odds, bet365 total-games line and over / under odds, the final score.

Pre-registered 2026-11-21, before any result. The r/algobetting post the user shared (2026-11-05) found
its edge in totals and spreads, not moneylines; Kalshi lists ATP / WTA total games and ATP game spreads.
Exploratory: all data before 2026-11-01.

  MATCHES   ATP main, ATP Challenger, WTA main (ITF out of scope), completed (no retirement or walkover),
            with bet365 winner odds, a total-games line and over / under odds; best of 3 or 5.
  MODEL     research_kit.inplay: serve probabilities solved from the de-vigged bet365 winner price at a
            serve LEVEL, then the full distribution of total games (a tie-break counts as one game,
            as in the source's total_games). P_model(over) = P(total > line).
  LEVEL     one per tour level x surface (Hard / Clay / Grass), fitted on 2016-2021 only: the level
            (grid 0.52-0.72, step 0.02, linear interpolation) whose mean predicted total games equals
            the mean actual total games, on up to 1,500 random matches per group (seed). Frozen for 2022-25.
  BOOK      P_book(over) = de-vigged bet365 over / under (proportional).
  PRIMARY   2022-2025: logistic of (total > line) on logit(P_book) alone vs logit(P_book) + (logit(P_model)
            - logit(P_book)), fitted on 2016-2021 (C = 1); log-loss difference on 2022-25, 95% range
            resampling matches. Integer lines that land exactly on the total (pushes) are dropped.
  MONEY     2022-2025, bet365 close: bet over when P_model - 1 / odds_over >= 0.03 (and under the same way),
            one bet per match, 1 unit; ROI with a 95% range. Also at 0.05.
  ALSO      by level and by surface; calibration of P_model and P_book in bins; the mean model and book
            lines; the coefficient on the model term.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research_kit import inplay as ip  # noqa: E402
from research_kit.core import boot_mean, log_loss, logit  # noqa: E402

SEED = 20261121
TEST = range(2022, 2026)
GRID = np.round(np.arange(0.52, 0.7201, 0.02), 2)


def load(path: str) -> pd.DataFrame:
    d = pd.read_csv(path, low_memory=False)
    d["level"] = np.where(d["tour"] == "ATP", np.where(d["tournament"].str.contains("challenger", case=False), "ATP Challenger", "ATP main"),
                          np.where(d["tournament"].str.contains("ITF", case=False), "WTA ITF", "WTA main"))
    d = d[d["level"] != "WTA ITF"]
    for c in ("bet365_odds_a", "bet365_odds_b", "bet365_total_games_line", "bet365_odds_over", "bet365_odds_under", "total_games", "match_format"):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    ok = (d["bet365_odds_a"] > 1) & (d["bet365_odds_b"] > 1) & (d["bet365_odds_over"] > 1) & (d["bet365_odds_under"] > 1)
    ok &= d["bet365_total_games_line"].between(10, 50) & d["total_games"].between(12, 66) & d["match_format"].isin([3, 5])
    if "completed" in d:
        ok &= pd.to_numeric(d["completed"], errors="coerce") == 1
    d = d[ok].copy()
    d["surf"] = d["surface"].astype(str).str.title().replace({"Indoors": "Hard", "Carpet": "Hard", "Indoor": "Hard"})
    d = d[d["surf"].isin(["Hard", "Clay", "Grass"])]
    pa = (1 / d["bet365_odds_a"]) / (1 / d["bet365_odds_a"] + 1 / d["bet365_odds_b"])
    d["p_win"] = pa                                                  # player_a is the winner: symmetric for totals
    d["p_book_over"] = (1 / d["bet365_odds_over"]) / (1 / d["bet365_odds_over"] + 1 / d["bet365_odds_under"])
    d["year"] = d["tournament_year"].astype(int)
    d["ftb"] = np.where(d["match_format"] == 5, np.where(d["year"] >= 2022, 10, 7), 7)
    return d.reset_index(drop=True)


def model_row(p_win: float, level: float, bo: int, ftb: int) -> dict:
    p = min(max(p_win, 0.02), 0.98)
    pa, pb = ip.solve_serve(p, level, best_of=bo, final_set_tb=ftb)
    return ip.total_games_dist(pa, pb, best_of=bo, final_set_tb=ftb)


def mean_games(rows: pd.DataFrame, level: float) -> float:
    m = [sum(k * v for k, v in model_row(r.p_win, level, int(r.match_format), int(r.ftb)).items()) for r in rows.itertuples()]
    return float(np.mean(m))


def fit_levels(d: pd.DataFrame) -> dict:
    train = d[(d["year"] >= 2016) & (d["year"] <= 2021)]
    rng = np.random.default_rng(SEED)
    out = {}
    for (lv, sf), g in train.groupby(["level", "surf"]):
        if len(g) < 300:
            continue
        s = g.iloc[rng.choice(len(g), size=min(1500, len(g)), replace=False)]
        actual = float(s["total_games"].mean())
        means = [mean_games(s, L) for L in GRID]
        lvl = float(np.interp(actual, means, GRID)) if means[0] <= actual <= means[-1] else float(GRID[int(np.argmin(np.abs(np.array(means) - actual)))])
        out[f"{lv}|{sf}"] = {"level": round(lvl, 4), "actual_mean_games": round(actual, 3), "n_fit": int(len(s))}
    return out


def main() -> int:
    d = load(sys.argv[1])
    levels = fit_levels(d)
    d = d[d["year"] >= 2016].copy()
    d["key"] = d["level"] + "|" + d["surf"]
    d = d[d["key"].isin(levels)].reset_index(drop=True)
    pm, mmean = [], []
    for r in d.itertuples():
        dist = model_row(r.p_win, levels[r.key]["level"], int(r.match_format), int(r.ftb))
        pm.append(ip.p_over(dist, r.bet365_total_games_line))
        mmean.append(sum(k * v for k, v in dist.items()))
    d["p_model_over"] = np.clip(pm, 0.01, 0.99)
    d["model_mean_games"] = mmean
    d = d[d["total_games"] != d["bet365_total_games_line"]].reset_index(drop=True)      # pushes out
    d["y"] = (d["total_games"] > d["bet365_total_games_line"]).astype(int)
    test = d["year"].isin(TEST).to_numpy()
    train = ~test
    from sklearn.linear_model import LogisticRegression
    xb = logit(d["p_book_over"].to_numpy())
    xm = logit(d["p_model_over"].to_numpy()) - xb
    y = d["y"].to_numpy()
    m0 = LogisticRegression(C=1.0, max_iter=1000).fit(xb[train].reshape(-1, 1), y[train])
    m1 = LogisticRegression(C=1.0, max_iter=1000).fit(np.column_stack([xb, xm])[train], y[train])
    p0 = m0.predict_proba(xb[test].reshape(-1, 1))[:, 1]
    p1 = m1.predict_proba(np.column_stack([xb, xm])[test])[:, 1]
    yt = y[test]
    res = {"levels": levels, "matches": int(len(d)), "test_matches": int(test.sum()),
           "by_level": d.loc[test, "level"].value_counts().to_dict(), "results": {}}
    R = res["results"]
    R["PRIMARY log loss (book + model) minus (book), 2022-25"] = [round(v, 5) for v in boot_mean(log_loss(yt, p1) - log_loss(yt, p0), seed=SEED)]
    R["model term coefficient (fitted 2016-21; 0 = no information)"] = round(float(m1.coef_[0][1]), 4)
    R["log loss, book alone / raw model alone, 2022-25"] = [round(float(log_loss(yt, d.loc[test, "p_book_over"]).mean()), 5),
                                                           round(float(log_loss(yt, d.loc[test, "p_model_over"]).mean()), 5)]
    t = d[test]
    R["mean line / model mean games / actual mean games, 2022-25"] = [round(float(t["bet365_total_games_line"].mean()), 2),
                                                                      round(float(t["model_mean_games"].mean()), 2), round(float(t["total_games"].mean()), 2)]
    for lv in ("ATP main", "ATP Challenger", "WTA main"):
        mm = test & (d["level"] == lv).to_numpy()
        R[f"log loss difference, {lv}"] = [round(v, 5) for v in boot_mean(log_loss(y[mm], m1.predict_proba(np.column_stack([xb, xm])[mm])[:, 1])
                                                                          - log_loss(y[mm], m0.predict_proba(xb[mm].reshape(-1, 1))[:, 1]), seed=SEED)] + [int(mm.sum())]
    for edge in (0.03, 0.05):
        eo = t["p_model_over"] - 1 / t["bet365_odds_over"]
        eu = (1 - t["p_model_over"]) - 1 / t["bet365_odds_under"]
        over = (eo >= edge) & (eo >= eu)
        under = (eu >= edge) & (eu > eo)
        won = np.where(over, t["y"] == 1, t["y"] == 0)
        odds = np.where(over, t["bet365_odds_over"], t["bet365_odds_under"])
        pnl = np.where(won, odds - 1, -1.0)[(over | under).to_numpy()]
        bets = t[(over | under).to_numpy()]
        R[f"MONEY edge >= {int(100 * edge)} pts at bet365 close, 2022-25"] = {
            "n": int(len(pnl)), "roi": [round(v, 4) for v in boot_mean(pnl, seed=SEED)] if len(pnl) else None,
            "share_over": round(float(over.sum() / max(len(pnl), 1)), 3),
            "by_level": {lv: int(n) for lv, n in bets["level"].value_counts().items()}}
    bins = pd.cut(t["p_model_over"] - t["p_book_over"], [-1, -0.10, -0.05, -0.02, 0.02, 0.05, 0.10, 1])
    R["over rate minus book, by model-minus-book gap (pts), 2022-25"] = {str(b): [int(len(g)), round(100 * float((g["y"] - g["p_book_over"]).mean()), 2)]
                                                                         for b, g in t.groupby(bins, observed=True)}
    Path(sys.argv[2]).write_text(json.dumps(res, indent=1, default=str) + "\n")
    print(json.dumps(res, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
