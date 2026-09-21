"""Conservative player identity resolution for live V5 fixtures."""
from __future__ import annotations
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
import re
import unicodedata
import pandas as pd

ALIAS_COLUMNS=["provider","provider_player_id","provider_name","canonical_player","status","method","confidence","first_seen_utc","last_seen_utc","notes"]

def identity_key(value):
    s=unicodedata.normalize("NFKD",str(value or "")).encode("ascii","ignore").decode("ascii").lower()
    s=re.sub(r"[^a-z0-9 ]+"," ",s)
    toks=[x for x in s.split() if x]
    if len(toks)>=2:
        # Order-insensitive key safely handles "Surname, Given" vs "Given Surname".
        toks=sorted(toks)
    return " ".join(toks)

def load_aliases(path):
    p=Path(path)
    if not p.exists(): return pd.DataFrame(columns=ALIAS_COLUMNS)
    d=pd.read_csv(p,dtype=str).fillna("")
    for c in ALIAS_COLUMNS:
        if c not in d.columns: d[c]=""
    return d[ALIAS_COLUMNS]

def _alias_match(name, aliases, provider="", provider_player_id=""):
    if aliases is None or aliases.empty: return None
    d=aliases.copy()
    d=d[d.status.str.upper().isin(["VERIFIED","AUTO_VERIFIED"])]
    if provider: d=d[(d.provider=="") | (d.provider.str.lower()==provider.lower())]
    if provider_player_id:
        z=d[d.provider_player_id==str(provider_player_id)]
        if len(z)==1: return z.iloc[0].canonical_player
    key=identity_key(name)
    z=d[d.provider_name.map(identity_key)==key]
    vals=z.canonical_player.dropna().unique()
    return vals[0] if len(vals)==1 else None

def resolve_identity(name, historical_players, aliases=None, provider="", provider_player_id=""):
    players=[str(x) for x in historical_players if str(x).strip()]
    exact={str(x).strip().lower():x for x in players}
    raw=str(name or "").strip()
    if raw.lower() in exact:
        return {"status":"ESTABLISHED","canonical_player":exact[raw.lower()],"method":"exact","confidence":1.0,"candidates":[]}
    alias=_alias_match(raw,aliases,provider,provider_player_id)
    if alias in players:
        return {"status":"VERIFIED_ALIAS","canonical_player":alias,"method":"alias_registry","confidence":1.0,"candidates":[]}
    key=identity_key(raw)
    keyed={}
    for p in players: keyed.setdefault(identity_key(p),[]).append(p)
    if key in keyed and len(keyed[key])==1:
        return {"status":"AUTO_ALIAS","canonical_player":keyed[key][0],"method":"normalized_unique","confidence":0.995,"candidates":[keyed[key][0]]}
    scored=[]
    for p in players:
        pk=identity_key(p)
        if not pk: continue
        score=SequenceMatcher(None,key,pk).ratio()
        # Candidate generation only. Never auto-merge fuzzy identities.
        if score>=0.78: scored.append((score,p))
    scored=sorted(scored,reverse=True)[:5]
    if scored:
        return {"status":"IDENTITY_REVIEW","canonical_player":None,"method":"fuzzy_candidates_only","confidence":float(scored[0][0]),"candidates":[p for _,p in scored]}
    return {"status":"COLD_START","canonical_player":None,"method":"no_plausible_history","confidence":0.0,"candidates":[]}
