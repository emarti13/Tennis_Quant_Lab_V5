"""In-play Kalshi tennis trading hypotheses (research, 2026-10-20).

Usage: python run_inplay.py [--raw DIR]   (writes results.json next to this file)

Nothing from matches starting 2026-10-13 or later is used. The planned split (train < 2026-09-10,
test 2026-09-10..10-12) is empty: the raw files hold no pre-sealed matches after 2026-09-02. So a
rolling chronological split by thirds of match starts is used: fold 1 trains on third 1 and tests
on third 2; fold 2 trains on thirds 1-2 and tests on third 3. "train"/"test" in the simple-rule
tables = third 1 / thirds 2-3. Unit for resampling: the match (event_ticker).
Look-ahead rules: a decision at minute t uses only bars ending at or before t; entries execute at
the standing quote of bar t+1 (one-minute delay); exits triggered at bar k execute at bar k+1.
Execution for the simple rules and the model rules is on ONE canonical ticker per event (YES = buy
at its ask, the other player = buy NO at 1 - its bid), so a match is never counted twice.
"""
from __future__ import annotations

import argparse
import json
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path("/home/user/Tennis_Quant_Lab_V5")
sys.path.insert(0, str(BASE))
from v5_devig import kalshi_fee  # noqa: E402
from v5_kalshi_history import rebuild_fixture_map  # noqa: E402
from scripts.simulate_kalshi_making import load_raw  # noqa: E402

HERE = Path(__file__).resolve().parent
SCRATCH = HERE.parents[1]
SEALED_FROM = pd.Timestamp("2026-10-13", tz="UTC")
TEST_FROM = None  # set in main(): start of third 2
PRE_MIN = 60          # minutes of grid kept before the start
STALE_MAX = 10        # minutes a forward-filled quote may be old to be used
BOOT = 2000
RNG = np.random.default_rng(20261020)
FAMILIES = ["ATP", "CHALLENGER", "WTA", "WTA125"]


def fee(p):
    """Per-contract taker fee for a 100-contract order (v5_devig.kalshi_fee(p, 100) / 100), vectorised."""
    p = np.asarray(p, dtype=float)
    return np.ceil(0.07 * 100 * p * (1 - p) * 100 - 1e-9) / 100 / 100


assert abs(fee(0.37) - kalshi_fee(0.37, 100) / 100) < 1e-12 and abs(fee(0.91) - kalshi_fee(0.91, 100) / 100) < 1e-12


