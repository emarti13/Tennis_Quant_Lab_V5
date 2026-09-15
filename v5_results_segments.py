from __future__ import annotations
import numpy as np
import pandas as pd

SIGNALS=("BET","LEAN","REVIEW","PASS")
MARKETS={"Moneyline":{"moneyline","match_winner","ml"},"Spread":{"game_spread","spread"},"Totals":{"total_games","total","totals"}}
TOURS=("ATP","WTA","CHALLENGER")

def _competition(tour,tournament=""):
    combined=f"{tour or ''} {tournament or ''}".upper()
    if "CHALLENG" in combined: return "CHALLENGER"
    if "WTA" in combined or "WOMEN" in combined: return "WTA"
    if "ATP" in combined or "MEN" in combined: return "ATP"
    return str(tour or "UNKNOWN").upper()

def _unit_profit(row):
    result=str(row.get("settled_result","")).upper()
    if result in ("PUSH","VOID"): return 0.0
    if result=="LOSS": return -1.0
    if result!="WIN": return np.nan
    odds=pd.to_numeric(pd.Series([row.get("best_american_odds")]),errors="coerce").iloc[0]
    if pd.notna(odds): return float(odds/100.0 if odds>0 else 100.0/abs(odds))
    p=pd.to_numeric(pd.Series([row.get("profit_units")]),errors="coerce").iloc[0]
    return float(p) if pd.notna(p) else np.nan

def _cell(g):
    if g.empty: return "—"
    r=g["settled_result"].astype(str).str.upper(); wins=int(r.eq("WIN").sum()); losses=int(r.eq("LOSS").sum()); decisions=wins+losses
    units=float(g.apply(_unit_profit,axis=1).fillna(0).sum()); roi=units/decisions if decisions else np.nan; rate=wins/decisions if decisions else np.nan
    return f"{'—' if pd.isna(rate) else f'{rate:.1%}'} · {wins}-{losses} · N={len(g)} · {units:+.2f}u · {'— ROI' if pd.isna(roi) else f'{roi:+.1%} ROI'}"

def recommendation_accuracy_tables(df):
    cols=list(SIGNALS)+["Overall"]
    if df is None or df.empty: return {k:pd.DataFrame(index=list(TOURS)+["All"],columns=cols).fillna("—") for k in MARKETS}
    x=df.copy(); status=x.get("result_status",pd.Series(index=x.index,dtype=object)).fillna("").astype(str).str.upper(); result=x.get("settled_result",pd.Series(index=x.index,dtype=object)).fillna("").astype(str).str.upper(); signal=x.get("signal",pd.Series(index=x.index,dtype=object)).fillna("").astype(str).str.upper()
    x=x[status.eq("SETTLED") & result.isin(["WIN","LOSS","PUSH","VOID"]) & signal.isin(SIGNALS)].copy(); x["_signal"]=signal.loc[x.index]
    tour_col="tour_v5" if "tour_v5" in x.columns else "tour"; tours=x.get(tour_col,pd.Series(index=x.index,dtype=object)); tournaments=x.get("tournament",pd.Series("",index=x.index)); x["_tour"]=[_competition(a,b) for a,b in zip(tours,tournaments)]; x["_market"]=x.get("market_group",pd.Series(index=x.index,dtype=object)).fillna("").astype(str).str.lower()
    out={}
    for label,aliases in MARKETS.items():
        m=x[x["_market"].isin(aliases)]; rows={}
        for t in list(TOURS)+["All"]:
            g=m if t=="All" else m[m["_tour"]==t]
            rows[t]={s:_cell(g[g["_signal"]==s]) for s in SIGNALS}; rows[t]["Overall"]=_cell(g)
        out[label]=pd.DataFrame.from_dict(rows,orient="index",columns=cols)
    return out
