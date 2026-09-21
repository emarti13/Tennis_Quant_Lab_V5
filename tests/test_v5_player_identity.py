import pandas as pd
from v5_player_identity import resolve_identity

PLAYERS=["Mateo Del Pino","Juan Del Pino","Kristina Mladenovic"]

def test_order_and_punctuation_normalize_to_unique_history():
    r=resolve_identity("Del Pino, Mateo",PLAYERS)
    assert r["status"]=="AUTO_ALIAS"
    assert r["canonical_player"]=="Mateo Del Pino"

def test_unknown_player_cold_starts_only_without_plausible_candidate():
    r=resolve_identity("Completely New Junior",PLAYERS)
    assert r["status"]=="COLD_START"
    assert r["canonical_player"] is None

def test_fuzzy_candidate_requires_review_not_auto_merge():
    r=resolve_identity("Matteo Del Pino",PLAYERS)
    assert r["status"]=="IDENTITY_REVIEW"
    assert r["canonical_player"] is None
    assert "Mateo Del Pino" in r["candidates"]

def test_verified_alias_registry_wins():
    aliases=pd.DataFrame([{"provider":"oddspapi","provider_player_id":"","provider_name":"M. Del Pino","canonical_player":"Mateo Del Pino","status":"VERIFIED","method":"manual","confidence":"1"}])
    r=resolve_identity("M. Del Pino",PLAYERS,aliases,provider="oddspapi")
    assert r["status"]=="VERIFIED_ALIAS"
    assert r["canonical_player"]=="Mateo Del Pino"