# ----------------------------------------------------------------------------- data
def load_markets(raw_dir: Path) -> list[dict]:
    cache = HERE / "raw_loaded.pkl"
    if cache.exists():
        raw = pickle.load(open(cache, "rb"))
    else:
        raw = load_raw(raw_dir)
        pickle.dump(raw, open(cache, "wb"))
    mk = pd.concat([pd.read_csv(p, dtype=str, keep_default_na=False)
                    for p in sorted((BASE / "market_history" / "kalshi" / "markets").glob("*.csv"))]).drop_duplicates("ticker")
    reg = pd.read_csv(BASE / "oddspapi_registry" / "fixtures.csv", dtype=str, keep_default_na=False)
    fmap = rebuild_fixture_map(mk, reg)   # same mapping as scripts/measure_inplay_calibration.samples()
    fmap = fmap[fmap["match_method"] == "names"].merge(mk[["ticker", "family"]], on="ticker")
    starts = reg.drop_duplicates("fixture_id").set_index("fixture_id")["true_start_time_utc"]
    out = []
    for r in fmap.itertuples():
        m = raw.get(r.ticker)
        if m is None or m["result"] not in ("yes", "no") or r.fixture_id not in starts.index or not starts[r.fixture_id]:
            continue
        start = pd.Timestamp(starts[r.fixture_id])
        if start >= SEALED_FROM:
            continue
        c = [(pd.Timestamp(t), b, a) for t, b, a in m["candles"] if b is not None and a is not None and 0 < b < a < 1]
        if not c:
            continue
        df = pd.DataFrame(c, columns=["t", "bid", "ask"]).drop_duplicates("t", keep="last").set_index("t").sort_index()
        s0 = start.ceil("min")
        grid = pd.date_range(s0 - pd.Timedelta(minutes=PRE_MIN), df.index.max(), freq="min")
        if len(grid) <= PRE_MIN + 5:
            continue
        df["age_t"] = df.index
        g = df.reindex(grid, method="ffill")
        age = ((grid - pd.DatetimeIndex(g["age_t"])).total_seconds() / 60).to_numpy()
        bid, ask = g["bid"].to_numpy(float), g["ask"].to_numpy(float)
        ok = np.isfinite(bid) & (age <= STALE_MAX)
        mid = (bid + ask) / 2
        # pre-match mid: standing quote 1 minute before the start (spread <= 10c, as in the calibration study)
        pre_t = start - pd.Timedelta(minutes=1)
        pre = df[df.index <= pre_t]
        pre = pre[(pre["ask"] - pre["bid"]) <= 0.10]
        if pre.empty:
            continue
        pre_mid = float((pre["bid"].iloc[-1] + pre["ask"].iloc[-1]) / 2)
        i0 = PRE_MIN
        live = np.where(ok[i0:] & ((mid[i0:] <= 0.02) | (mid[i0:] >= 0.98)))[0]
        iend = i0 + (int(live[0]) if len(live) else len(grid) - 1 - i0)   # first bar at 2c/98c (exclusive for decisions)
        if iend - i0 < 4:
            continue
        out.append({"ticker": r.ticker, "event": r.event_ticker, "family": r.family, "start": start,
                    "won": 1 if m["result"] == "yes" else 0, "pre_mid": pre_mid, "bid": bid, "ask": ask,
                    "mid": mid, "ok": ok, "i0": i0, "iend": iend})
    # canonical ticker per event: the alphabetically first one
    seen = {}
    for m in sorted(out, key=lambda x: x["ticker"]):
        seen.setdefault(m["event"], m["ticker"])
    for m in out:
        m["canon"] = seen[m["event"]] == m["ticker"]
    return out


def features(m: dict, step: int = 2) -> pd.DataFrame:
    mid, bid, ask, ok, i0, iend = m["mid"], m["bid"], m["ask"], m["ok"], m["i0"], m["iend"]
    n = len(mid)
    midf = pd.Series(np.where(ok, mid, np.nan)).ffill().to_numpy()
    rows = []
    d1 = np.diff(midf, prepend=np.nan)
    d2arr = midf - np.roll(midf, 2)
    jump = np.zeros(n)
    jump[i0 + 2:] = (np.abs(d2arr[i0 + 2:]) >= 0.08)
    cj = np.cumsum(jump)
    for t in range(i0, iend, step):
        if t + 1 >= n or not ok[t] or (ask[t] - bid[t]) > 0.10 or not ok[t + 1]:
            continue
        seg = midf[i0:t + 1]
        r15 = d1[t - 14:t + 1]
        rows.append({"ticker": m["ticker"], "event": m["event"], "family": m["family"], "start": m["start"], "t": t,
                     "minute": t - i0, "mid": mid[t], "spread": ask[t] - bid[t], "pre_mid": m["pre_mid"],
                     "d2": midf[t] - midf[t - 2], "d5": midf[t] - midf[t - 5], "d15": midf[t] - midf[t - 15],
                     "d30": midf[t] - midf[t - 30], "mx": np.nanmax(seg), "mn": np.nanmin(seg),
                     "rv15": np.nanstd(r15), "jumps": cj[t],
                     "ask_next": ask[t + 1], "bid_next": bid[t + 1], "won": m["won"], "canon": m["canon"]})
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------- stats
def boot_ret(ev: np.ndarray, pnl: np.ndarray, cost: np.ndarray) -> list[float]:
    """95% range of sum(pnl)/sum(cost), resampling events."""
    u, inv = np.unique(ev, return_inverse=True)
    sp, sc = np.bincount(inv, pnl, len(u)), np.bincount(inv, cost, len(u))
    idx = RNG.integers(0, len(u), (BOOT, len(u)))
    r = sp[idx].sum(1) / sc[idx].sum(1)
    return [round(float(np.percentile(r, 2.5)), 4), round(float(np.percentile(r, 97.5)), 4)]


