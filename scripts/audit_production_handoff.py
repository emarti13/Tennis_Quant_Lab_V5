#!/usr/bin/env python3
from pathlib import Path
import json, math, re, unicodedata
import numpy as np
import pandas as pd

BASE=Path(__file__).resolve().parents[1]
H=BASE/"v5_daily_ready"/"market_snapshot_history.csv"
F=BASE/"v5_daily_ready"/"frozen_predictions.csv"
C=BASE/"experiments"/"acceptance"/"production_candidate.json"
OUT=BASE/"exports"/"production_handoff_audit.json"

def cn(s):
    s="" if s is None else str(s)
    if "," in s:
        a,b=[x.strip() for x in s.split(",",1)]
        if a and b:s=f"{b} {a}"
    s=unicodedata.normalize("NFKD",s)
    s="".join(ch for ch in s if not unicodedata.combining(ch)).lower()
    return " ".join(re.sub(r"[^a-z0-9]+"," ",s).split())

def logit(p):
    p=min(max(float(p),1e-8),1-1e-8)
    return math.log(p/(1-p))
def logistic(x): return 1/(1+math.exp(-max(min(x,35),-35)))

cand=json.loads(C.read_text())
hist=pd.read_csv(H,low_memory=False)
fro=pd.read_csv(F,low_memory=False)

# settled fixture truth
sf=fro[(fro.get("result_status","").astype(str).str.upper()=="SETTLED") & fro.get("result_winner","").fillna("").astype(str).str.strip().ne("")].copy()
truth={}
for fid,g in sf.groupby("fixture_id"):
    truth[str(fid)]={
      "winner":str(g["result_winner"].dropna().iloc[0]),
      "loser":str(g["result_loser"].dropna().iloc[0]) if g["result_loser"].notna().any() else "",
      "score":str(g["result_score"].dropna().iloc[0]) if g["result_score"].notna().any() else ""
    }

m=hist[hist["market_group"].astype(str).str.lower().eq("moneyline")].copy()
m["snap"]=pd.to_datetime(m["snapshot_utc"],errors="coerce",utc=True)
m["start"]=pd.to_datetime(m["start_time_utc"],errors="coerce",utc=True)
m=m[m["snap"].notna() & m["start"].notna() & (m["snap"]<m["start"])].copy()
m["fid"]=m["fixture_id"].astype(str)
m["selkey"]=m["selection"].map(cn)
m["p1key"]=m["player1"].map(cn)
m["p2key"]=m["player2"].map(cn)
m=m[m["fid"].isin(truth)].copy()

# use earliest complete two-sided snapshot per fixture
cnt=m.groupby(["fid","snap"])["selkey"].nunique().reset_index(name="n")
first=cnt[cnt.n>=2].sort_values(["fid","snap"]).drop_duplicates("fid")[["fid","snap"]]
m=m.merge(first,on=["fid","snap"],how="inner")

def num(r,k):
    try:
      x=float(r.get(k))
      return x if math.isfinite(x) else None
    except: return None

def contribs(row, model, include_base=False):
    names=model.get("feature_names",[])
    scales=np.asarray(model.get("scales",model.get("scales",[])),dtype=float)
    co=np.asarray(model.get("coefficients",[]),dtype=float)
    if len(names)!=len(co): return []
    out=[]
    for i,n in enumerate(names):
      x=num(row,n)
      if x is None: x=0.0
      sc=float(scales[i]) if i<len(scales) and math.isfinite(scales[i]) and abs(scales[i])>1e-12 else 1.0
      z=x/sc
      c=z*float(co[i])
      out.append({"feature":n,"value":x,"scale":sc,"z":z,"coefficient":float(co[i]),"logit_contribution":c})
    return sorted(out,key=lambda x:abs(x["logit_contribution"]),reverse=True)

