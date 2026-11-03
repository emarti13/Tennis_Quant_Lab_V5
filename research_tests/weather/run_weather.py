"""Heat and wind matched to the player: does the price miss who suffers in the conditions?

Usage:  python research_tests/weather/run_weather.py JOINED_PKL HISTORY_DIR EVENTS_CSV WEATHER_DIR OUT_JSON
        (WEATHER_DIR from research_tests/weather/fetch_meteostat.py)

Pre-registered 2026-11-03, before any result was seen. Prices treat a 38-degree humid afternoon like a
cool evening. Conditions at the match's start hour at the tournament's location,
outdoor matches only (the history file's indoor flag must say outdoors: ATP main and part of the
Challengers; WTA has no flag and is left out):

  hot        feels-like temperature at the start hour 32 C or more (NOAA heat index from the nearest
             Meteostat station's temperature and humidity; Open-Meteo's archive refused the volume)
  windy      wind speed at the start hour 25 km/h or more
  Player attributes from public data before the event: age, height (history file), ace rate per
  service point over all earlier events (tourney date strictly before this event's), shrunk toward
  0.08 with 500 service points.
  Features: hot x (age A - age B) / 5;  hot x (height A - height B) / 10 cm;  windy x (ace rate A - B) x 10.

  SET       ATP main and Challenger outdoor matches with odds, 2016-2025; walk-forward, test 2022-2025.
  PRIMARY   M0 = logistic on logit(Betfair close); M1 = M0 + the three interactions (L2): log loss
            M1 - M0 on 2022-2025, 95% range resampling matches.
  SECONDARY older player (5+ years) in heat, taller player (10+ cm) in heat, bigger server (ace rate
            +0.03) in wind: that player's result minus Betfair close, 2016-2025 and 2016-2021; money on
            2022-2025 for any beyond 2 points in 2016-2021.
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
BOOKS = {"bf_close": ("bf_w", "bf_l"), "b365_close": ("b365_w", "b365_l")}
COMMISSION = {"bf_close": 0.02, "b365_close": 0.0}
COLS = ["d_hot_age", "d_hot_ht", "d_wind_ace"]


def attributes(hist_dir: Path) -> pd.DataFrame:
    """Per (tourney_id, round, winner, loser): both players' age, height, prior ace rate, and the indoor flag."""
    h = pd.concat([pd.read_csv(hist_dir / f, low_memory=False) for f in ("ATP.csv", "Challenger.csv")], ignore_index=True)
    h["date"] = pd.to_datetime(h["tourney_date"].astype(str).str[:8], format="%Y%m%d", errors="coerce")
    rows = pd.concat([pd.DataFrame({"tid": h["tourney_id"], "date": h["date"], "name": h[f"{s}_name"],
                                    "ace": pd.to_numeric(h[f"{p}_ace"], errors="coerce"), "svpt": pd.to_numeric(h[f"{p}_svpt"], errors="coerce")})
                      for s, p in (("winner", "w"), ("loser", "l"))], ignore_index=True).dropna(subset=["date"])
    ev = rows.groupby(["name", "tid", "date"])[["ace", "svpt"]].sum().reset_index().sort_values(["name", "date"])
    g = ev.groupby("name")
    ev["cum_ace"] = g["ace"].cumsum() - ev["ace"]                      # earlier events only
    ev["cum_svpt"] = g["svpt"].cumsum() - ev["svpt"]
    ev["ace_rate"] = (ev["cum_ace"] + 500 * 0.08) / (ev["cum_svpt"] + 500)
    # one value per (player, event): the same event id can appear on two dates (e.g. a qualifying week)
    rate = ev.drop_duplicates(["name", "tid"]).set_index(["name", "tid"])["ace_rate"].to_dict()
    out = pd.DataFrame({"tid": h["tourney_id"], "round": h["round"], "w": h["winner_name"], "l": h["loser_name"],
                        "indoor": h["indoor"], "age_w": h["winner_age"], "age_l": h["loser_age"], "ht_w": h["winner_ht"], "ht_l": h["loser_ht"]})
    out["ace_w"] = [rate.get((n, t), np.nan) for n, t in zip(out["w"], out["tid"])]
    out["ace_l"] = [rate.get((n, t), np.nan) for n, t in zip(out["l"], out["tid"])]
    return out.drop_duplicates(["tid", "round", "w", "l"])


