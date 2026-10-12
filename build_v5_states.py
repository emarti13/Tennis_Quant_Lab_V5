
import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from v5_core import DynamicServeReturn, SurfaceElo
from v5_season_files import recent_season_years, season_sources

SURFACES = ["Hard", "Clay", "Grass"]

# Cached multi-season aggregates from bootstrap_v5_history.py. Building
# ratings without them would silently drop years of history, so fail closed.
REQUIRED_HISTORY_FILES = {"ATP.csv", "ATPQualifiers.csv", "Challenger.csv", "WTA.csv"}

# Only load columns V5 actually uses. This makes the large historical files
# much faster to read and uses far less RAM.
NEEDED_COLS = {
    "tourney_id", "tourney_date", "match_num", "surface",
    "winner_name", "loser_name", "winner_rank", "loser_rank",
    "w_svpt", "w_1stWon", "w_2ndWon",
    "l_svpt", "l_1stWon", "l_2ndWon",
}


def load(path, level, tour):
    path = Path(path)
    size_mb = path.stat().st_size / (1024 * 1024)
    print(f"      Reading {path.name} ({size_mb:.1f} MB)...", flush=True)
    t0 = time.time()

    # Read the header first and pass pandas an explicit usecols list.
    # This avoids a pandas C-parser bug seen on the large WTA file when
    # a callable usecols filter is combined with chunked parsing.
    header = pd.read_csv(
        path,
        nrows=0,
        encoding="utf-8-sig",
        engine="python",
    ).columns.tolist()

    usecols = [c for c in header if c in NEEDED_COLS]

    try:
        d = pd.read_csv(
            path,
            usecols=usecols,
            engine="c",
            low_memory=False,
            encoding="utf-8-sig",
            encoding_errors="replace",
        )
    except IndexError:
        # Pandas 3.x / Python 3.14 can occasionally throw an internal
        # C-parser IndexError while concatenating chunks. The Python
        # parser is slower but stable and preserves every row.
        print(
            f"      C parser hit an internal pandas error on {path.name}; "
            "retrying safely with the Python parser...",
            flush=True,
        )
        d = pd.read_csv(
            path,
            usecols=usecols,
            engine="python",
            encoding="utf-8-sig",
            encoding_errors="replace",
        )

    # Guarantee fields used later exist even if one source omits them.
    for c in NEEDED_COLS:
        if c not in d.columns:
            d[c] = np.nan

    d["_level"] = level
    d["_tour"] = tour

    date_text = (
        d["tourney_date"]
        .astype("string")
        .str.replace(r"\.0$", "", regex=True)
        .str.slice(0, 8)
    )
    d["date"] = pd.to_datetime(
        date_text,
        format="%Y%m%d",
        errors="coerce",
    )

    print(
        f"      {path.name}: {len(d):,} rows loaded in {time.time()-t0:.1f}s",
        flush=True,
    )
    return d

def dedupe(d):
    keys = [
        c for c in ["tourney_id", "match_num", "winner_name", "loser_name"]
        if c in d.columns
    ]
    if keys:
        before = len(d)
        d = d.drop_duplicates(keys, keep="last")
        print(f"      De-duplication: {before:,} -> {len(d):,}", flush=True)
    return d


def estimate_baselines(d, cut="2025-01-01", default=.62):
    x = d[d.date < pd.Timestamp(cut)].copy()
    out = {}

    for surface in SURFACES:
        z = x[x.surface.astype(str).str.title() == surface]

        w_first = pd.to_numeric(z["w_1stWon"], errors="coerce")
        w_second = pd.to_numeric(z["w_2ndWon"], errors="coerce")
        l_first = pd.to_numeric(z["l_1stWon"], errors="coerce")
        l_second = pd.to_numeric(z["l_2ndWon"], errors="coerce")
        w_svpt = pd.to_numeric(z["w_svpt"], errors="coerce")
        l_svpt = pd.to_numeric(z["l_svpt"], errors="coerce")

        won = (w_first + w_second).sum(skipna=True)
        won += (l_first + l_second).sum(skipna=True)
        pts = w_svpt.sum(skipna=True) + l_svpt.sum(skipna=True)

        out[surface] = float(won / pts) if pts > 10000 else default

    return out


def _vol_label(p):
    if p < 20:
        return "Very Low"
    if p < 40:
        return "Low"
    if p < 60:
        return "Average"
    if p < 80:
        return "High"
    return "Very High"


def _form_label(p, value):
    if abs(value) < .01:
        return "Neutral"
    if p >= 80:
        return "Hot"
    if p >= 60:
        return "Positive"
    if p <= 20:
        return "Cold"
    if p <= 40:
        return "Negative"
    return "Neutral"