rows=[]
for fid,g in m.groupby("fid"):
    if len(g)<2: continue
    # one p1-oriented record, using whichever side row equals player1
    r1=None
    for _,r in g.iterrows():
      if cn(r.get("selection"))==cn(r.get("player1")):
        r1=r; break
    if r1 is None: continue
    p1=str(r1.get("player1") or ""); p2=str(r1.get("player2") or "")
    winner=truth[fid]["winner"]; y=1 if cn(winner)==cn(p1) else 0 if cn(winner)==cn(p2) else None
    if y is None: continue
    tour="WTA" if str(r1.get("tour_v5") or r1.get("tour") or "").upper()=="WTA" else "MEN"
    p_final=num(r1,"model_probability"); p_base=num(r1,"accepted_baseline_probability_p1"); p_elo=num(r1,"elo_probability_p1")
    p_ctx=num(r1,"full_context_probability_p1")
    q=num(r1,"consensus_no_vig_prob")
    if cn(r1.get("selection"))!=cn(p1):
      q=1-q if q is not None else None
    bundle=cand[tour]
    direct=contribs(r1,bundle.get("direct_context_model") or {})
    residual=contribs(r1,bundle.get("residual_model") or {})
    rows.append({
      "fixture_id":fid,"start_time_utc":str(r1.get("start_time_utc")),"tournament":str(r1.get("tournament")),
      "tour":tour,"player1":p1,"player2":p2,"winner":winner,"player1_won":y,
      "market_p1":q,"accepted_baseline_p1":p_base,"elo_p1":p_elo,"full_context_p1":p_ctx,"final_v5_p1":p_final,
      "selected_candidate":str(r1.get("selected_model_candidate") or ""),
      "context_fallback_reason":str(r1.get("context_fallback_reason") or ""),
      "max_abs_direct_z":max([abs(x["z"]) for x in direct],default=0),
      "max_abs_residual_z":max([abs(x["z"]) for x in residual],default=0),
      "top_direct_contributions":direct[:8],
      "top_residual_contributions":residual[:8],
    })

df=pd.DataFrame(rows)
def metrics(frame,col):
    x=pd.to_numeric(frame[col],errors="coerce"); y=pd.to_numeric(frame["player1_won"],errors="coerce")
    ok=x.notna()&y.notna()
    if not ok.any():return {"n":0}
    p=x[ok].clip(1e-8,1-1e-8); yy=y[ok]
    return {"n":int(ok.sum()),"brier":float(((p-yy)**2).mean()),"accuracy":float(((p>=.5)==(yy>=.5)).mean())}

report={"n":int(len(df)),"overall":{},"cutoffs":{},"extremes":[],"candidate":{}}
for col in ["market_p1","accepted_baseline_p1","elo_p1","full_context_p1","final_v5_p1"]:
    report["overall"][col]=metrics(df,col)
starts=pd.to_datetime(df["start_time_utc"],errors="coerce",utc=True)
for cut in ["2026-09-21","2026-09-28","2026-10-01","2026-10-05","2026-10-07"]:
    sub=df[starts>=pd.Timestamp(cut,tz="UTC")]
    report["cutoffs"][cut]={col:metrics(sub,col) for col in ["market_p1","accepted_baseline_p1","elo_p1","full_context_p1","final_v5_p1"]}
    report["cutoffs"][cut]["n"]=int(len(sub))

df["gap"]=(pd.to_numeric(df["final_v5_p1"],errors="coerce")-pd.to_numeric(df["market_p1"],errors="coerce")).abs()
for _,r in df.sort_values("gap",ascending=False).head(30).iterrows():
    item={}
    for k in [
      "fixture_id","start_time_utc","tournament","tour","player1","player2","winner","player1_won",
      "market_p1","accepted_baseline_p1","elo_p1","full_context_p1","final_v5_p1","gap",
      "selected_candidate","context_fallback_reason","max_abs_direct_z","max_abs_residual_z",
      "top_direct_contributions","top_residual_contributions"
    ]:
        v=r[k]
        if isinstance(v,(list,dict)):
            item[k]=v
        else:
            item[k]=None if pd.isna(v) else v
    report["extremes"].append(item)

for tour in ["MEN","WTA"]:
    b=cand[tour]
    report["candidate"][tour]={
      "selected_candidate":b.get("selected_candidate"),
      "stack_weights":(b.get("stack_model") or {}).get("weights"),
      "uncertainty_gamma":(b.get("uncertainty_model") or {}).get("gamma"),
      "direct_training_rows":(b.get("direct_context_model") or {}).get("training_rows"),
      "residual_training_rows":(b.get("residual_model") or {}).get("training_rows")
    }

OUT.parent.mkdir(exist_ok=True)
OUT.write_text(json.dumps(report,indent=2,default=str))
print(json.dumps({"n":report["n"],"overall":report["overall"],"cutoffs":report["cutoffs"],"top5":report["extremes"][:5]},indent=2,default=str))
