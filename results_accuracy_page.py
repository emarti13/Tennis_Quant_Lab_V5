from pathlib import Path
import json
import numpy as np
import pandas as pd
import streamlit as st
from v5_fixture_accuracy import fixture_accuracy_metrics, fixture_accuracy_records
from v5_results_reset import filter_since_reset, load_reset_timestamp
BASE=Path(__file__).resolve().parent
DEFAULT_LEDGER=BASE/'v5_daily_ready'/'frozen_predictions.csv'
PRODUCTION_CANDIDATE_PATH=BASE/'experiments'/'acceptance'/'production_candidate.json'

def _safe_div(a,b): return float(a/b) if b else np.nan
def _current_model_version(path=PRODUCTION_CANDIDATE_PATH):
 try: p=json.loads(Path(path).read_text(encoding='utf-8')); return str(p.get('version')) if p.get('version') else None
 except (OSError,json.JSONDecodeError): return None

def filter_current_engine_rows(df,current_model_version):
 if df is None or df.empty or not current_model_version or 'model_version' not in df.columns: return pd.DataFrame(columns=list(df.columns) if df is not None else [])
 v=df.model_version.fillna('').astype(str); s=df.get('signal',pd.Series(index=df.index,dtype=object)).fillna('').astype(str).str.upper(); return df[v.eq(str(current_model_version))&s.isin(['BET','LEAN'])].copy()
def results_ledger_views(df,current_model_version):
 if df is None or df.empty:
  e=pd.DataFrame(columns=list(df.columns) if df is not None else []); return {'current_engine':e.copy(),'historical_actionable':e.copy(),'all_settled':e.copy()}
 status=df.get('result_status',pd.Series(index=df.index,dtype=object)).fillna('').astype(str).str.upper(); result=df.get('settled_result',pd.Series(index=df.index,dtype=object)).fillna('').astype(str).str.upper(); signal=df.get('signal',pd.Series(index=df.index,dtype=object)).fillna('').astype(str).str.upper(); settled=df[status.eq('SETTLED')&result.isin(['WIN','LOSS','PUSH','VOID'])].copy(); actionable=settled[signal.loc[settled.index].isin(['BET','LEAN'])].copy()
 if current_model_version and 'model_version' in actionable.columns:
  v=actionable.model_version.fillna('').astype(str); current=actionable[v.eq(str(current_model_version))].copy(); historical=actionable[~v.eq(str(current_model_version))].copy()
 else: current=actionable.iloc[0:0].copy(); historical=actionable.copy()
 return {'current_engine':current,'historical_actionable':historical,'all_settled':settled}
def load_accuracy_ledger(path=DEFAULT_LEDGER):
 path=Path(path)
 if not path.exists(): return pd.DataFrame()
 df=pd.read_csv(path,low_memory=False)
 for c in ('frozen_at_utc','start_time_utc','settled_at_utc'):
  if c in df: df[c]=pd.to_datetime(df[c],errors='coerce',utc=True)
 for c in ('model_probability','full_context_probability_p1','edge_vs_consensus','expected_value','expected_margin','expected_total','winner_games','loser_games','state_confidence','profit_units','best_american_odds','model_fair_american','line'):
  if c in df: df[c]=pd.to_numeric(df[c],errors='coerce')
 try: prod=path.resolve()==DEFAULT_LEDGER.resolve()
 except OSError: prod=path==DEFAULT_LEDGER
 return filter_since_reset(df,load_reset_timestamp(),timestamp_columns=('frozen_at_utc','snapshot_utc','start_time_utc')) if prod else df
def accuracy_metrics(df,*,actionable_only=True):
 if df is None or df.empty: return {'frozen':0,'settled':0,'decisions':0,'wins':0,'losses':0,'pushes':0,'voids':0,'win_rate':np.nan,'units':0.,'roi':np.nan}
 status=df.get('result_status',pd.Series(index=df.index,dtype=object)).fillna('').astype(str).str.upper(); result=df.get('settled_result',pd.Series(index=df.index,dtype=object)).fillna('').astype(str).str.upper(); sm=status.eq('SETTLED')
 if actionable_only and 'signal' in df: sm &= df.signal.fillna('').astype(str).str.upper().isin(['BET','LEAN'])
 dm=sm&result.isin(['WIN','LOSS']); w=int((dm&result.eq('WIN')).sum()); l=int((dm&result.eq('LOSS')).sum()); n=w+l; units=pd.to_numeric(df.loc[dm,'profit_units'],errors='coerce').sum() if 'profit_units' in df else 0.
 return {'frozen':len(df),'settled':int(sm.sum()),'decisions':n,'wins':w,'losses':l,'pushes':int((sm&result.eq('PUSH')).sum()),'voids':int((sm&result.eq('VOID')).sum()),'win_rate':_safe_div(w,n),'units':float(units),'roi':_safe_div(units,n)}
