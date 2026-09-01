from __future__ import annotations

import json
import math
import re
from pathlib import Path

import numpy as np
import pandas as pd

from v5_core import logistic, logit, simulate_match
from v5_daily_batch import infer_best_of
from v5_model_calibration import calibrated_match_probability
from v5_settlement import VOID_MARKERS, canonical_name, load_tennismylife_results, parse_score_games

OUT = Path("v5_daily_ready/total_length_calibration_diagnostic.json")
CANDIDATE_OFFSETS = [-0.12, -0.09, -0.06, -0.03, 0.0, 0.03, 0.06]
SIMS = 160
SAMPLE = {"MEN": 700, "WTA": 450}


def _date(value):
    text = str(value or "").split(".")[0]
    if re.fullmatch(r"\d{8}", text):
        parsed = pd.to_datetime(text, format="%Y%m%d", errors="coerce")
    else:
        parsed = pd.to_datetime(value, errors="coerce")
    return "" if pd.isna(parsed) else parsed.date().isoformat()


def _result_key(date, winner, loser):
    return (_date(date), canonical_name(winner), canonical_name(loser))


def _score_total(score):
    text = str(score or "")
    if any(marker in text.upper() for marker in VOID_MARKERS):
        return None
    parsed = parse_score_games(text)
    return None if parsed is None else int(parsed[0] + parsed[1])


def _result_index(results):
    out = {}
    for _, r in results.iterrows():
        total = _score_total(r.get("score"))
        if total is None:
            continue
        key = _result_key(r.get("tourney_date"), r.get("winner_name"), r.get("loser_name"))
        item = {"actual_total": total, "tournament": r.get("tourney_name") or r.get("tournament") or "", "score": r.get("score")}
        if key in out and out[key] != item:
            out[key] = None
        else:
            out[key] = item
    return out


def _load_walkforward(tour):
    path = Path("v5_wta_walkforward.csv" if tour == "WTA" else "v5_men_walkforward.csv")
    df = pd.read_csv(path, low_memory=False)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    return df[df["date"].dt.year.isin([2025, 2026])].copy()


def _matched_rows(tour, result_lookup):
    wf = _load_walkforward(tour)
    rows = []
    for _, r in wf.iterrows():
        key = _result_key(r.get("date"), r.get("winner"), r.get("loser"))
        result = result_lookup.get(key)
        if not result:
            continue
        try:
            pw=float(r.get("winner_serve_p")); pl=float(r.get("loser_serve_p")); pe=float(r.get("elo_winner_p"))
        except Exception:
            continue
        if not all(math.isfinite(x) and 0 < x < 1 for x in (pw,pl,pe)):
            continue
        rows.append({"date":pd.Timestamp(r.get("date")),"surface":str(r.get("surface") or "Hard"),"winner_serve_p":pw,"loser_serve_p":pl,"elo_winner_p":pe,"actual_total":int(result["actual_total"]),"tournament":result["tournament"]})
    return pd.DataFrame(rows)


def _sample(frame,n,seed):
    if len(frame)<=n:return frame.sort_values("date").reset_index(drop=True)
    return frame.sample(n=n,random_state=seed).sort_values("date").reset_index(drop=True)


def _predict_row(row,tour,offset,seed):
    p1=logistic(logit(row["winner_serve_p"])+offset)
    p2=logistic(logit(row["loser_serve_p"])+offset)
    target=calibrated_match_probability(row["winner_serve_p"],row["loser_serve_p"],row["elo_winner_p"],tour)
    best_of=infer_best_of(row.get("tournament"),tour)
    result=simulate_match(p1,p2,best_of=best_of,n=SIMS,seed=seed,state_variation=False,target_pA_win=target,spread_lines=[],total_lines=[])
    return float(result["expected_total"])


def _evaluate(frame,tour,offset,seed_base):
    actual=[];predicted=[]
    for i,(_,row) in enumerate(frame.iterrows()):
        actual.append(float(row["actual_total"]));predicted.append(_predict_row(row,tour,offset,seed_base+i))
    a=np.asarray(actual);p=np.asarray(predicted);err=p-a
    return {"n":int(len(a)),"mean_actual_total":float(a.mean()) if len(a) else None,"mean_predicted_total":float(p.mean()) if len(p) else None,"mean_error_games":float(err.mean()) if len(err) else None,"mae_games":float(np.abs(err).mean()) if len(err) else None,"rmse_games":float(np.sqrt(np.mean(err**2))) if len(err) else None}


def main():
    results=load_tennismylife_results();lookup=_result_index(results)
    payload={"method":{"fit_year":2025,"validation_year":2026,"inputs":"TennisMyLife completed scores + pre-match V5 serve/return and surface Elo only","market_prices_used":False,"parameter":"common offset added to both players' serve logits; relative serve differential unchanged","candidate_offsets":CANDIDATE_OFFSETS,"simulations_per_match":SIMS},"tours":{}}
    for tour in ("MEN","WTA"):
        matched=_matched_rows(tour,lookup)
        if matched.empty:
            payload["tours"][tour]={"error":"no matched completed scores"};continue
        train=_sample(matched[matched["date"].dt.year==2025],SAMPLE[tour],2025)
        valid=_sample(matched[matched["date"].dt.year==2026],SAMPLE[tour],2026)
        train_metrics={}
        for j,offset in enumerate(CANDIDATE_OFFSETS):
            train_metrics[str(offset)]=_evaluate(train,tour,offset,100000+j*10000)
        eligible=[(float(k),v) for k,v in train_metrics.items() if v["rmse_games"] is not None]
        if not eligible:
            payload["tours"][tour]={"error":"no evaluable 2025 score rows"};continue
        best_offset=min(eligible,key=lambda kv:kv[1]["rmse_games"])[0]
        validation=_evaluate(valid,tour,best_offset,900000)
        baseline_validation=_evaluate(valid,tour,0.0,800000)
        payload["tours"][tour]={
            "matched_2025_total":int((matched["date"].dt.year==2025).sum()),"matched_2026_total":int((matched["date"].dt.year==2026).sum()),
            "sample_2025":int(len(train)),"sample_2026":int(len(valid)),"train_candidates":train_metrics,"selected_offset_from_2025":best_offset,
            "validation_2026_selected":validation,"validation_2026_zero_offset":baseline_validation,
            "validation_rmse_improvement_games":baseline_validation["rmse_games"]-validation["rmse_games"] if baseline_validation["rmse_games"] is not None and validation["rmse_games"] is not None else None,
        }
    OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(payload,indent=2,default=str),encoding="utf-8");print(json.dumps(payload,indent=2,default=str))


if __name__=="__main__":main()
