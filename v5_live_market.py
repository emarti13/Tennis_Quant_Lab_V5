
from __future__ import annotations

from pathlib import Path
import math
import pandas as pd

BASE = Path(__file__).resolve().parent
MARKET_FILE = BASE / "v5_market_ready" / "market_board_input.csv"

def _norm(x):
    return str(x).strip().lower()

def load_market_board():
    if not MARKET_FILE.exists():
        return pd.DataFrame()
    df = pd.read_csv(MARKET_FILE, low_memory=False)
    return df

def find_match_rows(df, p1, p2):
    if df.empty:
        return df
    a,b = _norm(p1),_norm(p2)
    m = (
        ((df["player1"].astype(str).str.strip().str.lower()==a) &
         (df["player2"].astype(str).str.strip().str.lower()==b))
        |
        ((df["player1"].astype(str).str.strip().str.lower()==b) &
         (df["player2"].astype(str).str.strip().str.lower()==a))
    )
    return df[m].copy()

def is_half_line(x):
    try:
        v=float(x)
    except Exception:
        return False
    return abs((v*2) - round(v*2)) < 1e-9 and abs(v-round(v)) > 1e-9

def model_probability_for_market(row, result, selected_p1, selected_p2):
    group = row["market_group"]
    sel = str(row["selection"])
    line = row.get("line")

    if group == "moneyline":
        if _norm(sel)==_norm(selected_p1):
            return float(result["pA_win"])
        if _norm(sel)==_norm(selected_p2):
            return 1.0-float(result["pA_win"])
        return None

    # Automated EV only on half-lines. Integer spreads/totals can push and
    # require explicit push probabilities rather than treating the other side
    # as 1-p.
    if not is_half_line(line):
        return None

    line=float(line)

    if group == "game_spread":
        spreads={float(k):float(v) for k,v in result["spread"].items()}
        if _norm(sel)==_norm(selected_p1):
            return spreads.get(line)
        if _norm(sel)==_norm(selected_p2):
            # P2 +L covers iff P1 -L does not cover for half-lines.
            p=spreads.get(-line)
            return None if p is None else 1.0-p
        return None

    if group == "total_games":
        overs={float(k):float(v) for k,v in result["over"].items()}
        p=overs.get(line)
        if p is None:
            return None
        if sel.strip().lower()=="over":
            return p
        if sel.strip().lower()=="under":
            return 1.0-p
        return None

    return None

def add_model_pricing(match_rows, result, selected_p1, selected_p2):
    if match_rows.empty:
        return match_rows

    out=match_rows.copy()
    probs=[]
    edges=[]
    evs=[]
    fair=[]
    for _,r in out.iterrows():
        p=model_probability_for_market(r,result,selected_p1,selected_p2)
        probs.append(p)
        if p is None:
            edges.append(None); evs.append(None); fair.append(None)
            continue
        try:
            market_p=float(r["consensus_no_vig_prob"])
        except Exception:
            market_p=None
        try:
            dec=float(r["best_decimal_odds"])
        except Exception:
            dec=None
        edges.append(None if market_p is None else p-market_p)
        evs.append(None if dec is None else p*dec-1.0)
        if p<=0 or p>=1:
            fair.append(None)
        elif p>=0.5:
            fair.append(-100*p/(1-p))
        else:
            fair.append(100*(1-p)/p)

    out["model_probability"]=probs
    out["model_fair_american"]=fair
    out["edge_vs_consensus"]=edges
    out["expected_value"]=evs
    return out

def signal_row(row, disagreement_level=None, state_confidence=None):
    """
    Conservative research labels. These remain heuristics until walk-forward
    validation is complete.
    """
    ev=row.get("expected_value")
    edge=row.get("edge_vs_consensus")
    if pd.isna(ev) or pd.isna(edge):
        return "N/A"

    ev=float(ev); edge=float(edge)

    if state_confidence is not None and state_confidence < 0.45:
        return "REVIEW"
    if disagreement_level == "HIGH":
        return "REVIEW"
    if disagreement_level == "MODERATE" and ev >= 0.05:
        return "REVIEW"
    if ev >= 0.05 and edge >= 0.025:
        return "BET"
    if ev >= 0.02 and edge >= 0.01:
        return "LEAN"
    return "PASS"
