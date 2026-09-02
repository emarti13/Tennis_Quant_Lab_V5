from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

from v5_score_distribution import predict_score_distribution
from v5_score_walkforward import (
    distribution_metrics,
    fit_gaussian_score_model,
    parse_completed_score,
    predict_gaussian_score_model,
    score_candidate_gate,
)

OUTDIR = "v5_score_diagnostic"


def _attach_scores(matchups: pd.DataFrame, matches: pd.DataFrame) -> pd.DataFrame:
    scores = matches[["match_id", "score"]].drop_duplicates("match_id").copy()
    parsed = scores["score"].map(parse_completed_score).apply(pd.Series)
    scores = pd.concat([scores, parsed], axis=1)
    scores = scores[scores["completed"].eq(True)].copy()
    out = matchups.merge(scores[["match_id", "winner_games", "loser_games", "total_games", "winner_margin", "sets"]], on="match_id", how="inner", validate="one_to_one")
    out["actual_total"] = pd.to_numeric(out["total_games"], errors="coerce")
    winner_margin = pd.to_numeric(out["winner_margin"], errors="coerce")
    out["actual_margin_a"] = np.where(pd.to_numeric(out["target_a_win"], errors="coerce").eq(1), winner_margin, -winner_margin)
    return out


def _deterministic_cap(frame: pd.DataFrame, max_rows: int | None) -> pd.DataFrame:
    """Evenly sample a chronological frame without peeking at outcomes.

    This is used only to bound the expensive mechanistic replay. The direct model
    still fits on all available 2025 rows; candidate metrics are compared on the
    exact same untouched 2026 rows selected here.
    """
    ordered = frame.copy()
    ordered["match_date"] = pd.to_datetime(ordered.get("match_date"), errors="coerce")
    sort_cols = [c for c in ("match_date", "match_id") if c in ordered.columns]
    if sort_cols:
        ordered = ordered.sort_values(sort_cols, kind="stable")
    ordered = ordered.reset_index(drop=True)
    limit = int(max_rows or 0)
    if limit <= 0 or len(ordered) <= limit:
        return ordered
    positions = np.linspace(0, len(ordered) - 1, num=limit)
    indices = np.unique(np.rint(positions).astype(int))
    return ordered.iloc[indices].reset_index(drop=True)


