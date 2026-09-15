from __future__ import annotations
import gzip,json
from pathlib import Path
import pandas as pd
from historical_odds_normalizer import flatten_history,select_snapshot
from historical_market_mapper import map_snapshot_rows
from historical_fixture_matcher import canonical_name
from diagnose_v5_score_distribution import _attach_scores,_feature_columns,_mechanistic_predictions
from v5_score_walkforward import fit_gaussian_score_model,predict_gaussian_score_model,distribution_metrics,score_candidate_gate
from consensus_line_analysis import consensus_spread,consensus_total

OUT=Path('experiments/acceptance/consensus_lines_2026_report.json')

def key(date,a,b): return (pd.Timestamp(date).date().isoformat(),tuple(sorted((canonical_name(a),canonical_name(b)))))
def histories():
 for p in sorted(Path('oddspapi_history/chunks').glob('history_chunk_*.jsonl.gz')):
  with gzip.open(p,'rt',encoding='utf-8') as f:
   for s in f:
    if s.strip(): yield json.loads(s)
def predictions():
 m=pd.read_parquet('v5_context_diagnostic/matched_context_rows.parquet'); scores=pd.read_parquet('context_warehouse/matches.parquet'); f=_attach_scores(m,scores); out=[]
 for tour in ('MEN','WTA'):
  x=f[f.tour.astype(str).str.upper().eq(tour)].copy(); tr=x[pd.to_numeric(x.year,errors='coerce').eq(2025)]; va=x[pd.to_numeric(x.year,errors='coerce').eq(2026)].copy(); feats=_feature_columns(tr)
  d=fit_gaussian_score_model(tr,features=feats,l2=16.0); dp=predict_gaussian_score_model(d,va); mp=_mechanistic_predictions(va,simulations=80); gate=score_candidate_gate(distribution_metrics(va.actual_margin_a,va.actual_total,mp),distribution_metrics(va.actual_margin_a,va.actual_total,dp)); p=dp if gate['accepted'] else mp
  va['pred_margin_a']=p['margin_mean']; va['pred_total']=p['total_mean']; va['tour_eval']=tour; out.append(va)
 return pd.concat(out,ignore_index=True)
def summary(df):
 o={}
 if df.empty:
  return {label:{'fixtures':0,'decisions':0,'wins':0,'losses':0,'pushes':0,'accuracy':None} for label in ('ALL','MEN','WTA')}
 for label,s in [('ALL',df),('MEN',df[df['tour'].eq('MEN')]),('WTA',df[df['tour'].eq('WTA')])]:
  d=s[~s.outcome.eq('PUSH')]; o[label]={'fixtures':int(s.fixture_id.nunique()),'decisions':int(len(d)),'wins':int(d.outcome.eq('WIN').sum()),'losses':int(d.outcome.eq('LOSS').sum()),'pushes':int(s.outcome.eq('PUSH').sum()),'accuracy':float(d.outcome.eq('WIN').mean()) if len(d) else None}
 return o
def main():
 meta=json.loads(Path('oddspapi_markets_tennis.json').read_text()); pred=predictions(); idx={}
 for i,r in pred.iterrows(): idx.setdefault(key(r.match_date,r.player_a,r.player_b),[]).append(i)
 spreads=[]; totals=[]
 for rec in histories():
  fixture=rec.get('fixture'); payload=rec.get('historical_odds') or {}
  if not fixture or not payload: continue
  ids=idx.get(key(fixture.get('startTime'),fixture.get('participant1Name'),fixture.get('participant2Name')),[])
  if len(ids)!=1: continue
  r=pred.loc[ids[0]]; fid=str(payload.get('fixtureId') or fixture.get('fixtureId')); mapped=map_snapshot_rows(select_snapshot(flatten_history(payload),start_time=fixture['startTime'],closing=True),fixture,meta)
  for x in mapped:
   if x.get('line') is None: continue
   if x.get('market_group')=='game_spread': spreads.append({'fixture_id':fid,'tour':r.tour_eval,'selection':x.get('selection'),'player_a':r.player_a,'line':float(x['line']),'pred_margin_a':float(r.pred_margin_a),'actual_margin_a':float(r.actual_margin_a)})
   elif x.get('market_group')=='total_games': totals.append({'fixture_id':fid,'tour':r.tour_eval,'line':float(x['line']),'pred_total':float(r.pred_total),'actual_total':float(r.actual_total)})
 cs=consensus_spread(pd.DataFrame(spreads)); ct=consensus_total(pd.DataFrame(totals)); report={'version':'2026-consensus-lines-oos-1','method':'one median pre-match closing line per fixture across available OddsPapi books; 2025 fit / untouched 2026 validation','spread':summary(cs),'totals':summary(ct)}; OUT.parent.mkdir(parents=True,exist_ok=True); OUT.write_text(json.dumps(report,indent=2)); print(json.dumps(report,indent=2))
if __name__=='__main__': main()