def process(d, tour, outdir, holdout_start="2025-01-01"):
    d = d[d.date >= pd.Timestamp("2010-01-01")].copy()
    d = d[
        d.winner_name.notna()
        & d.loser_name.notna()
        & d.date.notna()
    ].copy()

    # tourney_id and match_num can be missing in some files; sort remains stable.
    d["_sort_tourney"] = d["tourney_id"].astype("string").fillna("")
    d["_sort_match"] = pd.to_numeric(d["match_num"], errors="coerce").fillna(0)
    d = d.sort_values(
        ["date", "_sort_tourney", "_sort_match"],
        kind="mergesort",
    ).reset_index(drop=True)

    baseline = estimate_baselines(
        d,
        cut=holdout_start,
        default=.62 if tour == "MEN" else .59,
    )

    sr = DynamicServeReturn(baseline)
    elo = SurfaceElo()
    pred = []

    total = len(d)
    print(
        f"      Building {tour} chronological states from {total:,} matches...",
        flush=True,
    )
    t0 = time.time()

    # iterrows is retained for compatibility with v5_core.update_match(row),
    # but progress is printed so Windows never looks frozen.
    for i, r in d.iterrows():
        surf = str(r.get("surface", "Hard")).title()
        if surf not in SURFACES:
            surf = "Hard"

        w = str(r.winner_name)
        l = str(r.loser_name)

        pw = sr.point_prob(w, l, surf, i)
        pl = sr.point_prob(l, w, surf, i)
        pe = elo.probability(w, l, surf)

        if r.date >= pd.Timestamp(holdout_start):
            pred.append({
                "date": r.date,
                "tour": tour,
                "surface": surf,
                "level": r["_level"],
                "winner": w,
                "loser": l,
                "winner_serve_p": pw,
                "loser_serve_p": pl,
                "elo_winner_p": pe,
                "winner_rank": r.get("winner_rank"),
                "loser_rank": r.get("loser_rank"),
            })

        sr.update_match(r, i)
        elo.update(w, l, surf)

        done = i + 1
        if done % 10000 == 0 or done == total:
            elapsed = time.time() - t0
            rate = done / elapsed if elapsed else 0
            remain = (total - done) / rate if rate else 0
            print(
                f"        {done:,}/{total:,} matches "
                f"({done/total:.0%}) | "
                f"{rate:,.0f} matches/s | "
                f"~{remain/60:.1f} min remaining",
                flush=True,
            )

    print(f"      {tour} match processing complete.", flush=True)

    players = set(sr.g.keys()) | set(elo.players.keys())
    states = []

    print(f"      Writing current states for {len(players):,} {tour} players...", flush=True)

    for p in players:
        for surf in SURFACES:
            ss = sr.s[(p, surf)]
            gs = sr.g[p]
            es = elo.snapshot(p, surf)
            cs = sr.current_state(p, surf)

            states.append({
                "player": p,
                "surface": surf,
                "serve_global": gs.serve,
                "return_global": gs.ret,
                "global_points": gs.n_points,
                "serve_surface": ss.serve,
                "return_surface": ss.ret,
                "surface_points": ss.n_points,
                **cs,
                **es,
            })

    state = pd.DataFrame(states)

    # Empirical volatility calibration by tour + surface.
    calibration = {}

    for surf in SURFACES:
        mask = state.surface == surf

        ref = state[
            mask
            & (state.form_matches >= 8)
            & state.raw_day_vol_logit.notna()
        ].copy()

        if ref.empty:
            ref = state[
                (state.form_matches >= 8)
                & state.raw_day_vol_logit.notna()
            ].copy()

        prior = float(ref.raw_day_vol_logit.median()) if len(ref) else .08
        q05 = float(ref.raw_day_vol_logit.quantile(.05)) if len(ref) else .04
        q95 = float(ref.raw_day_vol_logit.quantile(.95)) if len(ref) else .16

        calibration[surf] = {
            "prior_volatility": prior,
            "q05": q05,
            "q95": q95,
            "reference_n": int(len(ref)),
        }

        n = state.loc[mask, "form_matches"].fillna(0).astype(float)
        reliability = n / (n + 12.0)

        raw = (
            state.loc[mask, "raw_day_vol_logit"]
            .fillna(prior)
            .astype(float)
        )

        shrunk = reliability * raw + (1 - reliability) * prior

        state.loc[mask, "vol_shrunk_logit"] = shrunk
        state.loc[mask, "day_vol_logit"] = shrunk.clip(
            lower=q05,
            upper=q95,
        )
        state.loc[mask, "vol_reliability"] = reliability

        ref_arr = (
            np.sort(ref.raw_day_vol_logit.to_numpy())
            if len(ref)
            else np.array([prior])
        )
        state.loc[mask, "vol_percentile"] = (
            np.searchsorted(
                ref_arr,
                raw.to_numpy(),
                side="right",
            )
            / len(ref_arr)
            * 100
        )

        fref = state.loc[
            mask & (state.form_matches >= 5),
            "form_logit",
        ].dropna()

        farr = (
            np.sort(fref.to_numpy())
            if len(fref)
            else np.array([0.0])
        )

        fvals = (
            state.loc[mask, "form_logit"]
            .fillna(0)
            .to_numpy()
        )

        state.loc[mask, "form_percentile"] = (
            np.searchsorted(farr, fvals, side="right")
            / len(farr)
            * 100
        )

    state["volatility_label"] = (
        state.vol_percentile
        .fillna(50)
        .apply(_vol_label)
    )

    state["form_label"] = [
        _form_label(p, v)
        for p, v in zip(
            state.form_percentile.fillna(50),
            state.form_logit.fillna(0),
        )
    ]

    overall_depth = (
        state.form_matches.fillna(0)
        / (state.form_matches.fillna(0) + 20)
    ).clip(0, 1)

    surface_depth = (
        state.surface_form_matches.fillna(0)
        / (state.surface_form_matches.fillna(0) + 10)
    ).clip(0, 1)

    state["state_confidence"] = (
        .65 * overall_depth
        + .35 * surface_depth
    )

    state["state_confidence_label"] = (
        state.state_confidence.apply(
            lambda x: "High"
            if x >= .75
            else ("Medium" if x >= .45 else "Low")
        )
    )

    state.to_csv(
        outdir / f"v5_{tour.lower()}_ratings.csv",
        index=False,
    )

    pd.DataFrame(pred).to_csv(
        outdir / f"v5_{tour.lower()}_walkforward.csv",
        index=False,
    )

    return {
        "tour": tour,
        "baseline": baseline,
        "matches": len(d),
        "holdout_matches": len(pred),
        "players": len(players),
        "volatility_calibration": calibration,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=".")
    args = ap.parse_args()

    d = Path(args.dir)

    print("=" * 58, flush=True)
    print("TENNIS QUANT LAB V5 — CALIBRATED STATE BUILD", flush=True)
    print("=" * 58, flush=True)

    # Per-season files come from the refresh; overlap with the cached history
    # aggregates is removed by dedupe().
    seasons = recent_season_years()
    men_sources = [
        ("ATP.csv", "Main"),
        ("ATPQualifiers.csv", "Qualifying"),
        ("Challenger.csv", "Challenger"),
        *season_sources("MEN", seasons),
        ("ongoing_tourneys.csv", "Main"),
        ("challenger_ongoing_tourneys.csv", "Challenger"),
    ]

    women_sources = [
        ("WTA.csv", "Main"),
        *season_sources("WTA", seasons),
        ("wta_ongoing_tourneys.csv", "Main"),
    ]

    print("\n[1/3] Loading MEN source files...", flush=True)
    men = []
    for f, level in men_sources:
        path = d / f
        if path.exists():
            men.append(load(path, level, "MEN"))
        elif f in REQUIRED_HISTORY_FILES:
            raise FileNotFoundError(f"Required history aggregate missing: {f} (run bootstrap_v5_history.py)")
        else:
            print(f"      Skipping missing file: {f}", flush=True)

    if not men:
        raise FileNotFoundError("No MEN source files were found.")

    md = dedupe(pd.concat(men, ignore_index=True, sort=False))
    print(f"      MEN combined rows: {len(md):,}", flush=True)
    ms = process(md, "MEN", d)

    print("\n[2/3] Loading WTA source files...", flush=True)
    women = []
    for f, level in women_sources:
        path = d / f
        if path.exists():
            women.append(load(path, level, "WTA"))
        elif f in REQUIRED_HISTORY_FILES:
            raise FileNotFoundError(f"Required history aggregate missing: {f} (run bootstrap_v5_history.py)")
        else:
            print(f"      Skipping missing file: {f}", flush=True)

    if not women:
        raise FileNotFoundError("No WTA source files were found.")

    wd = dedupe(pd.concat(women, ignore_index=True, sort=False))
    print(f"      WTA combined rows: {len(wd):,}", flush=True)
    ws = process(wd, "WTA", d)

    print("\n[3/3] Saving build summary...", flush=True)
    (d / "v5_build_summary.json").write_text(
        json.dumps(
            {"MEN": ms, "WTA": ws},
            indent=2,
            default=str,
        )
    )

    print("\n[3/3] COMPLETE", flush=True)
    print("Current V5 rating states and walk-forward files written.", flush=True)


if __name__ == "__main__":
    main()