def _mechanistic_predictions(frame: pd.DataFrame, *, simulations: int) -> dict[str, np.ndarray]:
    margins=[]; totals=[]; margin_sd=[]; total_sd=[]
    for i, row in frame.reset_index(drop=True).iterrows():
        score = predict_score_distribution(
            {
                "serve_probability_p1": float(row["serve_probability_a"]),
                "serve_probability_p2": float(row["serve_probability_b"]),
                "winner_probability_p1": float(row["baseline_a_probability"]),
                "best_of": int(pd.to_numeric(pd.Series([row.get("best_of", 3)]), errors="coerce").fillna(3).iloc[0]),
                "spread_lines": [], "total_lines": [],
            },
            {"model_type": "conditioned_mechanistic", "simulations": int(simulations), "conditioning_simulations": max(80, int(simulations)//2), "conditioning_max_iter": 6, "seed": 1000 + i},
        )
        margins.append(score.expected_margin); totals.append(score.expected_total); margin_sd.append(score.margin_sd); total_sd.append(score.total_sd)
    return {
        "margin_mean": np.asarray(margins, dtype=float), "margin_sd": np.asarray(margin_sd, dtype=float),
        "total_mean": np.asarray(totals, dtype=float), "total_sd": np.asarray(total_sd, dtype=float),
    }


def _segment_metrics(frame: pd.DataFrame, prediction: dict[str, np.ndarray]) -> dict:
    out={}
    best_of = pd.to_numeric(frame["best_of"], errors="coerce").fillna(3).astype(int).to_numpy()
    for value in (3,5):
        mask = best_of == value
        if not mask.any():
            out[f"bo{value}"] = {"n":0}
            continue
        sliced={k:np.asarray(v)[mask] for k,v in prediction.items()}
        out[f"bo{value}"] = distribution_metrics(frame.loc[mask,"actual_margin_a"], frame.loc[mask,"actual_total"], sliced)
    return out


def _feature_columns(frame: pd.DataFrame) -> list[str]:
    base=[c for c in ("x_sr_a","x_elo_a") if c in frame.columns]
    ctx=[c for c in frame.columns if c.startswith("ctx_")]
    keep=[]
    for col in base+ctx:
        values=pd.to_numeric(frame[col],errors="coerce")
        finite=values[np.isfinite(values)]
        if len(finite) and finite.nunique()>1:
            keep.append(col)
    return keep


def evaluate_tour(frame: pd.DataFrame, tour: str, *, simulations: int, max_validation_rows: int | None = None, max_hybrid_train_rows: int | None = None) -> dict:
    train=frame[pd.to_numeric(frame["year"],errors="coerce").eq(2025)].copy().reset_index(drop=True)
    valid_full=frame[pd.to_numeric(frame["year"],errors="coerce").eq(2026)].copy().reset_index(drop=True)
    if len(train)<50 or len(valid_full)<50:
        return {"status":"insufficient_rows","train_rows":int(len(train)),"validation_rows":int(len(valid_full))}
    features=_feature_columns(train)
    direct_model=fit_gaussian_score_model(train,features=features,l2=16.0)

    valid=_deterministic_cap(valid_full,max_validation_rows)
    direct_valid=predict_gaussian_score_model(direct_model,valid)
    mech_valid=_mechanistic_predictions(valid,simulations=simulations)
    mech_metrics=distribution_metrics(valid["actual_margin_a"],valid["actual_total"],mech_valid)
    direct_metrics=distribution_metrics(valid["actual_margin_a"],valid["actual_total"],direct_valid)

    hybrid_limit = max_hybrid_train_rows if max_hybrid_train_rows is not None else 4000
    hybrid_train=_deterministic_cap(train,hybrid_limit)
    mech_train=_mechanistic_predictions(hybrid_train,simulations=simulations)
    hybrid_train["mechanistic_margin_a"] = mech_train["margin_mean"]
    hybrid_features=features+["mechanistic_margin_a"]
    hybrid_model=fit_gaussian_score_model(hybrid_train,features=hybrid_features,l2=16.0)
    valid_hybrid=valid.copy(); valid_hybrid["mechanistic_margin_a"] = mech_valid["margin_mean"]
    hybrid_valid=predict_gaussian_score_model(hybrid_model,valid_hybrid)
    hybrid_metrics=distribution_metrics(valid["actual_margin_a"],valid["actual_total"],hybrid_valid)

    gates={
        "gaussian_contextual":score_candidate_gate(mech_metrics,direct_metrics),
        "gaussian_hybrid":score_candidate_gate(mech_metrics,hybrid_metrics),
    }
    eligible=[name for name,gate in gates.items() if gate["accepted"]]
    metric_map={"conditioned_mechanistic":mech_metrics,"gaussian_contextual":direct_metrics,"gaussian_hybrid":hybrid_metrics}
    selected=min(eligible,key=lambda n:(metric_map[n]["margin_crps"]+metric_map[n]["total_crps"],metric_map[n]["margin_rmse"]+metric_map[n]["total_rmse"])) if eligible else "conditioned_mechanistic"
    pred_map={"conditioned_mechanistic":mech_valid,"gaussian_contextual":direct_valid,"gaussian_hybrid":hybrid_valid}
    return {
        "status":"evaluated","tour":tour,"train_rows":int(len(train)),"validation_rows_full":int(len(valid_full)),"validation_rows":int(len(valid)),"features":features,
        "diagnostic_simulations_per_match":int(simulations),
        "validation_sampling":{"policy":"chronological_even_spacing","max_rows":None if not max_validation_rows else int(max_validation_rows),"full_rows":int(len(valid_full)),"scored_rows":int(len(valid))},
        "hybrid_training_sampling":{"policy":"chronological_even_spacing","max_rows":None if not hybrid_limit else int(hybrid_limit),"full_rows":int(len(train)),"scored_rows":int(len(hybrid_train))},
        "metrics_2026":metric_map,"gates_vs_conditioned_mechanistic":gates,
        "selected_candidate":selected,"selected_metrics_2026":metric_map[selected],
        "bo3_bo5_selected_metrics":_segment_metrics(valid,pred_map[selected]),
        "bo3_bo5_mechanistic_metrics":_segment_metrics(valid,mech_valid),
        "direct_model":direct_model,"hybrid_model":hybrid_model,
    }


def run(base_dir: str | Path = ".") -> dict:
    base=Path(base_dir); matchup_path=base/"v5_context_diagnostic"/"matched_context_rows.parquet"; matches_path=base/"context_warehouse"/"matches.parquet"
    if not matchup_path.exists(): raise FileNotFoundError("Run diagnose_v5_context_model.py first")
    if not matches_path.exists(): raise FileNotFoundError("context_warehouse/matches.parquet missing")
    frame=_attach_scores(pd.read_parquet(matchup_path),pd.read_parquet(matches_path))
    simulations=max(80,int(os.getenv("V5_SCORE_DIAGNOSTIC_SIMS","160")))
    max_validation_rows=max(0,int(os.getenv("V5_SCORE_MAX_VALIDATION_ROWS","0"))) or None
    max_hybrid_train_rows=max(0,int(os.getenv("V5_SCORE_MAX_HYBRID_TRAIN_ROWS","0"))) or None
    report={"version":"v5-score-walkforward-2","fit_year":2025,"validation_year":2026,"market_prices_used":False,"completed_score_rows":int(len(frame)),"tours":{}}
    production={"version":report["version"],"market_prices_used":False}
    for tour in ("MEN","WTA"):
        result=evaluate_tour(
            frame[frame["tour"].astype(str).str.upper().eq(tour)].copy(),
            tour,
            simulations=simulations,
            max_validation_rows=max_validation_rows,
            max_hybrid_train_rows=max_hybrid_train_rows,
        )
        report["tours"][tour]=result
        selected=result.get("selected_candidate","conditioned_mechanistic")
        model=None
        if selected=="gaussian_contextual": model=result.get("direct_model")
        elif selected=="gaussian_hybrid": model=result.get("hybrid_model")
        production[tour]={"selected_candidate":selected,"model":model,"validation_metrics":result.get("selected_metrics_2026"),"bo3_bo5_metrics":result.get("bo3_bo5_selected_metrics"),"validation_sampling":result.get("validation_sampling")}
    out=base/OUTDIR; out.mkdir(parents=True,exist_ok=True)
    (out/"report.json").write_text(json.dumps(report,indent=2,allow_nan=False),encoding="utf-8")
    (out/"production_candidate.json").write_text(json.dumps(production,indent=2,allow_nan=False),encoding="utf-8")
    print(json.dumps({"version":report["version"],"completed_score_rows":report["completed_score_rows"],"selection":{t:production[t]["selected_candidate"] for t in ("MEN","WTA")},"validation_sampling":{t:production[t].get("validation_sampling") for t in ("MEN","WTA")}},indent=2))
    return report


if __name__=="__main__":
    run(".")
