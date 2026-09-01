from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from historical_score_calibration import build_result_index, load_historical_results, matched_walkforward_scores
from v5_core import logistic, logit, simulate_match
from v5_daily_batch import infer_best_of
from v5_model_calibration import calibrated_match_probability
from v5_strength_conditioning import condition_serve_pair_to_match_probability

OUT = Path("v5_daily_ready/joint_score_calibration_diagnostic.json")
OFFSETS = [-0.36, -0.27, -0.18, -0.09, 0.0]
DOMINANCE_MULTIPLIERS = [0.75, 1.0, 1.25, 1.5, 1.75]
SEARCH_SIMS = 100
SEARCH_ITERATIONS = 7
FINAL_SIMS = 140
LIMIT = 260
SPREAD_LINES = [x + 0.5 for x in range(-13, 13)]
TOTAL_LINES_BO3 = [x + 0.5 for x in range(14, 36)]
TOTAL_LINES_BO5 = [x + 0.5 for x in range(24, 56)]


def _load_walkforward(tour):
    path = Path("v5_wta_walkforward.csv" if tour == "WTA" else "v5_men_walkforward.csv")
    df = pd.read_csv(path, low_memory=False)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    return df[df["date"].dt.year.isin([2025, 2026])].copy()


def _segment(row, tour):
    best_of = infer_best_of(row.get("tournament"), tour)
    return "MEN_BO5" if tour == "MEN" and best_of == 5 else ("MEN_BO3" if tour == "MEN" else "WTA_BO3")


def _sample(frame, year, seed):
    x = frame[frame["date"].dt.year == year].copy()
    if len(x) <= LIMIT:
        return x.sort_values("date").reset_index(drop=True)
    return x.sample(n=LIMIT, random_state=seed).sort_values("date").reset_index(drop=True)


def _prepare(frame, tour, seed_base):
    rows=[]
    for i,(_,row) in enumerate(frame.iterrows()):
        target=calibrated_match_probability(row["winner_serve_p"],row["loser_serve_p"],row["elo_winner_p"],tour)
        best_of=infer_best_of(row.get("tournament"),tour)
        p1,p2,meta=condition_serve_pair_to_match_probability(
            row["winner_serve_p"],row["loser_serve_p"],target,
            best_of=best_of,n=SEARCH_SIMS,seed=seed_base+i,max_iter=SEARCH_ITERATIONS,
        )
        rows.append({**row.to_dict(),"conditioned_p1":p1,"conditioned_p2":p2,"target_probability":target,"best_of":best_of,"conditioning_achieved":meta["achieved_probability"]})
    return pd.DataFrame(rows)


def _candidate_pair(p1,p2,offset,multiplier):
    e1=logit(p1);e2=logit(p2)
    mean=(e1+e2)/2.0 + float(offset)
    diff=(e1-e2)*float(multiplier)
    return logistic(mean+diff/2.0),logistic(mean-diff/2.0)


def _float_map(mapping):
    return {float(k):float(v) for k,v in mapping.items()}


