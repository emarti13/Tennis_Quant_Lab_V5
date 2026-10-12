#!/usr/bin/env python3
"""
v5_model_guard.py - guardrail checks for a tennis win-probability model
====================================================================
Run this on EVERY model version, on backtest output AND live output, before
trusting a result. It looks for the ways tennis models silently break:

  ORIENTATION   player1 is secretly the winner (winner-first data layouts)
  TOO GOOD      results better than the betting market can achieve
  HIDDEN ANSWER right far more often than the probabilities admit
  CALIBRATION   "says 70%" doesn't win 70%
  BACKWARDS     a tournament/segment where flipping predictions scores better
  FUTURE DATA   features stamped at/after match start
  LEAKY FEATURE a single input predicts the winner suspiciously well
  DEFAULTS      players with no history silently treated as 50/50
  SKEW          live inputs/outputs look different from backtest
  DRIFT         live performance getting worse week by week
  JUMPS         a new version improving "too much" vs the previous one

Every check prints PASS / WARN / FAIL with what it means and what to look at.
Exit code is 1 if anything FAILs, so it can block a deploy.

INPUT (CSV, one row per match)
------------------------------
required:  date, player1, player2, model_prob (P player1 wins), won (1 if player1 won)
optional:  market_prob     no-vig market probability for player1
           split           'backtest' or 'live' (enables skew checks)
           level / tour / tournament   segments for breakdowns
           f_<name>        any feature columns the model used (oriented to player1)
           f_asof          latest timestamp of data used to build the features
           n_hist_p1, n_hist_p2   # of past matches found for each player
Also auto-reads the v5 warehouse export format (model_probability_player1, winner, ...).

USAGE
-----
    python v5_model_guard.py predictions.csv --tag v5.2
    python v5_model_guard.py --selftest            # proves each check fires on planted bugs
"""

import argparse
import csv
import math
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone

import numpy as np
import pandas as pd

HISTORY_FILE = "guard_history.csv"
PASS, WARN, FAIL, INFO = "PASS", "WARN", "FAIL", "INFO"


# ------------------------------------------------------------------ loading
def norm_name(n):
    n = str(n or "")
    if "," in n:
        last, first = n.split(",", 1)
        n = f"{first} {last}"
    n = unicodedata.normalize("NFKD", n).encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z ]", " ", n).split())


def derive_level(t):
    t = str(t)
    if re.search(r"US Open|Wimbledon|Roland Garros|French Open|Australian Open", t, re.I):
        return "Grand Slam"
    if re.search(r"Challenger", t, re.I):
        return "Challenger"
    if re.search(r"\bITF\b|\bM15\b|\bM25\b|\bW15\b|\bW35\b|\bW50\b|\bW75\b|\bW100\b", t, re.I):
        return "ITF"
    return "ATP/WTA tour"


def load(path):
    df = pd.read_csv(path)
    cols = set(df.columns)
    if "model_probability_player1" in cols:            # v5 warehouse export
        df = df.rename(columns={"model_probability_player1": "model_prob",
                                "market_no_vig_probability_player1": "market_prob",
                                "match_start_utc": "date", "fixture_id": "match_id"})
        df["won"] = (df["winner"].map(norm_name) == df["player1"].map(norm_name)).astype(int)
        unmatched = ~df["winner"].map(norm_name).isin(
            set(df["player1"].map(norm_name)) | set(df["player2"].map(norm_name)))
        if unmatched.any():
            print(f"  note: {unmatched.sum()} rows where the winner name matched neither player")
        if "score" in df.columns:
            df = df[~df["score"].fillna("").str.contains(r"W/O|walkover", case=False)]
    missing = [c for c in ("date", "player1", "player2", "model_prob", "won") if c not in df.columns]
    if missing:
        sys.exit(f"Missing required columns: {missing}")
    df["date"] = pd.to_datetime(df["date"], utc=True, format="mixed", errors="coerce")
    if "f_asof" in df.columns:
        df["f_asof"] = pd.to_datetime(df["f_asof"], utc=True, format="mixed", errors="coerce")
    if "level" not in df.columns and "tournament" in df.columns:
        df["level"] = df["tournament"].map(derive_level)
    if "split" not in df.columns:
        df["split"] = "all"
    return df.reset_index(drop=True)


