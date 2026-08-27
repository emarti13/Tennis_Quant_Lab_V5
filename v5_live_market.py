
from __future__ import annotations

from pathlib import Path
import re
import unicodedata
import pandas as pd

BASE = Path(__file__).resolve().parent
MARKET_FILE = BASE / "v5_market_ready" / "market_board_input.csv"

def canonical_name(name):
    s = "" if name is None else str(name).strip()

    # Remove disambiguators commonly appended by odds providers, e.g.
    # "Cretu, Cezar (2001)".
    s = re.sub(r"\s*\([^)]*\)\s*$", "", s).strip()

    if "," in s:
        parts=[x.strip() for x in s.split(",",1)]
        if len(parts)==2 and parts[0] and parts[1]:
            s=f"{parts[1]} {parts[0]}"

    s=unicodedata.normalize("NFKD",s)
    s="".join(ch for ch in s if not unicodedata.combining(ch))
    s=s.lower()
    s=re.sub(r"[^a-z0-9]+"," ",s)
    return " ".join(s.split())

def load_market_board():
    if not MARKET_FILE.exists():
        return pd.DataFrame()
    return pd.read_csv(MARKET_FILE, low_memory=False)

def find_match_rows(df, p1, p2):
    if df.empty:
        return df
    a,b=canonical_name(p1),canonical_name(p2)
    c1=df["player1"].map(canonical_name)
    c2=df["player2"].map(canonical_name)
    m=((c1==a)&(c2==b))|((c1==b)&(c2==a))
    return df[m].copy()

def is_half_line(x):
    try:
        v=float(x)
    except Exception:
        return False
    return abs(v*2-round(v*2))<1e-9 and abs(v-round(v))>1e-9

def model_probability_for_market(row, result, selected_p1, selected_p2):
    group=row.get("market_group")
    sel=canonical_name(row.get("selection"))
    p1=canonical_name(selected_p1)
    p2=canonical_name(selected_p2)
    line=row.get("line")

    if group=="moneyline":
        if sel==p1:
            return float(result["pA_win"])
        if sel==p2:
            return 1.0-float(result["pA_win"])
        return None

    if not is_half_line(line):
        return None
    line=float(line)

    if group=="game_spread":
        spreads={float(k):float(v) for k,v in result["spread"].items()}
        if sel==p1:
            return spreads.get(line)
        if sel==p2:
            p=spreads.get(-line)
            return None if p is None else 1.0-p

    if group=="total_games":
        overs={float(k):float(v) for k,v in result["over"].items()}
        p=overs.get(line)
        if p is None:
            return None
        raw=str(row.get("selection","")).strip().lower()
        if raw=="over":
            return p
        if raw=="under":
            return 1.0-p

    return None

def fair_american(p):
    p=float(p)
    if p<=0 or p>=1:
        return None
    return -100*p/(1-p) if p>=0.5 else 100*(1-p)/p

def add_model_pricing(match_rows, result, selected_p1, selected_p2):
    if match_rows.empty:
        return match_rows
    out=match_rows.copy()
    probs=[]; fair=[]; edges=[]; evs=[]
    for _,r in out.iterrows():
        p=model_probability_for_market(r,result,selected_p1,selected_p2)
        probs.append(p)
        if p is None:
            fair.append(None); edges.append(None); evs.append(None)
            continue
        fair.append(fair_american(p))
        try:
            nv=float(r.get("consensus_no_vig_prob"))
        except Exception:
            nv=None
        try:
            dec=float(r.get("best_decimal_odds"))
        except Exception:
            dec=None
        edges.append(None if nv is None else p-nv)
        evs.append(None if dec is None else p*dec-1.0)
    out["model_probability"]=probs
    out["model_fair_american"]=fair
    out["edge_vs_consensus"]=edges
    out["expected_value"]=evs
    return out

def signal_row(row, disagreement_level=None, state_confidence=None):
    ev=row.get("expected_value")
    edge=row.get("edge_vs_consensus")
    if pd.isna(ev) or pd.isna(edge):
        return "N/A"
    ev=float(ev); edge=float(edge)
    if state_confidence is not None and state_confidence<0.45:
        return "REVIEW"
    if disagreement_level=="HIGH":
        return "REVIEW"
    if disagreement_level=="MODERATE" and ev>=0.05:
        return "REVIEW"
    if ev>=0.05 and edge>=0.025:
        return "BET"
    if ev>=0.02 and edge>=0.01:
        return "LEAN"
    return "PASS"


# ============================================================
# ALL-BOOK PRICE FEED
# ============================================================

ALL_PRICE_CANDIDATES = [
    BASE / "v5_market_ready" / "all_book_prices.csv",
    BASE / "all_book_prices.csv",
]

def load_all_book_prices():
    for p in ALL_PRICE_CANDIDATES:
        if p.exists():
            df = pd.read_csv(p, low_memory=False)
            df.attrs["source_path"] = str(p)
            return df
    return pd.DataFrame()

def find_all_match_prices(df, p1, p2):
    if df.empty:
        return df
    a, b = canonical_name(p1), canonical_name(p2)
    if "player1" not in df.columns or "player2" not in df.columns:
        return pd.DataFrame()
    c1 = df["player1"].map(canonical_name)
    c2 = df["player2"].map(canonical_name)
    mask = ((c1 == a) & (c2 == b)) | ((c1 == b) & (c2 == a))
    return df[mask].copy()