def _evaluate(prepared,offset,multiplier,seed_base):
    margin_errors=[];total_errors=[];expected_margin_errors=[];expected_total_errors=[];raw_p_miss=[]
    for i,(_,row) in enumerate(prepared.iterrows()):
        p1,p2=_candidate_pair(row["conditioned_p1"],row["conditioned_p2"],offset,multiplier)
        total_lines=TOTAL_LINES_BO5 if int(row["best_of"])==5 else TOTAL_LINES_BO3
        result=simulate_match(
            p1,p2,best_of=int(row["best_of"]),n=FINAL_SIMS,seed=seed_base+i,
            state_variation=False,target_pA_win=float(row["target_probability"]),
            spread_lines=SPREAD_LINES,total_lines=total_lines,
        )
        spreads=_float_map(result["spread"]);overs=_float_map(result["over"])
        actual_margin=float(row["actual_margin"]);actual_total=float(row["actual_total"])
        for line in SPREAD_LINES:
            pred=spreads[line];obs=1.0 if actual_margin+line>0 else 0.0
            margin_errors.append((pred-obs)**2)
        for line in total_lines:
            pred=overs[line];obs=1.0 if actual_total>line else 0.0
            total_errors.append((pred-obs)**2)
        expected_margin_errors.append(float(result["expected_margin"])-actual_margin)
        expected_total_errors.append(float(result["expected_total"])-actual_total)
        raw_p_miss.append(abs(float(result["raw_pA_win"])-float(row["target_probability"])))
    me=np.asarray(expected_margin_errors);te=np.asarray(expected_total_errors)
    margin_brier=float(np.mean(margin_errors)) if margin_errors else None
    total_brier=float(np.mean(total_errors)) if total_errors else None
    return {
        "n":int(len(prepared)),
        "margin_cdf_brier":margin_brier,
        "total_cdf_brier":total_brier,
        "joint_score":None if margin_brier is None or total_brier is None else (margin_brier+total_brier)/2.0,
        "margin_mean_error_games":float(me.mean()) if len(me) else None,
        "margin_rmse_games":float(np.sqrt(np.mean(me**2))) if len(me) else None,
        "total_mean_error_games":float(te.mean()) if len(te) else None,
        "total_rmse_games":float(np.sqrt(np.mean(te**2))) if len(te) else None,
        "mean_raw_probability_miss_pp_before_final_weight":float(np.mean(raw_p_miss)*100) if raw_p_miss else None,
    }


def main():
    results,loaded,missing=load_historical_results((2025,2026));lookup=build_result_index(results)
    payload={
        "method":{
            "fit_year":2025,"validation_year":2026,"market_prices_used":False,
            "objective":"mean of margin-CDF and total-CDF Brier scores across fixed half-game thresholds",
            "interpretation":"proper distribution scoring across synthetic thresholds; no sportsbook spreads or totals enter fitting",
            "offsets":OFFSETS,"dominance_multipliers":DOMINANCE_MULTIPLIERS,
            "search_simulations":SEARCH_SIMS,"final_simulations":FINAL_SIMS,"sample_per_segment_per_year":LIMIT,
        },
        "score_files_loaded":loaded,"score_files_missing":missing,"segments":{}
    }
    segment_frames={}
    for tour in ("MEN","WTA"):
        matched=matched_walkforward_scores(_load_walkforward(tour),lookup)
        if matched.empty:continue
        matched["segment"]=matched.apply(lambda r:_segment(r,tour),axis=1)
        for segment,group in matched.groupby("segment"):segment_frames[segment]=(tour,group.copy())

    for segment,(tour,frame) in segment_frames.items():
        train=_prepare(_sample(frame,2025,2025),tour,100000)
        valid=_prepare(_sample(frame,2026,2026),tour,700000)
        candidates={}
        for oi,offset in enumerate(OFFSETS):
            for mi,mult in enumerate(DOMINANCE_MULTIPLIERS):
                key=f"offset={offset:+.2f}|dominance={mult:.2f}"
                candidates[key]=_evaluate(train,offset,mult,200000)
        eligible=[(key,val) for key,val in candidates.items() if val["joint_score"] is not None]
        selected_key,selected_metrics=min(eligible,key=lambda item:item[1]["joint_score"])
        parts=dict(piece.split("=") for piece in selected_key.split("|"))
        selected_offset=float(parts["offset"]);selected_mult=float(parts["dominance"])
        validation_selected=_evaluate(valid,selected_offset,selected_mult,800000)
        validation_baseline=_evaluate(valid,0.0,1.0,900000)
        payload["segments"][segment]={
            "available_2025":int((frame["date"].dt.year==2025).sum()),"available_2026":int((frame["date"].dt.year==2026).sum()),
            "sample_2025":int(len(train)),"sample_2026":int(len(valid)),
            "selected_from_2025":{"offset":selected_offset,"dominance_multiplier":selected_mult,"train_metrics":selected_metrics},
            "validation_2026_selected":validation_selected,"validation_2026_baseline":validation_baseline,
            "validation_joint_score_improvement":validation_baseline["joint_score"]-validation_selected["joint_score"],
            "candidate_scores":candidates,
        }
    OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(payload,indent=2,default=str),encoding="utf-8");print(json.dumps(payload,indent=2,default=str))


if __name__=="__main__":main()
