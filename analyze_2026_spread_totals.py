from __future__ import annotations
import gzip,json,math
from pathlib import Path
import numpy as np,pandas as pd
from historical_odds_normalizer import flatten_history,select_snapshot
from historical_market_mapper import map_snapshot_rows
from historical_fixture_matcher import canonical_name
from diagnose_v5_score_distribution import _attach_scores,_feature_columns,_mechanistic_predictions
from v5_score_walkforward import fit_gaussian_score_model,predict_gaussian_score_model,distribution_metrics,score_candidate_gate

OUT=Path('experiments/acceptance/spread_totals_2026_report.json')

def fixtures():
 d={}
 for s in Path('oddspapi_history/fixtures_2026.jsonl').read_text(encoding='utf-8').splitlines():
  if s.strip():
   x=json.loads(s); d[str(x['fixtureId'])]=x
 return d

def histories():
 for p in sorted(Path('oddspapi_history/chunks').glob('history_chunk_*.jsonl.gz')):
  with gzip.open(p,'rt',encoding='utf-8') as f:
   for s in f:
    if s.strip(): yield json.loads(s)

def key(date,a,b):
 return (pd.Timestamp(date).date().isoformat(),tuple(sorted((canonical_name(a),canonical_name(b)))))

def score_predictions():
 m=pd.read_parquet('v5_context_diagnostic/matched_context_rows.parquet')
 scores=pd.read_parquet('context_warehouse/matches.parquet')
 frame=_attach_scores(m,scores)
 allp=[]; summary={}
 for tour in ('MEN','WTA'):
  f=frame[frame.tour.astype(str).str.upper().eq(tour)].copy().reset_index(drop=True)
  tr=f[pd.to_numeric(f.year,errors='coerce').eq(2025)].copy().reset_index(drop=True)
  va=f[pd.to_numeric(f.year,errors='coerce').eq(2026)].copy().reset_index(drop=True)
  feats=_feature_columns(tr)
  direct=fit_gaussian_score_model(tr,features=feats,l2=16.0); dp=predict_gaussian_score_model(direct,va)
  mech=_mechanistic_predictions(va,simulations=80)
  mm=distribution_metrics(va.actual_margin_a,va.actual_total,mech); dm=distribution_metrics(va.actual_margin_a,va.actual_total,dp)
  gate=score_candidate_gate(mm,dm); selected='gaussian_contextual' if gate['accepted'] else 'conditioned_mechanistic'; pred=dp if selected=='gaussian_contextual' else mech
  va=va.copy(); va['pred_margin_a']=pred['margin_mean']; va['pred_total']=pred['total_mean']; va['tour_eval']=tour
  allp.append(va)
  summary[tour]={'validation_rows':len(va),'selected_candidate':selected,'distribution_metrics':dm if selected=='gaussian_contextual' else mm}
 return pd.concat(allp,ignore_index=True),summary

