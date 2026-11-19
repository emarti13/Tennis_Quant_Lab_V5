"""Idea-scout batch 1 (2026-11-03): seven body/schedule flags the closing price may miss.

Usage:  python research_tests/scout/run_scout.py JOINED_PKL CANON_PKL HISTORY_DIR EVENTS_CSV ELEV_CSV OUT_JSON

JOINED_PKL   the Kaggle odds join (2014-2025; tennisexplorer start times in UTC+9; Betfair-labelled
             sportsbook close (bf), bet365 close; first player = winner)
CANON_PKL    v5_fatigue_features.load_repo_matches('.') saved as a pickle: every ATP, ATP qualifying,
             Challenger and WTA match with the leak-free order fields (event start date, stage, round rank)
HISTORY_DIR  .v5_history_cache (for each player's ranking and entry code at the match)
EVENTS_CSV   research_tests/travel/events.csv (tournament -> latitude, longitude)
ELEV_CSV     opentopodata SRTM90m elevation for those coordinates (latitude, longitude, elev_m)

Pre-registered 2026-11-03, before any outcome, residual or price was looked at for these flags (the
idea-scout counted only how often each fires). The user picked ideas 1-5, 7 and 8 of the scout report.
Each flag is per player, from information public before the match; the input is A's minus B's.

  hangover   (1) the player reached the final of the previous event (won or lost) and this event starts
             1-8 days after that final (final day = previous event start + 6, Slams + 13); first match
             of this event only. Slices: champion / runner-up; level up (previous final a Challenger,
             this event ATP main).
  short_rest (2) hours from the end of the player's previous match at this event (its start + minutes)
             to this match's start, from tennisexplorer start times: flag = rest < 18 h and the
             opponent's rest >= 30 h (no earlier match at the event counts as rested). Also the
             capped difference min(rest, 48) A minus B, in units of 24 h (missing rest = 48).
             Check first: share of matches whose start is before the previous match's end (times
             that are scheduled, not actual, would show up here).
  altitude   (3) event at 1400 m or higher and the player played no match at an event 1000 m or higher
             in the previous 21 days; first two matches of the player at the event. Elevations are
             SRTM at the geocoded point; venues the geocoder put on a mountain but which are at sea
             level are set to 0 m by hand before any result (ALT_OVERRIDE below).
  venue      (4) ATP main draw (qualifying is only on file for the men's tour): A entered as a qualifier
             or lucky loser and has already played 2+ matches at the event; B is a direct entrant in
             B's first match of the event who played another event that started 1-14 days earlier.
             Slice: B's previous event was on a different surface.
  layoff     (5) 91+ days since the player's previous match, ranked 1-100 at that previous match, and
             this is one of the first three matches back. Two-sided (direction not assumed). ATP main
             and WTA main only (ITF is not on file, so Challenger-level gaps are not real gaps).
             Slice: entered on a protected ranking (PR).
  surface    (7) the player's first match on this surface (Carpet counts as Hard) after 56+ days without
             one, having played on it before. Also surface x specialist: the flag times
             (surface win rate - overall win rate, both since 2010 and before this event, +2/+4 smoothing).
  freepass   (8) the player's previous match at this event was a win by walkover, or by the opponent
             retiring with at most one set completed (at most two score tokens).

  SET       ATP main, WTA main, Challenger with odds; walk-forward by year from 2016, test 2022-2025.
  PRIMARY   M0 = logistic on logit(close); M1 = M0 + the nine inputs (seven flags, the rest difference,
            surface x specialist), L2 C=0.3: log loss M1 - M0 on 2022-2025, 95% range resampling matches.
  SECONDARY each flag on its own: the flagged player's result minus the close where exactly one side
            has the flag, 2016-25 and 2016-21, 95% range resampling the flagged PLAYERS (clusters), and
            the pre-registered slices; MONEY only for a flag whose 2016-21 residual is beyond 2 points:
            back the indicated side at bf close and bet365 close in 2022-2025 (no commission: both are
            sportsbook prices with their margin in them).
  POWER     the minimum detectable residual (80% power, 5% two-sided) = 2.8 x SE for each flag.
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
FLAGS = ["hangover", "short_rest", "altitude", "venue", "layoff", "surface", "freepass"]
EXTRA = ["rest_diff", "surface_spec"]
SLICES = ["hangover_champ", "hangover_runnerup", "hangover_levelup", "venue_diff_surface", "layoff_pr"]
BOOKS = {"bf_close": ("bf_w", "bf_l"), "b365_close": ("b365_w", "b365_l")}
COMMISSION = {"bf_close": 0.0, "b365_close": 0.0}
# geocoded onto high ground; the tennis venue is at or near sea level (set before any result)
ALT_OVERRIDE = ["Gran Canaria", "Tenerife", "Maui", "Reunion", "Los Cabos", "Santo Domingo", "Montemar"]


# ------------------------------------------------------------------ per-player flags from the canonical history
def history_attrs(hist_dir: Path) -> pd.DataFrame:
    """Ranking and entry code per (raw tourney id, round, winner, loser) and side."""
    frames = []
    for f in ("ATP.csv", "ATPQualifiers.csv", "Challenger.csv", "WTA.csv"):
        d = pd.read_csv(hist_dir / f, low_memory=False, dtype={"tourney_id": str})
        frames.append(d[["tourney_id", "round", "winner_name", "loser_name", "winner_rank", "loser_rank", "winner_entry", "loser_entry"]])
    return pd.concat(frames, ignore_index=True).drop_duplicates(["tourney_id", "round", "winner_name", "loser_name"])


def player_table(canon: pd.DataFrame, attrs: pd.DataFrame) -> pd.DataFrame:
    """One row per (match, player), ordered leak-free: event start date, event, stage, round rank."""
    m = canon[canon["level"].astype(str) != "D"].merge(
        attrs, left_on=["tourney_id_raw", "round", "winner_name", "loser_name"],
        right_on=["tourney_id", "round", "winner_name", "loser_name"], how="left")
    m["surf"] = m["surface"].replace({"Carpet": "Hard"})
    sides = []
    for me, op, won in (("winner", "loser", 1), ("loser", "winner", 0)):
        sides.append(pd.DataFrame({
            "key": m["key"], "tour": m["tour"], "tid": m["tid"], "level": m["level"].astype(str), "surf": m["surf"],
            "date": m["date"], "stage": m["stage"], "rr": m["rank"], "round": m["round"], "best_of": m["best_of"],
            "name": m[f"{me}_name"], "opp": m[f"{op}_name"], "won": won,
            "prank": pd.to_numeric(m[f"{me}_rank"], errors="coerce"),
            "entry": m[f"{me}_entry"].astype(str).str.upper().replace({"NAN": ""}),
            "walkover": m["walkover"].astype(bool), "retired": m["retired"].astype(bool), "sets": m["sets"]}))
    p = pd.concat(sides, ignore_index=True)
    p = p.sort_values(["name", "date", "tid", "stage", "rr", "key"], kind="stable").reset_index(drop=True)
    g = p.groupby(["name", "tid"], sort=False)
    p["k"] = g.cumcount()                       # matches already played at this event
    # ---- events per player in order
    ev = p.groupby(["name", "tid"], sort=False).agg(
        date=("date", "first"), level=("level", "first"), surf=("surf", "first"),
        final=("round", lambda s: bool((s == "F").any())),
        title=("won", "last"), last_round=("round", "last"), is_slam=("level", lambda s: s.iloc[0] == "G")).reset_index()
    ev = ev.sort_values(["name", "date", "tid"], kind="stable").reset_index(drop=True)
    ev["title"] = ev["final"] & (ev["last_round"] == "F") & (ev["title"] == 1)
    ge = ev.groupby("name", sort=False)
    for c in ("date", "final", "title", "level", "surf", "is_slam"):
        ev[f"prev_{c}"] = ge[c].shift(1)
    final_day = ev["prev_date"] + pd.to_timedelta(np.where(ev["prev_is_slam"].fillna(False).astype(bool), 13, 6), unit="D")
    gap = (ev["date"] - final_day).dt.days
    ev["hang_event"] = ev["prev_final"].fillna(False).astype(bool) & gap.between(1, 8)
    ev["hang_champ"] = ev["hang_event"] & ev["prev_title"].fillna(False).astype(bool)
    ev["hang_levelup"] = ev["hang_event"] & (ev["prev_level"] == "C") & ev["level"].isin(["250", "500", "M", "G", "F", "A"])
    ev["prev_gap_days"] = (ev["date"] - ev["prev_date"]).dt.days
    p = p.merge(ev[["name", "tid", "hang_event", "hang_champ", "hang_levelup", "prev_gap_days", "prev_surf"]], on=["name", "tid"], how="left")
    first = p["k"] == 0
    p["hangover"] = (first & p["hang_event"]).astype(int)
    p["hangover_champ"] = (first & p["hang_champ"]).astype(int)
    p["hangover_runnerup"] = (first & p["hang_event"] & ~p["hang_champ"]).astype(int)
    p["hangover_levelup"] = (first & p["hang_levelup"]).astype(int)
    # ---- venue (pair flag, built at match level below): per-player parts
    p["is_q"] = p["entry"].isin(["Q", "LL"])
    p["fresh_from_other"] = first & p["prev_gap_days"].between(1, 14)
    p["prev_diff_surface"] = p["prev_surf"].notna() & (p["prev_surf"] != p["surf"])
    # ---- layoff: days since the previous match (event start dates), rank at that match
    gp = p.groupby("name", sort=False)
    p["days_since"] = (p["date"] - gp["date"].shift(1)).dt.days
    p["rank_before"] = gp["prank"].shift(1)
    back = (p["days_since"] >= 91) & (p["rank_before"] <= 100)
    p["gap_id"] = back.astype(int).groupby(p["name"]).cumsum()
    p["n_since_gap"] = p.groupby(["name", "gap_id"]).cumcount()
    started = p.groupby(["name", "gap_id"])["days_since"].transform("first")
    rk = p.groupby(["name", "gap_id"])["rank_before"].transform("first")
    p["layoff"] = ((p["gap_id"] > 0) & (started >= 91) & (rk <= 100) & (p["n_since_gap"] <= 2)).astype(int)
    p["layoff_pr"] = (p["layoff"].astype(bool) & (p["entry"] == "PR")).astype(int)
    # ---- surface switch and specialism (strictly before this event)
    gs = p.groupby(["name", "surf"], sort=False)
    p["prev_surf_date"] = gs["date"].shift(1)
    sd = (p["date"] - p["prev_surf_date"]).dt.days
    p["surface"] = ((p.groupby(["name", "tid", "surf"]).cumcount() == 0) & (sd >= 56)).astype(int)
    # cumulative wins/matches before this EVENT: subtract this event's own rows
    p["cw"] = gp["won"].cumsum() - p["won"]
    p["cn"] = gp.cumcount()
    p["csw"] = gs["won"].cumsum() - p["won"]
    p["csn"] = gs.cumcount()
    ge2 = p.groupby(["name", "tid"], sort=False)
    for c in ("cw", "cn"):
        p[c] = ge2[c].transform("first")
    ge3 = p.groupby(["name", "tid", "surf"], sort=False)
    for c in ("csw", "csn"):
        p[c] = ge3[c].transform("first")
    spec = (p["csw"] + 2) / (p["csn"] + 4) - (p["cw"] + 2) / (p["cn"] + 4)
    p["surface_spec"] = p["surface"] * spec
    # ---- free pass in the previous round at this event
    pw = g["walkover"].shift(1)
    pr = g["retired"].shift(1)
    ps = g["sets"].shift(1)
    pwon = g["won"].shift(1)
    p["freepass"] = ((p["k"] >= 1) & (pwon == 1) & (pw.fillna(False).astype(bool) | (pr.fillna(False).astype(bool) & (ps <= 2)))).astype(int)
    return p


def canon_match_flags(p: pd.DataFrame) -> pd.DataFrame:
    """Per (canonical key, player name): every canonical flag, including the venue pair flag."""
    cols = ["hangover", "hangover_champ", "hangover_runnerup", "hangover_levelup", "layoff", "layoff_pr",
            "surface", "surface_spec", "freepass"]
    me = p[["key", "name", "opp", "level", "k", "is_q", "fresh_from_other", "prev_diff_surface"] + cols]
    op = p[["key", "name", "k", "is_q", "fresh_from_other", "prev_diff_surface"]].rename(
        columns={"name": "opp", "k": "o_k", "is_q": "o_q", "fresh_from_other": "o_fresh", "prev_diff_surface": "o_diff"})
    x = me.merge(op, on=["key", "opp"], how="left")
    atp_main = x["level"].isin(["250", "500", "M", "G", "A", "F"]) & x["key"].str.startswith("MEN|")
    v = atp_main & x["is_q"] & (x["k"] >= 2) & ~x["o_q"].fillna(False).astype(bool) & x["o_fresh"].fillna(False).astype(bool)
    x["venue"] = v.astype(int)
    x["venue_diff_surface"] = (v & x["o_diff"].fillna(False).astype(bool)).astype(int)
    return x.drop_duplicates(["key", "name"]).set_index(["key", "name"])[cols + ["venue", "venue_diff_surface"]]


# ------------------------------------------------------------------ per-player flags from the odds data (times, venues)
def odds_player_flags(j: pd.DataFrame, minutes: pd.Series, elev: dict) -> pd.DataFrame:
    """Per (match_key, player name): rest hours at the event and the altitude flag."""
    utc = pd.to_datetime(j["match_date_formatted"], errors="coerce") - pd.Timedelta(hours=9)
    rows = pd.concat([pd.DataFrame({"match_key": j["match_key"].values, "name": j[c].values, "tid": j["tid"].values, "utc": utc.values,
                                    "mins": j["ckey"].map(minutes).values, "elev": j["tournament"].map(elev).values})
                      for c in ("winner_name", "loser_name")], ignore_index=True)
    rows = rows.sort_values(["name", "utc", "match_key"], kind="stable").reset_index(drop=True)
    ge = rows.groupby(["name", "tid"], sort=False)
    prev_end = ge["utc"].shift(1) + pd.to_timedelta(ge["mins"].shift(1), unit="m")
    rows["rest_h"] = (rows["utc"] - prev_end).dt.total_seconds() / 3600
    rows["k_ev"] = ge.cumcount()
    # altitude: no match at an event >= 1000 m in the previous 21 days
    rows["hi"] = (rows["elev"] >= 1000).astype(int)
    acc = np.zeros(len(rows), bool)
    for name, idx in rows.groupby("name", sort=False).indices.items():
        t = rows["utc"].to_numpy()[idx]
        hi = rows["hi"].to_numpy()[idx]
        hi_t = t[hi == 1]
        if len(hi_t) == 0:
            continue
        lo = np.searchsorted(hi_t, t - np.timedelta64(21, "D"), side="left")
        up = np.searchsorted(hi_t, t, side="left")      # strictly earlier matches
        acc[idx] = (up - lo) > 0
    rows["altitude"] = ((rows["elev"] >= 1400) & ~acc & (rows["k_ev"] <= 1)).astype(int)
    return rows.drop_duplicates(["match_key", "name"]).set_index(["match_key", "name"])[["rest_h", "altitude"]]


def build(joined: pd.DataFrame, cf: pd.DataFrame, minutes: pd.Series, elev: dict) -> pd.DataFrame:
    j = joined.sort_values("match_key", kind="stable").reset_index(drop=True)
    of = odds_player_flags(j, minutes, elev)
    flip = j["flip"].to_numpy(bool)
    out = pd.DataFrame({"match_key": j["match_key"].values, "year": pd.to_datetime(j["wh_date"]).dt.year.values,
                        "level": j["odds_level"].values, "y": (~flip).astype(int)})
    na, nb = orient(j["winner_name"].to_numpy(), j["loser_name"].to_numpy(), flip)
    out["name_a"], out["name_b"] = na, nb
    ia = pd.MultiIndex.from_arrays([j["ckey"].values, na])
    ib = pd.MultiIndex.from_arrays([j["ckey"].values, nb])
    for c in ["hangover", "venue", "layoff", "surface", "freepass", "surface_spec"] + SLICES:
        a = cf[c].reindex(ia).fillna(0).to_numpy(float)   # missing = flag not set (row is kept; coverage reported)
        b = cf[c].reindex(ib).fillna(0).to_numpy(float)
        out[f"a_{c}"], out[f"b_{c}"] = a, b
    out["canon_found"] = ia.isin(cf.index) & ib.isin(cf.index)
    oa = pd.MultiIndex.from_arrays([j["match_key"].values, na])
    ob = pd.MultiIndex.from_arrays([j["match_key"].values, nb])
    ra, rb = of["rest_h"].reindex(oa).to_numpy(float), of["rest_h"].reindex(ob).to_numpy(float)
    out["rest_a"], out["rest_b"] = ra, rb
    rested_a = np.where(np.isfinite(ra), ra, 99.0)
    rested_b = np.where(np.isfinite(rb), rb, 99.0)
    out["a_short_rest"] = ((rested_a < 18) & (rested_b >= 30)).astype(float)
    out["b_short_rest"] = ((rested_b < 18) & (rested_a >= 30)).astype(float)
    out["a_rest_diff"] = np.minimum(np.clip(rested_a, 0, None), 48) / 24
    out["b_rest_diff"] = np.minimum(np.clip(rested_b, 0, None), 48) / 24
    out["a_altitude"] = of["altitude"].reindex(oa).fillna(0).to_numpy(float)
    out["b_altitude"] = of["altitude"].reindex(ob).fillna(0).to_numpy(float)
    for c in FLAGS + EXTRA + SLICES:
        out[f"d_{c}"] = out[f"a_{c}"] - out[f"b_{c}"]
    for book, (c1, c2) in BOOKS.items():
        o1, o2 = orient(pd.to_numeric(j[c1], errors="coerce"), pd.to_numeric(j[c2], errors="coerce"), flip)
        out[f"p_{book}"] = devig(o1, o2)
        out[f"oa_{book}"], out[f"ob_{book}"] = o1, o2
    return out


def swap_source(joined: pd.DataFrame) -> pd.DataFrame:
    j = joined.copy()
    for a, b in [("winner_name", "loser_name"), *BOOKS.values()]:
        j[a], j[b] = joined[b].values, joined[a].values
    return j


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


def flag_report(df, f, test, early, R, money=True):
    y = df["y"].to_numpy()
    a_only, b_only = (df[f"d_{f}"] == 1).to_numpy(), (df[f"d_{f}"] == -1).to_numpy()
    resid = np.where(a_only, y - df["p_bf_close"], np.where(b_only, df["p_bf_close"] - y, np.nan))
    who = np.where(a_only, df["name_a"], df["name_b"])
    ok = np.isfinite(resid)
    out = {}
    for lab, m in (("all", ok), ("2016-21", ok & early), ("2022-25", ok & test)):
        mean, lo, hi = boot_mean(resid[m], seed=SEED, cluster=who[m])
        se = (hi - lo) / 3.92
        out[lab] = {"n": int(m.sum()), "pts": round(100 * mean, 2), "range": [round(100 * lo, 2), round(100 * hi, 2)],
                    "mde_pts": round(100 * 2.8 * se, 2), "flagged_mean_close": round(float(np.where(a_only, df["p_bf_close"], 1 - df["p_bf_close"])[m].mean()), 3) if m.any() else None}
    for lv in ("ATP main", "WTA main", "Challenger"):
        m = ok & (df["level"] == lv).to_numpy()
        if m.sum() >= 30:
            mean, lo, hi = boot_mean(resid[m], seed=SEED, cluster=who[m])
            out[lv] = {"n": int(m.sum()), "pts": round(100 * mean, 2), "range": [round(100 * lo, 2), round(100 * hi, 2)]}
    R[f"{f}: flagged player won minus close (pts)"] = out
    e = out["2016-21"]["pts"]
    if money and out["2016-21"]["n"] and abs(e) >= 2:
        back_flagged = e > 0
        for book in BOOKS:
            x = df[test & (a_only | b_only) & df[f"p_{book}"].notna().to_numpy()]
            a_flag = (x[f"d_{f}"] == 1).to_numpy()
            back_a = a_flag if back_flagged else ~a_flag
            o = np.where(back_a, x[f"oa_{book}"], x[f"ob_{book}"])
            won = np.where(back_a, x["y"] == 1, x["y"] == 0)
            pnl = np.where(won, (o - 1) * (1 - COMMISSION[book]), -1.0)
            mean, lo, hi = boot_mean(pnl, seed=SEED)
            R[f"MONEY {f}: back the {'flagged' if back_flagged else 'other'} player at {book}, 2022-25"] = {
                "n": int(len(x)), "roi": round(mean, 4), "range": [round(lo, 4), round(hi, 4)]}


def main() -> int:
    joined_pkl, canon_pkl, hist_dir, events_csv, elev_csv, out_json = sys.argv[1:7]
    joined = pd.read_pickle(joined_pkl)
    joined = joined[joined["tour"].isin(["ATP", "WTA"]) & joined["odds_level"].isin(["ATP main", "WTA main", "Challenger"])].reset_index(drop=True)
    joined = joined.assign(match_key=np.arange(len(joined)), flip=coin_flip(len(joined), SEED))
    canon = pd.read_pickle(canon_pkl)
    ck = canon[["tid", "round", "winner_name", "loser_name", "key", "minutes"]].drop_duplicates(["tid", "round", "winner_name", "loser_name"])
    joined = joined.merge(ck.rename(columns={"round": "wh_round", "key": "ckey", "minutes": "c_minutes"}),
                          on=["tid", "wh_round", "winner_name", "loser_name"], how="left")
    minutes = ck.set_index("key")["minutes"]
    ev = pd.read_csv(events_csv)
    el = pd.read_csv(elev_csv)
    ev = ev.assign(latitude=ev["latitude"].round(4), longitude=ev["longitude"].round(4)).merge(el, on=["latitude", "longitude"], how="left")
    ev.loc[ev["tournament"].str.contains("|".join(ALT_OVERRIDE), case=False, na=False), "elev_m"] = 0.0
    elev = dict(zip(ev["tournament"], ev["elev_m"]))
    p = player_table(canon, history_attrs(Path(hist_dir)))
    cf = canon_match_flags(p)
    df = build(joined, cf, minutes, elev)
    df = df[(df["year"] >= 2016) & df["p_bf_close"].notna()].reset_index(drop=True)

    res = {"manifest": provenance.manifest({"joined": joined_pkl, "canon": canon_pkl, "history": hist_dir, "events": events_csv, "elev": elev_csv},
                                           {"orientation": SEED, "bootstrap": SEED}, " ".join(["python"] + sys.argv)),
           "rows": int(len(df)), "by_level": df["level"].value_counts().to_dict(),
           "canonical match found": round(float(df["canon_found"].mean()), 4),
           "flag rates (share of matches with the flag on either side)": {f: round(float(((df[f"a_{f}"] + df[f"b_{f}"]) > 0).mean()), 4) for f in FLAGS + SLICES},
           "high-altitude events (>= 1400 m) used": sorted(k for k, v in elev.items() if v is not None and v >= 1400)}
    rest = np.concatenate([df["rest_a"].to_numpy(), df["rest_b"].to_numpy()])
    rest = rest[np.isfinite(rest)]
    res["start-time check: rests with a previous match at the event"] = {
        "n": int(len(rest)), "share negative (start before previous end)": round(float((rest < 0).mean()), 4),
        "share under 1 h": round(float((rest < 1).mean()), 4), "median h": round(float(np.median(rest)), 1)}
    R = res["results"] = {}
    y = df["y"].to_numpy()
    test = df["year"].isin(TEST_YEARS).to_numpy()
    early = (df["year"] < 2022).to_numpy()
    cols = [f"d_{f}" for f in FLAGS + EXTRA]
    p0, p1 = fit_predict(df, []), fit_predict(df, cols)
    m = test & np.isfinite(p1)
    R["PRIMARY M1 (nine inputs) minus M0, close, 2022-25 log loss"] = [round(v, 5) for v in boot_mean(log_loss(y[m], p1[m]) - log_loss(y[m], p0[m]), seed=SEED)] + [int(m.sum())]
    for lv in ("ATP main", "WTA main", "Challenger"):
        mm = m & (df["level"] == lv).to_numpy()
        R[f"M1 minus M0, {lv}"] = [round(v, 5) for v in boot_mean(log_loss(y[mm], p1[mm]) - log_loss(y[mm], p0[mm]), seed=SEED)] + [int(mm.sum())]
    from sklearn.linear_model import LogisticRegression
    tr = (df["year"] >= 2016).to_numpy() & ~test
    X = np.column_stack([logit(df["p_bf_close"].to_numpy())] + [df[c].to_numpy() for c in cols])
    lr = LogisticRegression(C=0.3, max_iter=1000).fit(X[tr], y[tr])
    R["M1 coefficients fitted on 2016-21 (logit units)"] = dict(zip(["market"] + cols, [round(float(v), 4) for v in lr.coef_[0]]))
    for f in FLAGS + SLICES:
        flag_report(df, f, test, early, R, money=f in FLAGS)
    # rest difference as a continuous residual check: within matches where both rests are known
    both = np.isfinite(df["rest_a"]) & np.isfinite(df["rest_b"])
    rd = (df["a_rest_diff"] - df["b_rest_diff"])[both]
    resid = (df["y"] - df["p_bf_close"])[both]
    R["rest difference (A minus B, days, capped 2) vs residual: slope pts per day, both rests known"] = {
        "n": int(both.sum()), "slope_pts": round(100 * float(np.polyfit(rd, resid, 1)[0]), 3) if both.sum() > 10 else None}
    C = {}
    raw = joined[joined["tour"] == "WTA"]
    C["swap_source"] = checks.swap_source(lambda r, f: build(r.assign(flip=f), cf, minutes, elev), raw, swap_source,
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