def conditions(j: pd.DataFrame, events: pd.DataFrame, wdir: Path) -> pd.DataFrame:
    loc = events.set_index("tournament")[["latitude", "longitude"]].round(1)
    j = j.copy()
    j["utc"] = (pd.to_datetime(j["match_date_formatted"], errors="coerce") - pd.Timedelta(hours=9)).dt.floor("h")
    j = j.join(loc, on="tournament")
    out = []
    for (lat, lon), g in j.dropna(subset=["latitude", "utc"]).groupby(["latitude", "longitude"]):
        f = wdir / f"{lat:.1f}_{lon:.1f}.csv"                     # fetch_meteostat.py output (match days only)
        if not f.exists():
            continue
        w = pd.read_csv(f)
        w["time"] = pd.to_datetime(w["time"])
        w = w.drop_duplicates("time").set_index("time")
        t = g["utc"]
        out.append(pd.DataFrame({"match_key": g["match_key"].values,
                                 "app_temp": w["app_temp"].reindex(t).to_numpy(),
                                 "wind": w["wind_kmh"].reindex(t).to_numpy()}))
    return pd.concat(out, ignore_index=True)


def build(joined: pd.DataFrame, attrs: pd.DataFrame, cond: pd.DataFrame) -> pd.DataFrame:
    j = joined.merge(attrs, left_on=["tid", "wh_round", "winner_name", "loser_name"], right_on=["tid", "round", "w", "l"], how="inner")
    j = j.merge(cond, on="match_key", how="inner")
    j = j[(j["indoor"] == "O") & j["app_temp"].notna()].sort_values("match_key", kind="stable")
    flip = j["flip"].to_numpy(bool)
    out = pd.DataFrame({"match_key": j["match_key"].values, "year": pd.to_datetime(j["wh_date"]).dt.year.values, "level": j["odds_level"].values,
                        "y": (~flip).astype(int), "hot": (j["app_temp"] >= 32).astype(int).values, "windy": (j["wind"] >= 25).astype(int).values})
    for c in ("age", "ht", "ace"):
        a, b = orient(pd.to_numeric(j[f"{c}_w"], errors="coerce").to_numpy(), pd.to_numeric(j[f"{c}_l"], errors="coerce").to_numpy(), flip)
        out[f"a_{c}"], out[f"b_{c}"] = a, b
    out["d_hot_age"] = (out["hot"] * (out["a_age"] - out["b_age"]) / 5).fillna(0)
    out["d_hot_ht"] = (out["hot"] * (out["a_ht"] - out["b_ht"]) / 10).fillna(0)
    out["d_wind_ace"] = (out["windy"] * (out["a_ace"] - out["b_ace"]) * 10).fillna(0)
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


def side_report(df, mask_a, mask_b, label, test, R):
    """Residual from the side of the player selected by mask (A where mask_a, B where mask_b)."""
    y = df["y"].to_numpy()
    early = (df["year"] < 2022).to_numpy()
    resid = np.where(mask_a, y - df["p_bf_close"], np.where(mask_b, (1 - y) - (1 - df["p_bf_close"]), np.nan))
    ra, re = resid[np.isfinite(resid)], resid[np.isfinite(resid) & early]
    R[label] = {"all": [round(100 * v, 2) for v in boot_mean(ra, seed=SEED)] + [int(len(ra))],
                "2016-21": [round(100 * v, 2) for v in boot_mean(re, seed=SEED)] + [int(len(re))]}
    e = R[label]["2016-21"]
    if len(re) and abs(e[0]) >= 2:
        back_sel = e[0] > 0
        for book in BOOKS:
            sel = test & (mask_a | mask_b) & df[f"p_{book}"].notna().to_numpy()
            x = df[sel]
            a_sel = mask_a[sel]
            back_a = a_sel if back_sel else ~a_sel
            o = np.where(back_a, x[f"oa_{book}"], x[f"ob_{book}"])
            won = np.where(back_a, x["y"] == 1, x["y"] == 0)
            pnl = np.where(won, (o - 1) * (1 - COMMISSION[book]), -1.0)
            m, lo, hi = boot_mean(pnl, seed=SEED)
            R[f"MONEY {label}: back the {'selected' if back_sel else 'other'} player at {book}, 2022-25"] = {"n": int(len(x)), "roi": round(m, 4), "range": [round(lo, 4), round(hi, 4)]}