# ------------------------------------------------------------------ helpers
def brier(p, y):
    return float(np.mean((np.asarray(p) - np.asarray(y)) ** 2))


def acc(p, y):
    return float(np.mean((np.asarray(p) >= 0.5) == (np.asarray(y) == 1)))


def conf(p):
    return float(np.mean(np.maximum(p, 1 - p)))


def auc(x, y):
    x, y = np.asarray(x, float), np.asarray(y, int)
    ok = ~np.isnan(x)
    x, y = x[ok], y[ok]
    n1, n0 = y.sum(), len(y) - y.sum()
    if n1 == 0 or n0 == 0:
        return float("nan")
    ranks = pd.Series(x).rank().values
    return float((ranks[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def psi(a, b, bins=10):
    a, b = np.asarray(a, float), np.asarray(b, float)
    a, b = a[~np.isnan(a)], b[~np.isnan(b)]
    if len(a) < 20 or len(b) < 20:
        return float("nan")
    edges = np.unique(np.quantile(a, np.linspace(0, 1, bins + 1)))
    if len(edges) < 3:
        return float("nan")
    pa = np.histogram(np.clip(a, edges[0], edges[-1]), edges)[0] / len(a) + 1e-4
    pb = np.histogram(np.clip(b, edges[0], edges[-1]), edges)[0] / len(b) + 1e-4
    return float(np.sum((pb - pa) * np.log(pb / pa)))


class Report:
    def __init__(self):
        self.items = []

    def add(self, status, name, msg, detail=None):
        self.items.append((status, name, msg, detail))

    def print(self):
        for status, name, msg, detail in self.items:
            print(f"\n[{status}] {name}\n  {msg}")
            if detail:
                for line in str(detail).splitlines():
                    print("    " + line)
        counts = {s: sum(1 for i in self.items if i[0] == s) for s in (FAIL, WARN, PASS)}
        print(f"\nSUMMARY: {counts[FAIL]} FAIL, {counts[WARN]} WARN, {counts[PASS]} PASS")
        return counts


# ------------------------------------------------------------------ checks
def check_integrity(df, R):
    probs = df["model_prob"]
    problems = []
    if probs.isna().any():
        problems.append(f"{probs.isna().sum()} missing model_prob")
    if ((probs < 0) | (probs > 1)).any():
        problems.append("model_prob outside 0-1")
    if not df["won"].isin([0, 1]).all():
        problems.append("won is not always 0/1")
    if (df["player1"].map(norm_name) == df["player2"].map(norm_name)).any():
        problems.append("player1 == player2 on some rows")
    if "match_id" in df.columns and df["match_id"].duplicated().any():
        problems.append(f"{df['match_id'].duplicated().sum()} duplicate match_id rows")
    if df["date"].isna().any():
        problems.append(f"{df['date'].isna().sum()} unparseable dates")
    if "market_prob" in df.columns and ((df["market_prob"] <= 0) | (df["market_prob"] >= 1)).any():
        problems.append("market_prob outside (0,1)")
    if problems:
        R.add(FAIL, "Data integrity", "; ".join(problems))
    else:
        R.add(PASS, "Data integrity", f"{len(df)} matches, no structural problems.")


def check_orientation(df, R):
    for sp, g in df.groupby("split"):
        n = len(g)
        r = g["won"].mean()
        z = (r - 0.5) / math.sqrt(0.25 / n)
        mp = g["model_prob"].mean()
        msg = (f"[{sp}] player1 won {r:.1%} of {n} matches (fair layout ~50%, z={z:+.1f}); "
               f"model's average P(player1) = {mp:.1%}.")
        if abs(z) > 4 and abs(r - 0.5) > 0.08:
            R.add(FAIL, "Orientation leak", msg + " player1 is NOT random. If player1 is built from "
                  "winner columns, the model is being handed the answer. Randomize who is player1.")
        elif abs(z) > 3:
            R.add(WARN, "Orientation leak", msg + " Check how player1 is chosen.")
        else:
            R.add(PASS, "Orientation leak", msg)


def check_too_good(df, R):
    for sp, g in df.groupby("split"):
        a = acc(g["model_prob"], g["won"])
        line = f"[{sp}] model picks winners {a:.1%}"
        if "market_prob" in g.columns and g["market_prob"].notna().any():
            gm = g[g["market_prob"].notna()]
            am, bm, bk = acc(gm["market_prob"], gm["won"]), brier(gm["model_prob"], gm["won"]), brier(gm["market_prob"], gm["won"])
            line += f"; market favorite {am:.1%}. Brier model {bm:.4f} vs market {bk:.4f}"
            if bm < bk - 0.010 and len(gm) >= 200:
                R.add(WARN, "Too good to be true", line + ". Beating the market by this much is rare - "
                      "prove there is no leak before believing it.")
                continue
        if len(g) >= 200 and a > 0.74:
            R.add(FAIL, "Too good to be true", line + ". Pre-match tennis winners are picked ~68-71% "
                  "by the betting market. Above ~74% almost always means leaked information.")
        elif len(g) >= 200 and a > 0.71:
            R.add(WARN, "Too good to be true", line + ". At or above market level - verify carefully.")
        else:
            R.add(PASS if len(g) >= 200 else INFO, "Too good to be true", line + ".")


def check_hidden_answer(df, R):
    for sp, g in df.groupby("split"):
        a, c = acc(g["model_prob"], g["won"]), conf(g["model_prob"])
        gap = a - c
        msg = f"[{sp}] right {a:.1%} of the time while its own probabilities average {c:.1%} confidence (gap {gap:+.1%})."
        if len(g) >= 200 and gap > 0.06:
            R.add(FAIL, "Hidden-answer signature", msg + " The model is right far more often than it "
                  "believes - classic sign it sees which side won but not by how much (orientation or "
                  "same-match stats leak).")
        elif len(g) >= 200 and gap < -0.06:
            R.add(WARN, "Overconfidence", msg + " Probabilities are too extreme for how often it is right.")
        else:
            R.add(PASS, "Hidden-answer signature", msg)


def calib_table(p, y, bins=(0, .2, .4, .6, .8, 1.0001)):
    rows, worst = [], 0.0
    for lo, hi in zip(bins[:-1], bins[1:]):
        m = (p >= lo) & (p < hi)
        n = int(m.sum())
        if n == 0:
            continue
        pred, act = float(p[m].mean()), float(y[m].mean())
        se = math.sqrt(max(pred * (1 - pred), 1e-4) / n)
        z = (act - pred) / se
        worst = max(worst, abs(z)) if n >= 20 else worst
        rows.append(f"{lo:.0%}-{min(hi, 1):.0%}: says {pred:5.1%}  won {act:5.1%}  n={n:<5} z={z:+.1f}")
    return rows, worst


def check_calibration(df, R):
    for sp, g in df.groupby("split"):
        rows, worst = calib_table(g["model_prob"].values, g["won"].values)
        status = FAIL if worst > 3 else WARN if worst > 2 else PASS
        R.add(status, "Calibration", f"[{sp}] worst bucket z={worst:.1f} (above 3 = clearly off).",
              "\n".join(rows))


def check_backwards_segments(df, R, min_n=15):
    seg_col = "tournament" if "tournament" in df.columns else "level" if "level" in df.columns else None
    if not seg_col:
        R.add(INFO, "Backwards segments", "No tournament/level column - skipped.")
        return
    bad = []
    for seg, g in df.groupby(seg_col):
        if len(g) < min_n:
            continue
        b, bf = brier(g["model_prob"], g["won"]), brier(1 - g["model_prob"], g["won"])
        if bf < b:
            bad.append(f"{str(seg)[:45]:45} n={len(g):<4} Brier {b:.3f} vs flipped {bf:.3f}")
    if bad:
        R.add(FAIL, "Backwards segments", "Flipping every prediction scores BETTER in these segments. "
              "That points to swapped players, broken ID/name matching or stale features there.",
              "\n".join(bad))
    else:
        R.add(PASS, "Backwards segments", f"No {seg_col} where flipped predictions score better.")


def check_disagreements(df, R, top=12):
    if "market_prob" not in df.columns or df["market_prob"].isna().all():
        R.add(INFO, "Big disagreements", "No market_prob column - skipped.")
        return
    g = df[df["market_prob"].notna()].copy()
    g["gap"] = g["model_prob"] - g["market_prob"]
    opposite = ((g["model_prob"] - .5) * (g["market_prob"] - .5) < 0) & (g["gap"].abs() > 0.30)
    share = opposite.mean()
    cols = [c for c in ("date", "tournament", "player1", "player2", "model_prob", "market_prob", "won",
                        "n_hist_p1", "n_hist_p2") if c in g.columns]
    worst = g.reindex(g["gap"].abs().sort_values(ascending=False).index).head(top)[cols]
    worst = worst.assign(date=worst["date"].dt.strftime("%Y-%m-%d")) if "date" in worst else worst
    msg = (f"{share:.1%} of matches have model and market picking OPPOSITE winners by 30+ points. "
           "Eyeball the rows below: missing history, swapped names and default ratings show up here first.")
    R.add(FAIL if share > 0.10 else WARN if share > 0.04 else PASS, "Big disagreements", msg,
          worst.to_string(index=False, float_format=lambda v: f"{v:.3f}"))


def check_future_data(df, R):
    if "f_asof" not in df.columns:
        R.add(WARN, "Future data", "No f_asof column. Add the timestamp of the newest data used to build "
              "each row's features - without it, look-ahead leaks can't be detected automatically.")
        return
    late = df["f_asof"] >= df["date"]
    same_day = (df["f_asof"].dt.date == df["date"].dt.date) & ~late
    if late.any():
        R.add(FAIL, "Future data", f"{late.sum()} rows use data stamped at/after match start. That data "
              "can include the match itself.", df.loc[late, ["date", "player1", "f_asof"]].head(8).to_string(index=False))
    elif same_day.mean() > 0.02:
        R.add(WARN, "Future data", f"{same_day.mean():.0%} of rows use same-day data. Fine only if those "
              "matches truly finished before this one started.")
    else:
        R.add(PASS, "Future data", "All features built from data before match day.")


def check_leaky_features(df, R):
    fcols = [c for c in df.columns if c.startswith("f_") and c != "f_asof" and pd.api.types.is_numeric_dtype(df[c])]
    if not fcols:
        R.add(INFO, "Leaky features", "No f_ feature columns supplied - skipped. Export features to enable.")
        return
    ref = auc(df["market_prob"], df["won"]) if "market_prob" in df.columns else 0.75
    lines, worst = [], PASS
    for c in fcols:
        a = auc(df[c], df["won"])
        a2 = max(a, 1 - a) if not math.isnan(a) else float("nan")
        flag = ""
        if a2 > 0.80 or (not math.isnan(ref) and a2 > ref + 0.02):
            flag, worst = "  <-- FAIL: predicts winner too well on its own", FAIL
        elif a2 > 0.72 and worst != FAIL:
            flag, worst = "  <-- check", WARN
        lines.append(f"{c:30} AUC {a2:.3f}{flag}")
    R.add(worst, "Leaky features", f"How well each input alone predicts the winner (0.5 = useless, "
          f"market = {ref:.3f}). A single stat beating the whole market is almost always built from the "
          "match itself.", "\n".join(lines))


def check_defaults(df, R):
    if {"n_hist_p1", "n_hist_p2"} <= set(df.columns):
        low = (df[["n_hist_p1", "n_hist_p2"]].min(axis=1) < 5)
        msg = f"{low.mean():.1%} of matches have a player with <5 past matches found."
        if "market_prob" in df.columns and low.any() and (~low).any():
            b_low = brier(df.loc[low, "model_prob"], df.loc[low, "won"]) - brier(df.loc[low, "market_prob"], df.loc[low, "won"])
            b_ok = brier(df.loc[~low, "model_prob"], df.loc[~low, "won"]) - brier(df.loc[~low, "market_prob"], df.loc[~low, "won"])
            msg += f" Model-minus-market Brier: low-history {b_low:+.4f}, normal {b_ok:+.4f}."
        R.add(WARN if low.mean() > 0.10 else PASS, "Missing history / defaults", msg)
        return
    near = (df["model_prob"] - 0.5).abs() < 0.01
    msg = (f"{near.mean():.1%} of predictions are exactly ~50/50. No n_hist columns supplied, so this is "
           "a proxy: players not found in history often get default ratings and land near 50%.")
    R.add(WARN if near.mean() > 0.05 else PASS, "Missing history / defaults",
          msg + " Export n_hist_p1/n_hist_p2 for a direct check.")


def check_skew(df, R):
    splits = set(df["split"])
    if not {"backtest", "live"} <= splits:
        R.add(INFO, "Backtest vs live skew", "Needs both split=backtest and split=live rows in one file. "
              "This is the check that catches 'great backtest, bad live'.")
        return
    bt, lv = df[df["split"] == "backtest"], df[df["split"] == "live"]
    lines = [f"{'':22}{'backtest':>10}{'live':>10}",
             f"{'picks winners':22}{acc(bt.model_prob, bt.won):>10.1%}{acc(lv.model_prob, lv.won):>10.1%}",
             f"{'Brier':22}{brier(bt.model_prob, bt.won):>10.4f}{brier(lv.model_prob, lv.won):>10.4f}",
             f"{'avg confidence':22}{conf(bt.model_prob):>10.1%}{conf(lv.model_prob):>10.1%}",
             f"{'player1 win rate':22}{bt.won.mean():>10.1%}{lv.won.mean():>10.1%}"]
    status = PASS
    drop = brier(lv.model_prob, lv.won) - brier(bt.model_prob, bt.won)
    if drop > 0.03:
        status = FAIL
    elif drop > 0.015:
        status = WARN
    fcols = [c for c in df.columns if c.startswith("f_") and c != "f_asof" and pd.api.types.is_numeric_dtype(df[c])]
    for c in fcols:
        v = psi(bt[c], lv[c])
        tag = "  <-- shifted" if v > 0.25 else ""
        if v > 0.25:
            status = FAIL
        lines.append(f"{'PSI ' + c:22}{v:>10.3f}{tag}")
    R.add(status, "Backtest vs live skew", f"Live Brier is {drop:+.4f} vs backtest. Large gaps mean the "
          "backtest saw something live doesn't (leak) or live inputs are built differently (skew). "
          "PSI > 0.25 on a feature = its live values look different from backtest.", "\n".join(lines))


def check_drift(df, R):
    g = df[df["split"] == "live"] if "live" in set(df["split"]) else df
    if g["date"].isna().all() or len(g) < 60:
        R.add(INFO, "Drift over time", "Not enough dated rows.")
        return
    wk = g.assign(week=g["date"].dt.tz_convert(None).dt.to_period("W").dt.start_time)
    lines, xs, ys = [], [], []
    for i, (w, x) in enumerate(wk.groupby("week")):
        if len(x) < 10:
            continue
        bm = brier(x.model_prob, x.won)
        rel = bm - brier(x.market_prob, x.won) if "market_prob" in x else bm - 0.25
        xs.append(i)
        ys.append(rel)
        lines.append(f"week of {w:%Y-%m-%d}  n={len(x):<4} model Brier {bm:.4f}  model-minus-"
                     f"{'market' if 'market_prob' in x else 'coinflip'} {rel:+.4f}")
    if len(xs) < 3:
        R.add(INFO, "Drift over time", "Fewer than 3 usable weeks.", "\n".join(lines))
        return
    slope = float(np.polyfit(xs, ys, 1)[0])
    status = WARN if slope > 0.005 else PASS
    R.add(status, "Drift over time", f"Trend {slope:+.4f} Brier/week vs the benchmark (positive = getting "
          "worse). Steady worsening usually means features stopped updating after go-live.", "\n".join(lines))


def check_jumps(df, R, tag):
    summary = {"tag": tag or "", "run_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")}
    for sp, g in df.groupby("split"):
        summary[f"{sp}_n"] = len(g)
        summary[f"{sp}_brier"] = round(brier(g.model_prob, g.won), 5)
        summary[f"{sp}_acc"] = round(acc(g.model_prob, g.won), 4)
    prev = None
    if os.path.exists(HISTORY_FILE):
        hist = pd.read_csv(HISTORY_FILE)
        if len(hist):
            prev = hist.iloc[-1].to_dict()
    if prev:
        lines, status = [], PASS
        for k, v in summary.items():
            if k.endswith("_brier") and k in prev and not pd.isna(prev[k]):
                d = v - prev[k]
                lines.append(f"{k:18} {prev[k]:.4f} -> {v:.4f} ({d:+.4f})")
                if d < -0.010:
                    status = WARN
                    lines[-1] += "  <-- big improvement: explain WHY before accepting"
                elif d > 0.010:
                    status = WARN
                    lines[-1] += "  <-- got worse"
        R.add(status, "Change vs previous version", f"Compared with '{prev.get('tag', '')}' "
              f"({prev.get('run_at', '')}). Real gains are usually small; a big jump after one change "
              "is more often a new leak than a breakthrough.", "\n".join(lines))
    else:
        R.add(INFO, "Change vs previous version", f"First run - baseline saved to {HISTORY_FILE}.")
    if tag:
        exists = os.path.exists(HISTORY_FILE)
        keys = list(summary)
        if exists:
            old = pd.read_csv(HISTORY_FILE)
            keys = list(dict.fromkeys(list(old.columns) + keys))
            pd.concat([old, pd.DataFrame([summary])], ignore_index=True)[keys].to_csv(HISTORY_FILE, index=False)
        else:
            pd.DataFrame([summary]).to_csv(HISTORY_FILE, index=False)


def run(df, tag=None, quiet=False):
    R = Report()
    check_integrity(df, R)
    check_orientation(df, R)
    check_too_good(df, R)
    check_hidden_answer(df, R)
    check_calibration(df, R)
    check_backwards_segments(df, R)
    check_disagreements(df, R)
    check_future_data(df, R)
    check_leaky_features(df, R)
    check_defaults(df, R)
    check_skew(df, R)
    check_drift(df, R)
    check_jumps(df, R, tag)
    if not quiet:
        R.print()
    return R


# ------------------------------------------------------------------ self-test
def synth(n=3000, seed=0, leak=None):
    """Synthetic matches. leak in {None, 'orientation', 'future', 'swap', 'skew'}."""
    rng = np.random.default_rng(seed)
    skill_gap = rng.normal(0, 1.0, n)
    true_p = 1 / (1 + np.exp(-1.1 * skill_gap))
    won = (rng.random(n) < true_p).astype(int)
    market = np.clip(1 / (1 + np.exp(-(1.1 * skill_gap + rng.normal(0, .15, n)))), .02, .98)
    model = np.clip(1 / (1 + np.exp(-(1.1 * skill_gap + rng.normal(0, .35, n)))), .02, .98)
    dates = pd.date_range("2024-01-01", periods=n, freq="4h", tz="UTC")
    serve = 0.62 + 0.02 * skill_gap + rng.normal(0, .02, n)
    df = pd.DataFrame({"match_id": range(n), "date": dates, "player1": [f"A{i}" for i in range(n)],
                       "player2": [f"B{i}" for i in range(n)], "model_prob": model, "won": won,
                       "market_prob": market, "tournament": rng.choice(["T1", "T2", "T3", "T4"], n),
                       "f_serve_form": serve, "f_asof": dates - pd.Timedelta(days=2),
                       "n_hist_p1": rng.integers(10, 200, n), "n_hist_p2": rng.integers(10, 200, n),
                       "split": np.where(np.arange(n) < n * .8, "backtest", "live")})
    if leak == "orientation":   # backtest player1 = winner most of the time; model learned it
        bt = df["split"] == "backtest"
        flip = bt & (df["won"] == 0) & (rng.random(n) < 0.7)
        df.loc[flip, "won"] = 1
        df.loc[flip, "model_prob"] = 1 - df.loc[flip, "model_prob"]
        df.loc[bt, "model_prob"] = np.clip(0.5 + 0.35 * (df.loc[bt, "model_prob"] - 0.5) + 0.06, .02, .98)
    if leak == "future":        # serve stat includes the match result; stamped at match time
        df["f_serve_form"] = df["f_serve_form"] + 0.06 * (df["won"] - 0.5)
        df.loc[df.index % 5 == 0, "f_asof"] = df["date"]
    if leak == "swap":          # one tournament has players swapped
        m = df["tournament"] == "T3"
        df.loc[m, "model_prob"] = 1 - df.loc[m, "model_prob"]
    if leak == "skew":          # live features built differently -> live model degrades
        lv = df["split"] == "live"
        df.loc[lv, "f_serve_form"] = df.loc[lv, "f_serve_form"] - 0.05
        df.loc[lv, "model_prob"] = np.clip(0.5 + 0.3 * (df.loc[lv, "model_prob"] - 0.5) + rng.normal(0, .12, lv.sum()), .02, .98)
    return df


def selftest():
    global HISTORY_FILE
    HISTORY_FILE = "_selftest_history.csv"
    expect = {
        None: {},
        "orientation": {"Orientation leak": FAIL, "Hidden-answer signature": FAIL},
        "future": {"Future data": FAIL, "Leaky features": FAIL},
        "swap": {"Backwards segments": FAIL},
        "skew": {"Backtest vs live skew": FAIL},
    }
    ok = True
    for leak, want in expect.items():
        R = run(synth(leak=leak), quiet=True)
        got = {}
        for s, name, _, _ in R.items:
            got[name] = FAIL if FAIL in (got.get(name), s) else s
        fails = {k for k, v in got.items() if v == FAIL}
        if leak is None:
            good = not fails
            print(f"clean data       -> {'no FAILs' if good else 'unexpected FAILs: ' + str(fails)}")
        else:
            missing = {k for k, v in want.items() if got.get(k) != v}
            good = not missing
            print(f"planted {leak:<9}-> {'caught' if good else 'MISSED ' + str(missing)} (FAILs: {sorted(fails)})")
        ok &= good
    if os.path.exists(HISTORY_FILE):
        os.remove(HISTORY_FILE)
    print("selftest passed" if ok else "SELFTEST FAILED")
    return ok


def main():
    ap = argparse.ArgumentParser(description="Guardrail checks for a tennis win-probability model.")
    ap.add_argument("csv", nargs="?")
    ap.add_argument("--tag", help="version label; saves a summary to guard_history.csv for change tracking")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        sys.exit(0 if selftest() else 1)
    if not a.csv:
        ap.print_help()
        return
    df = load(a.csv)
    print(f"Loaded {len(df)} matches from {a.csv}  (splits: {dict(df['split'].value_counts())})")
    R = run(df, tag=a.tag)
    sys.exit(1 if any(i[0] == FAIL for i in R.items) else 0)


if __name__ == "__main__":
    main()