def summarize(tr: pd.DataFrame) -> dict:
    """tr: event, family, entry_time, pnl, cost (per contract)."""
    if len(tr) == 0:
        return {"n_trades": 0}
    tr = tr.sort_values("entry_time")
    ret = tr["pnl"] / tr["cost"]
    cum = ret.cumsum().to_numpy()
    dd = float(np.max(np.maximum.accumulate(np.r_[0, cum])[1:] - cum)) if len(cum) else 0.0
    out = {"n_trades": int(len(tr)), "n_matches": int(tr["event"].nunique()),
           "avg_cost": round(float(tr["cost"].mean()), 3),
           "ret_per_dollar": round(float(tr["pnl"].sum() / tr["cost"].sum()), 4),
           "ci95": boot_ret(tr["event"].to_numpy(), tr["pnl"].to_numpy(), tr["cost"].to_numpy()) if tr["event"].nunique() >= 10 else None,
           "max_drawdown_stakes": round(dd, 2), "total_stakes_won": round(float(cum[-1]), 2)}
    fam = {}
    for f, g in tr.groupby("family"):
        if g["event"].nunique() >= 10:
            fam[f] = {"n": int(g["event"].nunique()), "ret": round(float(g["pnl"].sum() / g["cost"].sum()), 4),
                      "ci95": boot_ret(g["event"].to_numpy(), g["pnl"].to_numpy(), g["cost"].to_numpy())}
    out["by_family"] = fam
    return out


