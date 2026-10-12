#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import json
import re
import unicodedata
import pandas as pd

BASE = Path(__file__).resolve().parents[1]
HISTORY = BASE / "v5_daily_ready" / "market_snapshot_history.csv"
FROZEN = BASE / "v5_daily_ready" / "frozen_predictions.csv"
OUTDIR = BASE / "exports"
MATCH_OUT = OUTDIR / "kalshi_training_matches.csv"
SIDE_OUT = OUTDIR / "kalshi_training_sides.csv"
QC_OUT = OUTDIR / "kalshi_training_export_qc.json"\nDIAG_OUT = OUTDIR / "model_layer_diagnostic.json"


def cname(value):
    s = "" if value is None else str(value).strip()
    if "," in s:
        a, b = [x.strip() for x in s.split(",", 1)]
        if a and b:
            s = f"{b} {a}"
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def nseries(df, col):
    if col not in df.columns:
        return pd.Series(index=df.index, dtype=float)
    return pd.to_numeric(df[col], errors="coerce")


def sseries(df, col):
    if col not in df.columns:
        return pd.Series("", index=df.index, dtype=object)
    return df[col].fillna("").astype(str)


def first_nonblank(group, *cols):
    for c in cols:
        if c not in group.columns:
            continue
        vals = group[c].dropna().astype(str)
        vals = vals[vals.str.strip().ne("")]
        if not vals.empty:
            return vals.iloc[0]
    return ""


