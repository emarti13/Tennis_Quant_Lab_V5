from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from v5_score_walkforward import parse_completed_score
from v5_tournament_score_challenger import evaluate_score_challenger_frame

OUTDIR = Path("v5_tournament_score_challenger_diagnostic")


def _attach_scores(matchups: pd.DataFrame, matches: pd.DataFrame) -> pd.DataFrame:
    scores = matches[["match_id", "score"]].drop_duplicates("match_id").copy()
    parsed = scores["score"].map(parse_completed_score).apply(pd.Series)
    scores = pd.concat([scores, parsed], axis=1)
    scores = scores[scores["completed"].eq(True)].copy()
    out = matchups.merge(
        scores[["match_id", "total_games", "winner_margin"]],
        on="match_id",
        how="inner",
        validate="one_to_one",
    )
    out["actual_total"] = pd.to_numeric(out["total_games"], errors="coerce")
    winner_margin = pd.to_numeric(out["winner_margin"], errors="coerce")
    out["actual_margin_a"] = np.where(
        pd.to_numeric(out["target_a_win"], errors="coerce").eq(1),
        winner_margin,
        -winner_margin,
    )
    return out


def run(base_dir: str | Path = ".") -> dict:
    base = Path(base_dir)
    matchup_path = base / "v5_tournament_challenger_diagnostic" / "matched_authority_rows.parquet"
    matches_path = base / "context_warehouse" / "matches.parquet"
    if not matchup_path.exists():
        raise FileNotFoundError("Run diagnose_v5_tournament_challenger.py first")
    if not matches_path.exists():
        raise FileNotFoundError("context_warehouse/matches.parquet missing")

    frame = _attach_scores(pd.read_parquet(matchup_path), pd.read_parquet(matches_path))
    report = {
        "diagnostic_version": "v5-tournament-authority-score-challenger-1",
        "authority_contract": "new tournament authority only; no retired court fallback",
        "fit_year": 2025,
        "validation_year": 2026,
        "market_prices_used": False,
        "completed_score_rows": int(len(frame)),
        "tours": {},
    }
    for tour in ("MEN", "WTA"):
        tour_frame = frame[frame["tour"].astype(str).str.upper().eq(tour)].copy()
        result = evaluate_score_challenger_frame(tour_frame, fit_year=2025, validation_year=2026)
        result["status"] = "evaluated"
        report["tours"][tour] = result

    groups = sorted(set().union(*(set(v.get("eligibility", {}).keys()) for v in report["tours"].values())))
    report["cross_tour_eligibility"] = {
        group: {
            outcome: {tour: bool(report["tours"][tour].get("eligibility", {}).get(group, {}).get(outcome, False)) for tour in ("MEN", "WTA")}
            for outcome in ("spread", "total", "both")
        }
        for group in groups
    }

    out = base / OUTDIR
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(report, indent=2, allow_nan=False))
    return report


if __name__ == "__main__":
    run(".")
