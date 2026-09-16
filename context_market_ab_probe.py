from __future__ import annotations
import gzip,json
from pathlib import Path
import pandas as pd
from historical_odds_normalizer import flatten_history,select_snapshot
from historical_market_mapper import map_snapshot_rows
from historical_fixture_matcher import canonical_name
from diagnose_v5_score_distribution import _attach_scores,_feature_columns,_mechanistic_predictions
from v5_score_walkforward import fit_gaussian_score_model,predict_gaussian_score_model
from consensus_line_analysis import consensus_spread,consensus_total
from context_market_ab import summarize_pair

OUT=Path('experiments/acceptance/context_market_ab_2026_report.json')

def key(date,a,b): return (pd.Timestamp(date).date().isoformat(),tuple(sorted((canonical_name(a),canonical_name(b)))))
def histories():
 for p in sorted(Path('oddspapi_history/chunks').glob('history_chunk_*.jsonl.gz')):
  with gzip.open(p,'rt',encoding='utf-8') as f:
   for s in f:
    if s.strip(): yield json.loads(s)

def predictions():
 m=pd.read_parquet('v5_context_diagnostic/matched_context_rows.parquet'); scores=pd.read_parquet('context_warehouse/matches.parquet'); f=_attach_scores(m,scores); frames=[]
 for tour in ('MEN','WTA'):
  x=f[f.tour.astype(str).str.upper().eq(tour)].copy(); tr=x[pd.to_numeric(x.year,errors='coerce').eq(2025)].copy(); va=x[pd.to_numeric(x.year,errors='coerce').eq(2026)].copy()
  base=_mechanistic_predictions(va,simulations=80)
  feats=_feature_columns(tr); model=fit_gaussian_score_model(tr,features=feats,l2=16.0); enh=predict_gaussian_score_model(model,va)
  va['baseline_margin']=base['margin_mean']; va['baseline_total']=base['total_mean']; va['enhanced_margin']=enh['margin_mean']; va['enhanced_total']=enh['total_mean']; va['tour_eval']=tour; frames.append(va)
 return pd.concat(frames,ignore_index=True)

def main():
 meta=json.loads(Path('oddspapi_markets_tennis.json').read_text()); pred=predictions(); idx={}
 for i,r in pred.iterrows(): idx.setdefault(key(r.match_date,r.player_a,r.player_b),[]).append(i)
 rows=[]
 for rec in histories():
  fixture=rec.get('fixture'); payload=rec.get('historical_odds') or {}
  if not fixture or not payload: continue
  ids=idx.get(key(fixture.get('startTime'),fixture.get('participant1Name'),fixture.get('participant2Name')),[])
  if len(ids)!=1: continue
  r=pred.loc[ids[0]]; fid=str(payload.get('fixtureId') or fixture.get('fixtureId')); mapped=map_snapshot_rows(select_snapshot(flatten_history(payload),start_time=fixture['startTime'],closing=True),fixture,meta)
  for x in mapped:
   if x.get('line') is None or x.get('market_group') not in {'game_spread','total_games'}: continue
   rows.append({'fixture_id':fid,'tour':r.tour_eval,'bookmaker':x.get('bookmaker'),'market_id':x.get('market_id'),'market_group':x.get('market_group'),'selection':x.get('selection'),'player_a':r.player_a,'line':float(x['line']),'no_vig_prob':x.get('no_vig_prob'),'actual_margin_a':float(r.actual_margin_a),'actual_total':float(r.actual_total),'baseline_margin':float(r.baseline_margin),'baseline_total':float(r.baseline_total),'enhanced_margin':float(r.enhanced_margin),'enhanced_total':float(r.enhanced_total)})
 raw=pd.DataFrame(rows); reports={}
 for market in ('spread','totals'):
  src=raw[raw.market_group.eq('game_spread' if market=='spread' else 'total_games')].copy(); outputs={}
  for version in ('baseline','enhanced'):
   if market=='spread':
    z=src.rename(columns={f'{version}_margin':'pred_margin_a'}); outputs[version]=consensus_spread(z)
   else:
    z=src.rename(columns={f'{version}_total':'pred_total'}); outputs[version]=consensus_total(z)
  reports[market]=summarize_pair(outputs['baseline'],outputs['enhanced'])
 report={'version':'2026-context-market-ab-1','method':'same 2025 fit / untouched 2026 fixtures and consensus closing lines; baseline conditioned mechanistic versus enhanced full contextual Gaussian','spread':reports['spread'],'totals':reports['totals']}
 OUT.parent.mkdir(parents=True,exist_ok=True); OUT.write_text(json.dumps(report,indent=2)); print(json.dumps(report,indent=2))
if __name__=='__main__': main()