def swap_source(joined):
    j = joined.copy()
    for a, b in [("winner_name", "loser_name"), *BOOKS.values()]:
        j[a], j[b] = joined[b].values, joined[a].values
    return j.assign(_swapped=1)


def main() -> int:
    joined_pkl, hist_dir, events_csv, wdir, out_json = sys.argv[1], Path(sys.argv[2]), sys.argv[3], Path(sys.argv[4]), sys.argv[5]
    joined = pd.read_pickle(joined_pkl)
    joined = joined[(joined["tour"] == "ATP") & joined["odds_level"].isin(["ATP main", "Challenger"])].reset_index(drop=True)
    joined = joined.assign(match_key=np.arange(len(joined)), flip=coin_flip(len(joined), SEED))
    attrs = attributes(hist_dir)
    cond = conditions(joined, pd.read_csv(events_csv), wdir)
    df = build(joined, attrs, cond)
    df = df[(df["year"] >= 2016) & df["p_bf_close"].notna()].reset_index(drop=True)
    res = {"manifest": provenance.manifest({"joined": joined_pkl, "history": str(hist_dir), "events": events_csv, "weather": str(wdir)},
                                          {"orientation": SEED, "bootstrap": SEED}, " ".join(["python"] + sys.argv)),
           "rows": int(len(df)), "by_level": df["level"].value_counts().to_dict(),
           "hot_share": round(float(df["hot"].mean()), 4), "windy_share": round(float(df["windy"].mean()), 4), "results": {}}
    R = res["results"]
    y = df["y"].to_numpy()
    test = df["year"].isin(TEST_YEARS).to_numpy()
    p0, p1 = fit_predict(df, []), fit_predict(df, COLS)
    m = test & np.isfinite(p1)
    R["PRIMARY M1 (heat x age, heat x height, wind x ace rate) minus M0, Betfair close, 2022-25"] = \
        [round(v, 5) for v in boot_mean(log_loss(y[m], p1[m]) - log_loss(y[m], p0[m]), seed=SEED)] + [int(m.sum())]
    hot = df["hot"].to_numpy() == 1
    windy = df["windy"].to_numpy() == 1
    ga, gh, gc = (df["a_age"] - df["b_age"]).to_numpy(), (df["a_ht"] - df["b_ht"]).to_numpy(), (df["a_ace"] - df["b_ace"]).to_numpy()
    side_report(df, hot & (ga >= 5), hot & (ga <= -5), "older player (5+ yrs) in heat: won minus Betfair close (pts)", test, R)
    side_report(df, hot & (gh >= 10), hot & (gh <= -10), "taller player (10+ cm) in heat: won minus Betfair close (pts)", test, R)
    side_report(df, windy & (gc >= 0.03), windy & (gc <= -0.03), "bigger server (ace rate +0.03) in wind: won minus Betfair close (pts)", test, R)
    side_report(df, ~hot & ~windy & (ga >= 5), ~hot & ~windy & (ga <= -5), "control: older player in mild conditions (pts)", test, R)
    C = {}
    raw = joined[joined["odds_level"] == "ATP main"]
    attrs_sw = attrs.rename(columns={"w": "l", "l": "w", "age_w": "age_l", "age_l": "age_w", "ht_w": "ht_l", "ht_l": "ht_w", "ace_w": "ace_l", "ace_l": "ace_w"})
    C["swap_source"] = checks.swap_source(lambda r, f: build(r.assign(flip=f), attrs_sw if "_swapped" in r else attrs, cond), raw, swap_source,
                                          raw["flip"].to_numpy(bool), COLS + ["p_bf_close", "oa_bf_close", "ob_bf_close"])
    p_mkt = df["p_bf_close"].to_numpy()

    def run(yy, z):
        a0, a1 = fit_predict(df, [], y=yy), fit_predict(df, COLS, y=yy, extra=z)
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