def fixture_headline_metrics(records): return fixture_accuracy_metrics(records)

def _competition(row):
 text=' '.join(str(row.get(c,'')) for c in ('tour_v5','tour','level','tournament')).upper()
 if 'CHALLENGER' in text or 'CHALL' in text: return 'Challenger'
 if 'WTA' in text: return 'WTA'
 return 'ATP' if ('ATP' in text or 'MEN' in text) else 'Other'
def _cell(g):
 m=accuracy_metrics(g,actionable_only=False); n=m['decisions']
 if not n: return '—' if not m['pushes'] else f"— · 0-0 · N=0 · {m['units']:+.1f}u · — ROI"
 return f"{m['win_rate']:.1%} · {m['wins']}-{m['losses']} · N={n} · {m['units']:+.1f}u · {m['roi']:+.1%} ROI"
def recommendation_accuracy_matrix(df,market_group):
 rows=['ATP','WTA','Challenger','All']; cols=['BET','LEAN','REVIEW','PASS','Overall']; out=pd.DataFrame('—',index=rows,columns=cols)
 if df is None or df.empty: return out
 market=df.get('market_group',pd.Series(index=df.index,dtype=object)).fillna('').astype(str).str.lower(); aliases={'moneyline':{'moneyline','match_winner','ml'},'game_spread':{'game_spread','spread'},'total_games':{'total_games','totals','total'}}; x=df[market.isin(aliases.get(market_group,{market_group}))].copy()
 if x.empty:return out
 x['_competition']=x.apply(_competition,axis=1); x['_signal']=x.get('signal',pd.Series(index=x.index,dtype=object)).fillna('').astype(str).str.upper(); status=x.get('result_status',pd.Series(index=x.index,dtype=object)).fillna('').astype(str).str.upper(); result=x.get('settled_result',pd.Series(index=x.index,dtype=object)).fillna('').astype(str).str.upper(); x=x[status.eq('SETTLED')&result.isin(['WIN','LOSS','PUSH'])]
 for r in rows:
  rg=x if r=='All' else x[x._competition.eq(r)]
  for c in cols: out.loc[r,c]=_cell(rg if c=='Overall' else rg[rg._signal.eq(c)])
 return out

def _display_fixture_accuracy(records):
 if records is None or records.empty: st.info('No settled fixture forecasts are available yet.'); return
 cols=[c for c in ['settled_at_utc','tournament','tour','surface','player1','player2','p1_probability','predicted_winner','actual_winner','winner_correct','expected_margin','actual_margin','abs_margin_error','expected_total','actual_total','abs_total_error','result_score'] if c in records]
 st.dataframe(records[cols],use_container_width=True,hide_index=True)
def _display_ledger(frame):
 if frame is None or frame.empty: st.info('No rows are available in this result scope yet.'); return
 cols=[c for c in ['settled_at_utc','tournament','tour_v5','market_group','selection','line','signal','settled_result','profit_units'] if c in frame]; st.dataframe(frame[cols],use_container_width=True,hide_index=True)
def render_results_accuracy(ledger_path=DEFAULT_LEDGER):
 st.title('Results & Accuracy'); reset_at=load_reset_timestamp(); reset_text='' if reset_at is None else f" Active production epoch: {reset_at.strftime('%Y-%m-%d %H:%M UTC')}."; st.caption('Underlying fixture accuracy plus market/tour recommendation audit.'+reset_text)
 df=load_accuracy_ledger(ledger_path)
 if df.empty: st.info('No post-reset frozen predictions have settled yet.'); return
 fixtures=fixture_accuracy_records(df); h=fixture_headline_metrics(fixtures); c=st.columns(5); c[0].metric('Settled fixtures',f"{h['settled_fixtures']:,}"); c[1].metric('Winner accuracy','—' if pd.isna(h['winner_accuracy']) else f"{h['winner_accuracy']:.1%}"); c[2].metric('Brier score','—' if pd.isna(h['brier_score']) else f"{h['brier_score']:.3f}"); c[3].metric('Margin MAE','—' if pd.isna(h['margin_mae']) else f"{h['margin_mae']:.2f} games"); c[4].metric('Total MAE','—' if pd.isna(h['total_mae']) else f"{h['total_mae']:.2f} games")
 st.subheader('Recommendation accuracy'); st.caption('Each cell: Win Rate · W-L · N · Units · ROI. Pushes are excluded from win-rate/ROI denominator. REVIEW and PASS show counterfactual performance at their frozen prices.')
 for title,market in [('Moneyline','moneyline'),('Spread','game_spread'),('Totals','total_games')]: st.markdown(f'#### {title}'); st.dataframe(recommendation_accuracy_matrix(df,market),use_container_width=True)
 st.subheader('Fixture forecast results'); _display_fixture_accuracy(fixtures)
 with st.expander('Market-level settlement audit — active epoch only',expanded=False): _display_ledger(results_ledger_views(df,_current_model_version())['all_settled'])
