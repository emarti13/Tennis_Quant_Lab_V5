from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from v5_tournament_authority import audit_authority, load_authority
from v5_tournament_challenger import (
    add_authority_features,
    attach_authority_context,
    evaluate_challenger_frame,
    fit_ball_categories,
)


def _segmented_coverage(frame: pd.DataFrame) -> dict:
    fields = [
        "authority_match_method",
        "authority_altitude_m",
        "authority_setting",
        "authority_ball_model",
        "authority_cpi",
        "authority_ta",
        "authority_latitude",
        "authority_longitude",
        "authority_timezone",
    ]
    output = {}
    grouped = frame.groupby(["year", "tour"], dropna=False, sort=True)
    for (year, tour), group in grouped:
        key = f"{int(year)}:{tour}"
        output[key] = {
            "rows": int(len(group)),
            **{
                field: float(group[field].notna().mean()) if field in group.columns else 0.0
                for field in fields
            },
        }
    return output


def _unresolved_top(frame: pd.DataFrame, limit: int = 50) -> list[dict]:
    unresolved = frame[frame["authority_match_method"].isna()].copy()
    if unresolved.empty:
        return []
    grouped = (
        unresolved.groupby(["year", "tour", "tourney_name"], dropna=False)
        .size()
        .reset_index(name="matches")
        .sort_values(["matches", "year", "tour"], ascending=[False, True, True])
        .head(int(limit))
    )
    rows = []
    for _, row in grouped.iterrows():
        rows.append({
            "year": None if pd.isna(row["year"]) else int(row["year"]),
            "tour": str(row["tour"]),
            "tourney_name": str(row["tourney_name"]),
            "matches": int(row["matches"]),
        })
    return rows


def run(
    base_dir: str | Path = ".",
    output_dir: str | Path = "v5_tournament_challenger_diagnostic",
) -> dict:
    base = Path(base_dir)
    matched_path = base / "v5_context_diagnostic" / "matched_context_rows.parquet"
    if not matched_path.exists():
        raise FileNotFoundError(
            "v5_context_diagnostic/matched_context_rows.parquet missing; run diagnose_v5_context_model.py first"
        )

    matchups = pd.read_parquet(matched_path)
    authority = load_authority(base / "context_registry" / "tournament_authority.csv")
    attached, coverage = attach_authority_context(matchups, authority)
    ball_categories = fit_ball_categories(attached, fit_year=2025, min_rows=100)
    featured = add_authority_features(attached, ball_categories=ball_categories)

    report = {
        "diagnostic_version": "v5-tournament-authority-challenger-1",
        "authority_contract": (
            "tournament_authority.csv is the sole court/tournament truth; OddsPapi ID is optional identity evidence; "
            "unresolved or missing values remain missing; retired court/schedule values are prohibited as fallback"
        ),
        "fit_year": 2025,
        "validation_year": 2026,
        "matchup_rows": int(len(featured)),
        "authority_table": audit_authority(authority),
        "match_coverage": coverage,
        "coverage_by_year_tour": _segmented_coverage(featured),
        "unresolved_top": _unresolved_top(featured),
        "ball_categories_fit_on_2025_only": ball_categories,
        "tours": {},
    }

    for tour in ("MEN", "WTA"):
        tour_frame = featured[featured["tour"].astype(str).str.upper().eq(tour)].copy()
        fit_rows = int(pd.to_numeric(tour_frame["year"], errors="coerce").eq(2025).sum())
        validation_rows = int(pd.to_numeric(tour_frame["year"], errors="coerce").eq(2026).sum())
        if fit_rows == 0 or validation_rows == 0:
            report["tours"][tour] = {
                "status": "insufficient_rows",
                "fit_rows": fit_rows,
                "validation_rows": validation_rows,
            }
            continue
        evaluation = evaluate_challenger_frame(tour_frame, fit_year=2025, validation_year=2026)
        evaluation["status"] = "evaluated"
        report["tours"][tour] = evaluation

    all_groups = sorted({
        group
        for tour_report in report["tours"].values()
        if tour_report.get("status") == "evaluated"
        for group in tour_report.get("eligibility", {})
    })
    report["cross_tour_eligibility"] = {
        group: {
            tour: bool(report["tours"].get(tour, {}).get("eligibility", {}).get(group, False))
            for tour in ("MEN", "WTA")
        }
        for group in all_groups
    }

    out_dir = base / output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    featured.to_parquet(out_dir / "matched_authority_rows.parquet", index=False)
    print(json.dumps(report, indent=2, allow_nan=False))
    return report


if __name__ == "__main__":
    run(".")