def main():
    OUTDIR.mkdir(parents=True, exist_ok=True)
    hist = pd.read_csv(HISTORY, low_memory=False)
    frozen = pd.read_csv(FROZEN, low_memory=False)

    qc = {
        "history_rows": int(len(hist)),
        "frozen_rows": int(len(frozen)),
        "history_columns": list(hist.columns),
        "frozen_columns": list(frozen.columns),
    }

    # Market history: moneyline only, with valid pre-match timestamp and price.
    mh = hist[sseries(hist, "market_group").str.lower().eq("moneyline")].copy()
    mh["snapshot_dt"] = pd.to_datetime(mh.get("snapshot_utc"), errors="coerce", utc=True)
    mh["start_dt"] = pd.to_datetime(mh.get("start_time_utc"), errors="coerce", utc=True)
    mh["best_decimal_odds_num"] = nseries(mh, "best_decimal_odds")
    mh["model_probability_num"] = nseries(mh, "model_probability")
    mh["market_probability_num"] = nseries(mh, "consensus_no_vig_prob")
    mh = mh[
        mh["snapshot_dt"].notna()
        & mh["start_dt"].notna()
        & (mh["snapshot_dt"] < mh["start_dt"])
        & mh["best_decimal_odds_num"].gt(1.0)
        & mh["model_probability_num"].between(0, 1, inclusive="both")
    ].copy()
    mh["fixture_id"] = sseries(mh, "fixture_id")
    mh["selection_key"] = sseries(mh, "selection").map(cname)

    # Earliest snapshot per fixture that actually contains both moneyline sides.
    snap_counts = (
        mh.groupby(["fixture_id", "snapshot_dt"], dropna=False)["selection_key"]
        .nunique()
        .reset_index(name="side_count")
    )
    complete_snaps = snap_counts[snap_counts["side_count"].ge(2)].copy()
    earliest = (
        complete_snaps.sort_values(["fixture_id", "snapshot_dt"])
        .drop_duplicates("fixture_id", keep="first")
        [["fixture_id", "snapshot_dt"]]
        .rename(columns={"snapshot_dt": "first_snapshot_dt"})
    )
    opening = mh.merge(
        earliest,
        left_on=["fixture_id", "snapshot_dt"],
        right_on=["fixture_id", "first_snapshot_dt"],
        how="inner",
    )

    # Settlement truth comes from the frozen production ledger after TennisMyLife settlement.
    fr = frozen.copy()
    fr["fixture_id"] = sseries(fr, "fixture_id")
    status = sseries(fr, "result_status").str.upper()
    winner = sseries(fr, "result_winner")
    fr = fr[status.eq("SETTLED") & winner.str.strip().ne("")].copy()
    fr["winner_key"] = winner.loc[fr.index].map(cname)

    truth_rows = []
    for fixture_id, g in fr.groupby("fixture_id", sort=False):
        truth_rows.append({
            "fixture_id": fixture_id,
            "winner": first_nonblank(g, "result_winner"),
            "loser": first_nonblank(g, "result_loser"),
            "score": first_nonblank(g, "result_score"),
            "result_tournament": first_nonblank(g, "result_tournament", "tournament"),
            "result_tourney_date": first_nonblank(g, "result_tourney_date"),
            "model_version": first_nonblank(g, "model_version"),
        })
    truth = pd.DataFrame(truth_rows)

    side_rows = []
    match_rows = []
    excluded = {"missing_truth": 0, "missing_player_mapping": 0, "missing_two_sides": 0}

    truth_by_fixture = truth.set_index("fixture_id").to_dict("index") if not truth.empty else {}

    for fixture_id, g in opening.groupby("fixture_id", sort=False):
        t = truth_by_fixture.get(fixture_id)
        if not t:
            excluded["missing_truth"] += 1
            continue

        g = g.sort_values("snapshot_dt").drop_duplicates("selection_key", keep="first").copy()
        p1 = first_nonblank(g, "player1")
        p2 = first_nonblank(g, "player2")
        if not p1 or not p2:
            # Fall back to the two selection names if participant columns are absent.
            sels = [x for x in g.get("selection", pd.Series(dtype=object)).dropna().astype(str).unique() if x.strip()]
            if len(sels) >= 2:
                p1, p2 = sels[:2]
        if not p1 or not p2:
            excluded["missing_player_mapping"] += 1
            continue

        p1k, p2k = cname(p1), cname(p2)
        by_key = {cname(r.get("selection")): r for _, r in g.iterrows()}
        r1 = by_key.get(p1k)
        r2 = by_key.get(p2k)
        if r1 is None or r2 is None:
            # Last-resort: if exactly two distinct sides exist, preserve them in displayed order.
            distinct = g.drop_duplicates("selection_key", keep="first")
            if len(distinct) >= 2:
                rr = [row for _, row in distinct.head(2).iterrows()]
                r1, r2 = rr[0], rr[1]
                p1, p2 = str(r1.get("selection") or p1), str(r2.get("selection") or p2)
                p1k, p2k = cname(p1), cname(p2)
            else:
                excluded["missing_two_sides"] += 1
                continue

        winner_name = t["winner"]
        wk = cname(winner_name)
        p1_won = 1 if wk == p1k else (0 if wk == p2k else None)
        if p1_won is None:
            excluded["missing_player_mapping"] += 1
            continue

        common = {
            "fixture_id": fixture_id,
            "forecast_date": first_nonblank(g, "forecast_date"),
            "start_time_utc": first_nonblank(g, "start_time_utc"),
            "first_market_snapshot_utc": pd.Timestamp(g["snapshot_dt"].iloc[0]).isoformat(),
            "tournament": first_nonblank(g, "tournament"),
            "tour": first_nonblank(g, "tour_v5", "tour"),
            "surface": first_nonblank(g, "surface"),
            "best_of": first_nonblank(g, "best_of"),
            "model_version": t.get("model_version") or first_nonblank(g, "model_version"),
            "winner": winner_name,
            "loser": t["loser"],
            "score": t["score"],
            "result_tournament": t["result_tournament"],
            "result_tourney_date": t["result_tourney_date"],
        }

        def val(row, key, numeric=False):
            x = row.get(key)
            if numeric:
                try:
                    return float(x)
                except Exception:
                    return None
            return "" if pd.isna(x) else x

        match_rows.append({
            **common,
            "player1": p1,
            "player2": p2,
            "v5_probability_player1": val(r1, "model_probability", True),
            "v5_probability_player2": val(r2, "model_probability", True),
            "first_observed_decimal_odds_player1": val(r1, "best_decimal_odds", True),
            "first_observed_decimal_odds_player2": val(r2, "best_decimal_odds", True),
            "first_observed_no_vig_probability_player1": val(r1, "consensus_no_vig_prob", True),
            "first_observed_no_vig_probability_player2": val(r2, "consensus_no_vig_prob", True),
            "first_observed_book_player1": val(r1, "best_bookmaker"),
            "first_observed_book_player2": val(r2, "best_bookmaker"),
            "player1_won": p1_won,
        })

        for player, opponent, row, won in [
            (p1, p2, r1, p1_won),
            (p2, p1, r2, 1 - p1_won),
        ]:
            side_rows.append({
                **common,
                "player": player,
                "opponent": opponent,
                "v5_probability": val(row, "model_probability", True),
                "first_observed_decimal_odds": val(row, "best_decimal_odds", True),
                "first_observed_no_vig_probability": val(row, "consensus_no_vig_prob", True),
                "first_observed_book": val(row, "best_bookmaker"),
                "won": won,
            })

    matches = pd.DataFrame(match_rows)
    sides = pd.DataFrame(side_rows)
    if not matches.empty:
        matches = matches.sort_values(["start_time_utc", "fixture_id"]).reset_index(drop=True)
    if not sides.empty:
        sides = sides.sort_values(["start_time_utc", "fixture_id", "player"]).reset_index(drop=True)

    matches.to_csv(MATCH_OUT, index=False)
    sides.to_csv(SIDE_OUT, index=False)

    qc.update({
        "moneyline_history_rows_valid_pre_match": int(len(mh)),
        "fixtures_with_complete_first_snapshot": int(len(earliest)),
        "settled_truth_fixtures": int(len(truth)),
        "exported_matches": int(len(matches)),
        "exported_sides": int(len(sides)),
        "excluded": excluded,
        "date_min": None if matches.empty else str(matches["start_time_utc"].min()),
        "date_max": None if matches.empty else str(matches["start_time_utc"].max()),
        "definition_starting_odds": "earliest complete two-sided pre-match moneyline snapshot retained in market_snapshot_history.csv; this is first observed in our warehouse, not guaranteed sportsbook opening line",
        "match_output": str(MATCH_OUT.relative_to(BASE)),
        "side_output": str(SIDE_OUT.relative_to(BASE)),
    })

    def layer_metrics(frame):
        if frame.empty:
            return {}
        f = frame.copy()
        y = pd.to_numeric(f["player1_won"], errors="coerce")
        q1 = pd.to_numeric(f["first_observed_no_vig_probability_player1"], errors="coerce")
        q2 = pd.to_numeric(f["first_observed_no_vig_probability_player2"], errors="coerce")
        market = q1 / (q1 + q2)
        layers = {
            "final_v5": pd.to_numeric(f["v5_probability_player1"], errors="coerce"),
            "accepted_baseline": pd.to_numeric(f["accepted_baseline_probability_p1"], errors="coerce"),
            "elo": pd.to_numeric(f["elo_probability_p1"], errors="coerce"),
            "full_context": pd.to_numeric(f["full_context_probability_p1"], errors="coerce"),
            "market": market,
        }
        out = {"n": int(len(f))}
        for name, prob in layers.items():
            valid = y.notna() & prob.notna()
            if not valid.any():
                out[name] = {"n": 0, "brier": None, "accuracy": None}
                continue
            yy = y[valid].astype(float)
            pp = prob[valid].astype(float).clip(1e-8, 1-1e-8)
            out[name] = {
                "n": int(valid.sum()),
                "brier": float(((pp - yy) ** 2).mean()),
                "accuracy": float(((pp >= .5) == (yy >= .5)).mean()),
                "mean_probability": float(pp.mean()),
            }
        return out

    diagnostic = {"overall": layer_metrics(matches), "by_cutoff": {}, "by_tournament": {}}
    if not matches.empty:
        starts = pd.to_datetime(matches["start_time_utc"], errors="coerce", utc=True)
        for cutoff in ("2026-09-21", "2026-09-28", "2026-10-01", "2026-10-05", "2026-10-07"):
            diagnostic["by_cutoff"][cutoff] = layer_metrics(matches[starts >= pd.Timestamp(cutoff, tz="UTC")])
        for name, group in matches.groupby("tournament"):
            if len(group) >= 8:
                diagnostic["by_tournament"][str(name)] = layer_metrics(group)
        diagnostic["extreme_disagreements"] = (
            matches.assign(
                market_p1=pd.to_numeric(matches["first_observed_no_vig_probability_player1"], errors="coerce") /
                          (pd.to_numeric(matches["first_observed_no_vig_probability_player1"], errors="coerce") +
                           pd.to_numeric(matches["first_observed_no_vig_probability_player2"], errors="coerce")),
                final_p1=pd.to_numeric(matches["v5_probability_player1"], errors="coerce"),
            )
            .assign(abs_gap=lambda x: (x["final_p1"] - x["market_p1"]).abs())
            .sort_values("abs_gap", ascending=False)
            .head(30)[[
                "fixture_id","start_time_utc","tournament","player1","player2","winner",
                "player1_won","final_p1","accepted_baseline_probability_p1","elo_probability_p1",
                "full_context_probability_p1","market_p1","abs_gap","selected_model_candidate",
                "player1_cold_start","player2_cold_start","player1_identity_status","player2_identity_status"
            ]].to_dict("records")
        )
    DIAG_OUT.write_text(json.dumps(diagnostic, indent=2, default=str), encoding="utf-8")

    QC_OUT.write_text(json.dumps(qc, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: qc[k] for k in [
        "history_rows", "frozen_rows", "moneyline_history_rows_valid_pre_match",
        "fixtures_with_complete_first_snapshot", "settled_truth_fixtures",
        "exported_matches", "exported_sides", "excluded", "date_min", "date_max"
    ]}, indent=2))


if __name__ == "__main__":
    main()
