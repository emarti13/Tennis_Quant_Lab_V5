from __future__ import annotations

from pathlib import Path
import re
import unicodedata
import numpy as np
import pandas as pd

DEFAULT_PATH = Path("context_registry/tournament_authority.csv")
REQUIRED = ("Year","Circuit Tour","Tournament Name","Surface","Setting","Altitude (m)")
COURT_FIELDS = ("Official_Ball_Model","General_CPI_Category","Actual_CPI_Rating","Tennis_Abstract_Rating")

def _norm(v):
    s=unicodedata.normalize("NFKD",str(v or "")).encode("ascii","ignore").decode("ascii").lower()
    return " ".join(re.findall(r"[a-z0-9]+",s))

def load_authority(path=DEFAULT_PATH):
    p=Path(path)
    if not p.exists(): raise FileNotFoundError(f"authoritative tournament table missing: {p}")
    try: df=pd.read_csv(p,low_memory=False)
    except UnicodeDecodeError: df=pd.read_csv(p,low_memory=False,encoding="cp1252")
    missing=[c for c in REQUIRED if c not in df.columns]
    if missing: raise ValueError(f"authoritative tournament table missing columns: {missing}")
    out=df.copy()
    for c in ("Year","Latitude","Longitude","Altitude (m)","Altitude (ft)","Actual_CPI_Rating","Tennis_Abstract_Rating"):
        if c in out.columns: out[c]=pd.to_numeric(out[c],errors="coerce")
    out["_name_key"]=out["Tournament Name"].map(_norm)
    out["_tour_key"]=out["Circuit Tour"].map(_norm)
    return out

def audit_authority(df):
    return {"rows":int(len(df)),"years":{str(int(k)):int(v) for k,v in df["Year"].dropna().value_counts().sort_index().items()},
      "coverage":{c:float(df[c].notna().mean()) if c in df else 0.0 for c in REQUIRED+COURT_FIELDS},
      "duplicate_rows":int(df.duplicated().sum())}

def resolve_authority(tournament,year,*,tour="",oddspapi_tournament_id=None,table=None):
    df=load_authority() if table is None else table.copy()
    y=pd.to_numeric(pd.Series([year]),errors="coerce").iloc[0]
    cand=df[pd.to_numeric(df["Year"],errors="coerce").eq(y)].copy()
    if oddspapi_tournament_id is not None and "OddsPapi Tournament ID" in cand:
        ids=cand["OddsPapi Tournament ID"].astype(str)
        hit=cand[ids.eq(str(oddspapi_tournament_id))]
        if len(hit)==1: return hit.iloc[0].to_dict() | {"authority_match_method":"oddspapi_id"}
    key=_norm(tournament)
    hit=cand[cand["_name_key"].eq(key)]
    if len(hit)==1: return hit.iloc[0].to_dict() | {"authority_match_method":"exact_name"}
    # Fail closed. No legacy court source and no fuzzy value fill.
    return None

def court_context(row):
    if row is None: return {}
    return {
      "surface":row.get("Surface"),"environment":row.get("Setting"),"altitude_m":row.get("Altitude (m)"),
      "ball_model":row.get("Official_Ball_Model"),"cpi_category":row.get("General_CPI_Category"),
      "actual_cpi":row.get("Actual_CPI_Rating"),"tennis_abstract_rating":row.get("Tennis_Abstract_Rating"),
      "latitude":row.get("Latitude"),"longitude":row.get("Longitude"),"timezone":row.get("Time Zone"),
      "oddspapi_tournament_id":row.get("OddsPapi Tournament ID"),"oddspapi_season_id":row.get("OddsPapi Season ID"),
      "source":"tournament_authority","authority_match_method":row.get("authority_match_method"),
    }
