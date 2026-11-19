"""Can our information beat Pinnacle's opening price? (research, edge search 1)

Usage:  python scripts/measure_open_close_edge.py [--out docs/experiments/data/open_close_edge.json] [--matches-cache PATH]

Tennis match lines open a median 16h before the start, soon after the previous round ends.
If the opener is set before the previous round's load (minutes, sets, a third set, a
retirement) is priced in, a model that knows that load can beat the opener, and execution
books that copy the opener can be hit before the line moves. This measures it.

Chronological, nothing from the sealed period (from 2026-10-13; CLAUDE.md):
- every 2026 fixture in the price store with a Pinnacle moneyline open and close (de-vigged
  with Pinnacle's measured lam) joined to its TennisMyLife result (same join as the
  baseline measurement), with the leak-free Elo (v5_baseline_elo, production settings) and
  the leak-free fatigue features (v5_fatigue_features) for that match;
- fit on fixtures starting January-June, test on July to before the sealed period;
- 1) how much the market learns between open and close (log loss of open vs close);
- 2) does a logistic model on (open, Elo, fatigue) beat the open out of sample, and by how
  much against the close;
- 3) does the same information predict the open->close move (out-of-sample correlation
  and the share of fixtures where the predicted direction is right);
- 4) the same by tour level and by hours between open and start;
- 5) the value of that direction: the mean move of Pinnacle's fair price toward the side the
  model picks (what a quote skewed that way gains, before any spread), and the closing-line
  value of taking the model's side at each book's opening price (spread included), next to
  taking a random side.
Paired-bootstrap 95% intervals on every log-loss difference. Missing fatigue values get 0
plus a missing flag (never a silent fill).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
import v5_baseline_elo as be  # noqa: E402
from v5_devig import book_lam, devig  # noqa: E402
from v5_fatigue_features import build_training_table  # noqa: E402
from scripts.measure_baseline_elo import join_market, loss, paired  # noqa: E402

SEALED_FROM = pd.Timestamp("2026-10-13", tz="UTC")
TEST_FROM = pd.Timestamp("2026-07-01", tz="UTC")
FATIGUE = ["prev_in_event_minutes", "prev_in_event_sets", "prev_in_event_went_distance", "ev_matches_before",
           "ev_minutes_before", "ev_quali_matches_before", "weeks_since_prev_event", "matches_last_4w",
           "layoff_8w_plus", "retired_last_match", "retired_or_wo_last5"]
RIDGE = 1.0


def logit(p):
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def pinnacle_open_close(base: Path) -> pd.DataFrame:
    """One row per fixture: players, start, level family, de-vigged open and close for p1, hours open."""
    fx = pd.concat([pd.read_csv(p, dtype=str, keep_default_na=False) for p in sorted((base / "market_history" / "fixtures").glob("*.csv"))])
    fx = fx.drop_duplicates("fixture_id")
    fx["start"] = pd.to_datetime(fx["cutoff_utc"], utc=True)
    fx = fx[(fx["resolution"] == "ok") & (fx["start"] < SEALED_FROM) & (fx["player1_id"] != "") & (fx["player2_id"] != "")]
    pts = pd.concat([pd.read_csv(p, dtype={"fixture_id": str}) for p in sorted((base / "market_history" / "price_points").glob("*.csv"))])
    pts = pts[(pts["market_group"] == "moneyline") & (pts["bookmaker"] == "pinnacle") & (pts["close_stale"].astype(str) != "True")]
    wide = pts.pivot_table(index="fixture_id", columns="side", values=["open_price", "close_price"], aggfunc="first")
    wide.columns = [f"{a}_{b}" for a, b in wide.columns]
    opened = pts[pts["side"] == "p1"].drop_duplicates("fixture_id").set_index("fixture_id")["open_utc"]
    wide = wide.dropna()
    wide = wide[(wide[["open_price_p1", "open_price_p2", "close_price_p1", "close_price_p2"]] > 1).all(axis=1)]
    lam = book_lam("pinnacle")
    wide["open_p1"] = [devig([a, b], lam)[0] for a, b in zip(wide["open_price_p1"], wide["open_price_p2"])]
    wide["close_p1"] = [devig([a, b], lam)[0] for a, b in zip(wide["close_price_p1"], wide["close_price_p2"])]
    wide["open_utc"] = pd.to_datetime(opened.reindex(wide.index), utc=True)
    out = fx.merge(wide[["open_p1", "close_p1", "open_utc"]], left_on="fixture_id", right_index=True)
    out["hours_open"] = (out["start"] - out["open_utc"]).dt.total_seconds() / 3600
    out["market_p1"] = out["close_p1"]                    # join_market's column name
    return out


def fit_logistic(X: np.ndarray, y: np.ndarray, offset: np.ndarray, ridge: float = RIDGE) -> np.ndarray:
    """Logistic regression with a fixed offset (logit of the open): Newton steps, L2 on the weights."""
    w = np.zeros(X.shape[1])
    for _ in range(50):
        z = offset + X @ w
        p = 1 / (1 + np.exp(-z))
        g = X.T @ (p - y) + ridge * w
        h = (X * (p * (1 - p))[:, None]).T @ X + ridge * np.eye(len(w))
        step = np.linalg.solve(h, g)
        w -= step
        if np.abs(step).max() < 1e-9:
            break
    return w


def design(df: pd.DataFrame, cols: list[str], mu=None, sd=None):
    X = df[cols].to_numpy(float)
    if mu is None:
        mu, sd = X.mean(axis=0), X.std(axis=0)
        sd[sd == 0] = 1
    return (X - mu) / sd, mu, sd


def build(base: Path, cache: str | None) -> pd.DataFrame:
    m = pd.read_pickle(cache) if cache and Path(cache).exists() else be.load_matches(base)
    pred = be.run(m, be.PRODUCTION_PARAMS)
    feats = build_training_table(m).set_index("match_key")
    mk = pinnacle_open_close(base)
    j = join_market(pred, mk)
    j["family"] = j["edition_key"].str.split("|").str[0]
    j["y"] = (j["player1_id"] == j["winner_key"]).astype(int)          # fixture player1 won
    j["elo_p1"] = np.where(j["y"] == 1, j["p_winner"], 1 - j["p_winner"])
    j["n_min"] = np.minimum(j["n_winner"], j["n_loser"])
    f = feats.reindex(j["key"])
    # feature table is oriented by its own p1; turn its differences into fixture-p1 minus fixture-p2
    sign = np.where(f["won"].to_numpy() == j["y"].to_numpy(), 1.0, -1.0)
    for c in FATIGUE:
        d = f[f"d_{c}"].to_numpy(float) * sign
        j[f"d_{c}_missing"] = np.isnan(d).astype(float)
        j[f"d_{c}"] = np.nan_to_num(d, nan=0.0)
    return j.reset_index(drop=True)


def evaluate(j: pd.DataFrame, rng) -> dict:
    train, test = j[j["start"] < TEST_FROM], j[j["start"] >= TEST_FROM]
    y = test["y"].to_numpy()
    ll = lambda p: loss(np.where(y == 1, p, 1 - p))  # noqa: E731
    open_l, close_l = ll(test["open_p1"].to_numpy()), ll(test["close_p1"].to_numpy())
    out = {"n_train": int(len(train)), "n_test": int(len(test)),
           "log_loss": {"open": round(float(open_l.mean()), 5), "close": round(float(close_l.mean()), 5),
                        "elo": round(float(ll(test["elo_p1"].to_numpy()).mean()), 5)},
           "close_minus_open": paired(close_l, open_l, rng), "models": {}}
    fat = [f"d_{c}" for c in FATIGUE] + [f"d_{c}_missing" for c in FATIGUE]
    for name, cols in (("open+elo", ["elo_gap"]), ("open+fatigue", fat), ("open+elo+fatigue", ["elo_gap"] + fat)):
        for df in (train, test):
            df.loc[:, "elo_gap"] = logit(df["elo_p1"]) - logit(df["open_p1"])
        Xtr, mu, sd = design(train, cols)
        Xte, _, _ = design(test, cols, mu, sd)
        Xtr, Xte = np.c_[Xtr, np.ones(len(Xtr))], np.c_[Xte, np.ones(len(Xte))]
        w = fit_logistic(Xtr, train["y"].to_numpy(float), logit(train["open_p1"]))
        p = 1 / (1 + np.exp(-(logit(test["open_p1"]) + Xte @ w)))
        model_l = ll(p)
        # the same information predicting the move: predicted shift vs actual logit(close) - logit(open)
        shift = p - test["open_p1"].to_numpy()
        move = test["close_p1"].to_numpy() - test["open_p1"].to_numpy()
        big = np.abs(shift) >= 0.01
        out["models"][name] = {
            "log_loss": round(float(model_l.mean()), 5),
            "model_minus_open": paired(model_l, open_l, rng), "model_minus_close": paired(model_l, close_l, rng),
            "move_corr": round(float(np.corrcoef(shift, move)[0, 1]), 4),
            "direction_right_when_shift_ge_1pt": round(float((np.sign(shift[big]) == np.sign(move[big])).mean()), 4) if big.any() else None,
            "n_shift_ge_1pt": int(big.sum()),
            "weights": dict(zip(cols + ["intercept"], np.round(w, 4).tolist())),
        }
    return out


def move_value(j: pd.DataFrame, base: Path, rng) -> dict:
    """Section 5, on the test fixtures, for the open+elo+fatigue model."""
    pts = pd.concat([pd.read_csv(p, dtype={"fixture_id": str}) for p in sorted((base / "market_history" / "price_points").glob("*.csv"))])
    pts = pts[pts["market_group"] == "moneyline"]
    raw = pts.pivot_table(index=["fixture_id", "bookmaker"], columns="side", values="open_price", aggfunc="first").unstack("bookmaker")
    raw.columns = [f"open_{b}_{s}" for s, b in raw.columns]
    j = j.join(raw, on="fixture_id")
    j["elo_gap"] = logit(j["elo_p1"]) - logit(j["open_p1"])
    cols = ["elo_gap"] + [f"d_{c}" for c in FATIGUE] + [f"d_{c}_missing" for c in FATIGUE]
    train, test = j[j["start"] < TEST_FROM], j[j["start"] >= TEST_FROM].copy()
    Xtr, mu, sd = design(train, cols)
    Xte, _, _ = design(test, cols, mu, sd)
    w = fit_logistic(np.c_[Xtr, np.ones(len(Xtr))], train["y"].to_numpy(float), logit(train["open_p1"]))
    shift = 1 / (1 + np.exp(-(logit(test["open_p1"]) + np.c_[Xte, np.ones(len(Xte))] @ w))) - test["open_p1"].to_numpy()
    move = (test["close_p1"] - test["open_p1"]).to_numpy()

    def boot(x):
        b = x[rng.integers(0, len(x), size=(1000, len(x)))].mean(axis=1)
        return {"n": int(len(x)), "mean": round(float(x.mean()), 5), "ci95": [round(float(np.percentile(b, 2.5)), 5), round(float(np.percentile(b, 97.5)), 5)]}

    out = {"abs_move_median": round(float(np.median(np.abs(move))), 5), "toward_pick": {}, "taker_clv": {}}
    for t in (0.0, 0.01, 0.02):
        sel = np.abs(shift) >= t
        gain = np.sign(shift[sel]) * move[sel]
        fam = test["family"].to_numpy()[sel]
        out["toward_pick"][f"shift_ge_{t}"] = {"all": boot(gain), **{f: boot(gain[fam == f]) for f in ("ATP", "CHALLENGER", "WTA")}}
    for book in ("pinnacle", "betrivers", "draftkings"):
        a, b = test.get(f"open_{book}_p1"), test.get(f"open_{book}_p2")
        if a is None or b is None:
            continue
        ok = (a.notna() & b.notna()).to_numpy()
        price = np.where(shift >= 0, a, b)
        fair = np.where(shift >= 0, test["close_p1"], 1 - test["close_p1"])
        rand = np.r_[(a * test["close_p1"] - 1)[ok], (b * (1 - test["close_p1"]) - 1)[ok]]
        out["taker_clv"][book] = {"open_overround": round(float((1 / a + 1 / b - 1)[ok].mean()), 5),
                                  "model_side": boot((price * fair - 1)[ok]), "random_side": round(float(rand.mean()), 5)}
    return out


def by_group(j: pd.DataFrame, col: str, rng) -> dict:
    res = {}
    for g, part in j.groupby(col, observed=True):
        if (part["start"] >= TEST_FROM).sum() >= 150 and (part["start"] < TEST_FROM).sum() >= 300:
            r = evaluate(part.copy(), rng)
            res[str(g)] = {"n_test": r["n_test"], "log_loss": r["log_loss"], "close_minus_open": r["close_minus_open"],
                           "open+elo+fatigue_minus_open": r["models"]["open+elo+fatigue"]["model_minus_open"],
                           "move_corr": r["models"]["open+elo+fatigue"]["move_corr"]}
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="docs/experiments/data/open_close_edge.json")
    ap.add_argument("--matches-cache", default=None, help="a pickled v5_baseline_elo.load_matches frame (speed only)")
    ap.add_argument("--dump", default=None, help="also pickle the joined fixture table here (for follow-up checks)")
    args = ap.parse_args()
    rng = np.random.default_rng(20261018)
    j = build(BASE, args.matches_cache)
    if args.dump:
        j.to_pickle(args.dump)
    j = j[j["n_min"] >= 18]                           # the pricing minimum: only fixtures we would price
    report = {"all_priced": evaluate(j.copy(), rng), "move_value": move_value(j.copy(), BASE, rng)}
    j["hours_band"] = pd.cut(j["hours_open"], [-1, 8, 16, 24, 1e9], labels=["<8h", "8-16h", "16-24h", "24h+"])
    report["by_family"] = by_group(j, "family", rng)
    report["by_hours_open"] = by_group(j, "hours_band", rng)
    out = BASE / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1, default=str) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