def logloss(y, p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def boot_diff(ev, a, b):
    """95% range of mean(a - b), resampling events."""
    u, inv = np.unique(ev, return_inverse=True)
    s, c = np.bincount(inv, a - b, len(u)), np.bincount(inv, None, len(u))
    idx = RNG.integers(0, len(u), (BOOT, len(u)))
    r = s[idx].sum(1) / c[idx].sum(1)
    return [round(float(np.percentile(r, 2.5)), 5), round(float(np.percentile(r, 97.5)), 5)]


# ----------------------------------------------------------------------------- models
def design(d: pd.DataFrame) -> pd.DataFrame:
    lg = lambda x: np.log(np.clip(x, 0.01, 0.99) / (1 - np.clip(x, 0.01, 0.99)))
    X = pd.DataFrame({"lmid": lg(d["mid"]), "lpre": lg(d["pre_mid"]), "spread": d["spread"],
                      "minute": d["minute"] / 60, "d2": d["d2"], "d5": d["d5"], "d15": d["d15"], "d30": d["d30"],
                      "lmx": lg(d["mx"]), "lmn": lg(d["mn"]), "rv15": d["rv15"], "jumps": d["jumps"]})
    for f in FAMILIES:
        X["fam_" + f] = (d["family"] == f).astype(float)
        X["lmid_x_" + f] = X["lmid"] * X["fam_" + f]
    X["lmid_x_min"] = X["lmid"] * X["minute"]
    X["lmid_x_lpre"] = X["lmid"] * X["lpre"]
    return X.fillna(0.0)


def fit_models(train: pd.DataFrame, test: pd.DataFrame) -> tuple[dict, dict]:
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    import lightgbm as lgb
    # time-held-out slice: the last 20% of train matches by start
    ev_start = train.groupby("event")["start"].min().sort_values()
    cut = ev_start.iloc[int(len(ev_start) * 0.8)]
    fit, val = train[train["start"] < cut], train[train["start"] >= cut]
    Xf, Xv, Xa, Xt = design(fit), design(val), design(train), design(test)
    info = {"holdout_cut": str(cut), "fit_rows": len(fit), "val_rows": len(val)}
    # (b) L2 logistic: choose C on the held-out slice, refit on all train
    best = None
    for C in [0.001, 0.01, 0.1, 1.0, 10.0]:
        sc = StandardScaler().fit(Xf)
        lr = LogisticRegression(C=C, max_iter=2000).fit(sc.transform(Xf), fit["won"])
        ll = logloss(val["won"].to_numpy(), lr.predict_proba(sc.transform(Xv))[:, 1]).mean()
        if best is None or ll < best[0]:
            best = (ll, C)
    info["logit_C"] = best[1]
    sc = StandardScaler().fit(Xa)
    lr = LogisticRegression(C=best[1], max_iter=2000).fit(sc.transform(Xa), train["won"])
    p_lr = lr.predict_proba(sc.transform(Xt))[:, 1]
    info["logit_coef"] = {k: round(float(v), 4) for k, v in zip(Xa.columns, lr.coef_[0])}
    # (c) LightGBM depth 3, lr 0.05, up to 500 rounds, early stopping on the held-out slice
    params = {"objective": "binary", "learning_rate": 0.05, "max_depth": 3, "num_leaves": 8,
              "min_data_in_leaf": 200, "feature_fraction": 0.8, "bagging_fraction": 0.8, "bagging_freq": 1,
              "lambda_l2": 1.0, "verbose": -1, "seed": 7}
    dtr = lgb.Dataset(Xf, fit["won"])
    dva = lgb.Dataset(Xv, val["won"], reference=dtr)
    bst = lgb.train(params, dtr, 500, valid_sets=[dva], callbacks=[lgb.early_stopping(30, verbose=False)])
    nbest = max(bst.best_iteration, 10)
    info["gbm_best_iter"] = int(nbest)
    bst = lgb.train(params, lgb.Dataset(Xa, train["won"]), nbest)
    p_gb = bst.predict(Xt)
    # (b') numpy L2 logistic with logit(mid) as a fixed offset (penalty only on the corrections)
    def off_fit(X, y, off, lam):
        mu, sd = X.mean(0), X.std(0) + 1e-9
        Z = np.c_[np.ones(len(X)), (X - mu) / sd]
        w = np.zeros(Z.shape[1])
        P = np.eye(Z.shape[1]) * lam; P[0, 0] = 0
        for _ in range(25):
            pr = 1 / (1 + np.exp(-(off + Z @ w)))
            g = Z.T @ (pr - y) + P @ w
            H = (Z * (pr * (1 - pr))[:, None]).T @ Z + P
            step = np.linalg.solve(H, g)
            w -= step
            if np.abs(step).max() < 1e-7:
                break
        return lambda Xn, on: 1 / (1 + np.exp(-(on + np.c_[np.ones(len(Xn)), (Xn - mu) / sd] @ w)))
    cols = [c for c in Xa.columns if c != "lmid"]
    best = None
    for lam in [1.0, 10.0, 100.0, 1000.0, 10000.0]:
        f = off_fit(Xf[cols].to_numpy(), fit["won"].to_numpy(), Xf["lmid"].to_numpy(), lam)
        ll = logloss(val["won"].to_numpy(), f(Xv[cols].to_numpy(), Xv["lmid"].to_numpy())).mean()
        if best is None or ll < best[0]:
            best = (ll, lam)
    info["logit_offset_lambda"] = best[1]
    f = off_fit(Xa[cols].to_numpy(), train["won"].to_numpy(), Xa["lmid"].to_numpy(), best[1])
    p_lo = f(Xt[cols].to_numpy(), Xt["lmid"].to_numpy())
    # (c') LightGBM boosting the residual from logit(mid) (init_score), same settings
    dtr = lgb.Dataset(Xf, fit["won"], init_score=Xf["lmid"])
    dva = lgb.Dataset(Xv, val["won"], init_score=Xv["lmid"], reference=dtr)
    b2 = lgb.train(params, dtr, 500, valid_sets=[dva], callbacks=[lgb.early_stopping(30, verbose=False)])
    n2 = max(b2.best_iteration, 1)
    info["gbm_offset_best_iter"] = int(n2)
    b2 = lgb.train(params, lgb.Dataset(Xa, train["won"], init_score=Xa["lmid"]), n2)
    p_go = 1 / (1 + np.exp(-(b2.predict(Xt, raw_score=True) + Xt["lmid"].to_numpy())))
    # baseline on the held-out slice too (sanity)
    info["val_ll_mid"] = round(float(logloss(val["won"].to_numpy(), val["mid"].to_numpy()).mean()), 5)
    info["gbm_importance"] = dict(sorted(zip(Xa.columns, map(int, bst.feature_importance("gain"))), key=lambda kv: -kv[1])[:8])
    return {"mid": test["mid"].to_numpy(), "logit": p_lr, "gbm": p_gb, "logit_offset": p_lo, "gbm_offset": p_go}, info


# ----------------------------------------------------------------------------- trades
def take_entry(m: dict, ts: int, side: str) -> tuple[float, float] | None:
    """Price/fee buying `side` (yes/no) at the standing quote of bar ts."""
    if ts >= len(m["mid"]) or not m["ok"][ts]:
        return None
    p = m["ask"][ts] if side == "yes" else 1 - m["bid"][ts]
    return p, float(fee(p))


def pos_bid(m, k, side):
    return m["bid"][k] if side == "yes" else 1 - m["ask"][k]


def settle(m: dict, te: int, side: str, entry: float, efee: float, hold: int | None = None, tp: float | None = None) -> float:
    """Per-contract P&L. Time exit after `hold` minutes (sell at the bid), or take-profit when the
    position's bid at bar k >= entry + tp (sell at bar k+1's bid), else hold to the result."""
    win = m["won"] if side == "yes" else 1 - m["won"]
    end = m["iend"]
    if hold is not None:
        k = te + hold
        if k < end and m["ok"][k]:
            b = pos_bid(m, k, side)
            return b - float(fee(b)) - entry - efee
        return win - entry - efee
    if tp is not None:
        for k in range(te, end):
            if m["ok"][k] and pos_bid(m, k, side) >= entry + tp and k + 1 < len(m["mid"]) and m["ok"][k + 1]:
                b = pos_bid(m, k + 1, side)
                return b - float(fee(b)) - entry - efee
    return win - entry - efee


def run_rule(mkts: list[dict], signal, exits: dict) -> dict[str, pd.DataFrame]:
    """signal(m, t) -> 'yes'/'no'/None using bars <= t. First signal per side per match; entry at t+1."""
    res = {k: [] for k in exits}
    for m in mkts:
        done = set()
        for t in range(m["i0"], m["iend"]):
            if not m["ok"][t] or m["ask"][t] - m["bid"][t] > 0.10:
                continue
            s = signal(m, t)
            if s is None or s in done:
                continue
            e = take_entry(m, t + 1, s)
            if e is None:
                continue
            done.add(s)
            for k, kw in exits.items():
                pnl = settle(m, t + 1, s, e[0], e[1], **kw)
                res[k].append({"event": m["event"], "family": m["family"], "start": m["start"],
                               "entry_time": m["start"] + pd.Timedelta(minutes=t + 1 - m["i0"]),
                               "pnl": pnl, "cost": e[0] + e[1]})
            if len(done) == 2:
                break
    return {k: pd.DataFrame(v) for k, v in res.items()}


def split_summ(tr: pd.DataFrame) -> dict:
    global TEST_FROM
    if len(tr) == 0:
        return {"all": {"n_trades": 0}}
    return {"all": summarize(tr), "train": summarize(tr[tr["start"] < TEST_FROM]), "test": summarize(tr[tr["start"] >= TEST_FROM])}


def maker_rule(mkts, signal, window=5, strict=False) -> pd.DataFrame:
    """Post at the bid of bar t+1 (no fee); filled if the ask of a bar in t+2..t+1+window is <= our price
    (strict: < our price). Hold to the result. The first signal per side, filled or not, is the only try."""
    rows = []
    for m in mkts:
        done = set()
        for t in range(m["i0"], m["iend"]):
            if not m["ok"][t] or m["ask"][t] - m["bid"][t] > 0.10:
                continue
            s = signal(m, t)
            if s is None or s in done or t + 1 >= len(m["mid"]) or not m["ok"][t + 1]:
                continue
            done.add(s)
            price = m["bid"][t + 1] if s == "yes" else 1 - m["ask"][t + 1]
            for k in range(t + 2, min(t + 2 + window, len(m["mid"]))):
                if not m["ok"][k]:
                    continue
                pa = m["ask"][k] if s == "yes" else 1 - m["bid"][k]
                if (pa < price) if strict else (pa <= price):
                    win = m["won"] if s == "yes" else 1 - m["won"]
                    rows.append({"event": m["event"], "family": m["family"], "start": m["start"],
                                 "entry_time": m["start"] + pd.Timedelta(minutes=k - m["i0"]), "pnl": win - price, "cost": price})
                    break
            if len(done) == 2:
                break
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default=str(SCRATCH / "kraw"))
    args = ap.parse_args()
    mk = load_markets(Path(args.raw))
    canon = [m for m in mk if m["canon"]]
    global TEST_FROM
    st = sorted(m["start"] for m in canon)
    cut1, cut2 = st[len(st) // 3], st[2 * len(st) // 3]
    TEST_FROM = cut1
    rep = {"markets": len(mk), "events": len(canon), "first_start": str(st[0]), "last_start": str(st[-1]),
           "split": "rolling thirds (planned 2026-09-10 split empty: no pre-sealed data after 2026-09-02)",
           "cut1": str(cut1), "cut2": str(cut2)}
    print(rep, flush=True)

    # ---- 1. dataset and calibration models
    d = pd.concat([features(m) for m in mk], ignore_index=True)
    d.to_pickle(HERE / "dataset.pkl")
    rep["dataset"] = {"rows": len(d)}
    parts, rep["model_info"] = [], {}
    for fold, (a, b) in enumerate([(cut1, cut2), (cut2, None)], 1):
        train = d[d["start"] < a].reset_index(drop=True)
        test = d[(d["start"] >= a) & ((d["start"] < b) if b is not None else True)].reset_index(drop=True)
        preds, info = fit_models(train, test)
        info.update({"train_rows": len(train), "test_rows": len(test), "test_events": int(test["event"].nunique())})
        rep["model_info"][f"fold{fold}"] = info
        for k, v in preds.items():
            test["p_" + k] = v
        test["fold"] = fold
        parts.append(test)
    test = pd.concat(parts, ignore_index=True)
    preds = {k: test["p_" + k].to_numpy() for k in ("mid", "logit", "gbm", "logit_offset", "gbm_offset")}
    ev_mask = test["canon"].to_numpy()          # evaluate on one ticker per event
    y = test["won"].to_numpy()[ev_mask]
    ev = test["event"].to_numpy()[ev_mask]
    ll = {k: logloss(y, v[ev_mask]) for k, v in preds.items()}
    rep["calibration"] = {"test_rows_one_ticker_per_event": int(ev_mask.sum()), "test_events": int(len(np.unique(ev)))}
    fo = test["fold"].to_numpy()[ev_mask]
    for k in ll:
        rep["calibration"][k] = {"log_loss": round(float(ll[k].mean()), 5),
                                 "by_fold": [round(float(ll[k][fo == f].mean()), 5) for f in (1, 2)]}
        if k != "mid":
            rep["calibration"][k]["minus_mid"] = round(float((ll[k] - ll["mid"]).mean()), 5)
            rep["calibration"][k]["minus_mid_ci95"] = boot_diff(ev, ll[k], ll["mid"])
    fam_t = test["family"].to_numpy()[ev_mask]
    rep["calibration_by_family"] = {f: {k: round(float(ll[k][fam_t == f].mean()), 5) for k in ll} for f in FAMILIES if (fam_t == f).sum()}
    print(json.dumps(rep["calibration"], indent=1), flush=True)

    # ---- 2. model trading rules on test (canonical ticker; both sides)
    tc = test[test["canon"]].copy()
    rep["model_trading"] = {}
    for k in ("logit", "gbm", "logit_offset", "gbm_offset"):
        for margin in (0.0, 0.02, 0.04):
            rows = []
            for e, g in tc.sort_values("t").groupby("event"):
                for side in ("yes", "no"):
                    if side == "yes":
                        price = g["ask_next"].to_numpy(); prob = g["p_" + k].to_numpy(); win = g["won"].iloc[0]
                    else:
                        price = 1 - g["bid_next"].to_numpy(); prob = 1 - g["p_" + k].to_numpy(); win = 1 - g["won"].iloc[0]
                    edge = prob - price - fee(price)
                    hit = np.where(edge > margin)[0]
                    if len(hit):
                        i = hit[0]; c = price[i] + fee(price[i])
                        rows.append({"event": e, "family": g["family"].iloc[0], "start": g["start"].iloc[0],
                                     "entry_time": g["start"].iloc[0] + pd.Timedelta(minutes=int(g["minute"].iloc[i]) + 1),
                                     "pnl": win - c, "cost": c})
            rep["model_trading"][f"{k}_margin{int(margin*100)}c"] = summarize(pd.DataFrame(rows))
    print(json.dumps(rep["model_trading"], indent=1), flush=True)

    # ---- 3. simple rules (canonical ticker; 1-minute decisions)
    def fade(m, t):
        x = m["mid"][t]
        return "no" if 0.70 <= x <= 0.90 else ("yes" if 0.10 <= x <= 0.30 else None)

    def mom(direction):
        def f(m, t):
            if t - 5 < 0 or not m["ok"][t - 5]:
                return None
            dlt = m["mid"][t] - m["mid"][t - 5]
            if abs(dlt) < 0.08:
                return None
            up = dlt > 0
            return ("yes" if up else "no") if direction == "with" else ("no" if up else "yes")
        return f

    def reversal(m, t):
        x, p = m["mid"][t], m["pre_mid"]
        if p > 0.5 and x < 0.45:
            return "yes"
        if p < 0.5 and x > 0.55:
            return "no"
        return None

    def fade_atp_wta(m, t):
        return fade(m, t) if m["family"] in ("ATP", "WTA") else None

    hold_tp = {"hold": {}, "tp5": {"tp": 0.05}, "tp10": {"tp": 0.10}, "tp20": {"tp": 0.20}}
    rules = {"fade_fav_70_90": (fade, hold_tp), "fade_fav_70_90_ATP_WTA": (fade_atp_wta, hold_tp),
             "momentum_with": (mom("with"), {"exit10": {"hold": 10}, "exit20": {"hold": 20}, "hold": {}, "tp10": {"tp": 0.10}}),
             "momentum_against": (mom("against"), {"exit10": {"hold": 10}, "exit20": {"hold": 20}, "hold": {}, "tp10": {"tp": 0.10}}),
             "prematch_fav_below45": (reversal, hold_tp)}
    rep["simple_rules"] = {}
    for name, (sig, ex) in rules.items():
        out = run_rule(canon, sig, ex)
        rep["simple_rules"][name] = {k: split_summ(v) for k, v in out.items()}
        print(name, {k: (v["all"].get("ret_per_dollar"), v["all"].get("ci95")) for k, v in rep["simple_rules"][name].items()}, flush=True)

    # ---- 4. maker variant of the best simple rule, chosen on TRAIN return only
    best = max(((n, k) for n in rep["simple_rules"] for k in rep["simple_rules"][n] if k in ("hold",)),
               key=lambda nk: rep["simple_rules"][nk[0]][nk[1]]["train"].get("ret_per_dollar", -9))
    rep["maker"] = {"rule": best[0], "chosen_on": "train hold-to-result return"}
    for strict in (False, True):
        tr = maker_rule(canon, rules[best[0]][0], strict=strict)
        rep["maker"]["strict" if strict else "touch"] = split_summ(tr)
    # fill rate: signals with the same rule (taker hold count)
    rep["maker"]["taker_signals_all"] = rep["simple_rules"][best[0]]["hold"]["all"]["n_trades"]
    print(json.dumps(rep["maker"], indent=1), flush=True)
    (HERE / "results.json").write_text(json.dumps(rep, indent=1, default=str) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