def main():
 meta=json.loads(Path('oddspapi_markets_tennis.json').read_text(encoding='utf-8'))
 fx=fixtures(); preds,dist=score_predictions()
 pidx={}
 for i,r in preds.iterrows(): pidx.setdefault(key(r.match_date,r.player_a,r.player_b),[]).append(i)
 spread=[]; totals=[]; fixture_market_counts={'cached_history_records':0,'matched_model_fixtures':set(),'spread_fixtures':set(),'total_fixtures':set(),'both_fixtures':set()}
 for rec in histories():
  fixture=rec.get('fixture') or fx.get(str((rec.get('historical_odds') or {}).get('fixtureId')))
  payload=rec.get('historical_odds') or {}; fid=str(payload.get('fixtureId') or (fixture or {}).get('fixtureId') or '')
  if not fixture or not payload: continue
  fixture_market_counts['cached_history_records']+=1
  k=key(fixture.get('startTime'),fixture.get('participant1Name'),fixture.get('participant2Name'))
  ids=pidx.get(k,[])
  if len(ids)!=1: continue
  pr=preds.loc[ids[0]]; fixture_market_counts['matched_model_fixtures'].add(fid)
  snap=select_snapshot(flatten_history(payload),start_time=fixture['startTime'],closing=True)
  mapped=map_snapshot_rows(snap,fixture,meta)
  groups={x.get('market_group') for x in mapped}
  if 'game_spread' in groups: fixture_market_counts['spread_fixtures'].add(fid)
  if 'total_games' in groups: fixture_market_counts['total_fixtures'].add(fid)
  if {'game_spread','total_games'}.issubset(groups): fixture_market_counts['both_fixtures'].add(fid)
  # one decision per bookmaker/market_id. Each market_id represents a specific line.
  buckets={}
  for x in mapped:
   if x.get('market_group') in {'game_spread','total_games'} and x.get('line') is not None:
    buckets.setdefault((x['bookmaker'],x['market_id'],x['market_group']),[]).append(x)
  for (_,_,g),rows in buckets.items():
   if g=='game_spread':
    candidates=[]
    for x in rows:
     sel=canonical_name(x.get('selection'))
     if sel==canonical_name(pr.player_a): pm=float(pr.pred_margin_a); am=float(pr.actual_margin_a)
     elif sel==canonical_name(pr.player_b): pm=-float(pr.pred_margin_a); am=-float(pr.actual_margin_a)
     else: continue
     line=float(x['line']); candidates.append((pm+line,am+line,x))
    if not candidates: continue
    # model selects the side with largest predicted cover margin; avoid duplicate market sides
    pv,av,x=max(candidates,key=lambda z:z[0]); outcome='PUSH' if av==0 else ('WIN' if av>0 else 'LOSS')
    spread.append({'fixture_id':fid,'tour':pr.tour_eval,'pred_cover_margin':pv,'actual_cover_margin':av,'outcome':outcome,'bookmaker':x['bookmaker'],'line':float(x['line'])})
   else:
    x=rows[0]; line=float(x['line']); pred=float(pr.pred_total)-line; actual=float(pr.actual_total)-line
    # prediction is over if pred>0, under otherwise; grade against actual
    win=(actual>0)==(pred>0); push=actual==0
    totals.append({'fixture_id':fid,'tour':pr.tour_eval,'pred_edge_games':abs(pred),'actual_vs_line':actual,'outcome':'PUSH' if push else ('WIN' if win else 'LOSS'),'bookmaker':x['bookmaker'],'line':line})
 def summarize(rows):
  df=pd.DataFrame(rows); out={}
  for label,sub in [('ALL',df)]+([(t,df[df.tour.eq(t)]) for t in ('MEN','WTA')] if not df.empty else []):
   if sub.empty: out[label]={'n':0}; continue
   decisive=sub[~sub.outcome.eq('PUSH')]; out[label]={'n':int(len(sub)),'decisions':int(len(decisive)),'wins':int(decisive.outcome.eq('WIN').sum()),'losses':int(decisive.outcome.eq('LOSS').sum()),'pushes':int(sub.outcome.eq('PUSH').sum()),'accuracy':float(decisive.outcome.eq('WIN').mean()) if len(decisive) else None,'unique_fixtures':int(sub.fixture_id.nunique())}
  return out
 report={'version':'2026-oddspapi-spread-total-oos-1','method':'2025 fit / 2026 validation; pre-match closing OddsPapi snapshots; score model contains no market prices','distribution_validation':dist,'coverage':{k:(len(v) if isinstance(v,set) else v) for k,v in fixture_market_counts.items()},'spread':summarize(spread),'totals':summarize(totals)}
 OUT.parent.mkdir(parents=True,exist_ok=True); OUT.write_text(json.dumps(report,indent=2,allow_nan=False),encoding='utf-8'); print(json.dumps(report,indent=2))
if __name__=='__main__': main()
