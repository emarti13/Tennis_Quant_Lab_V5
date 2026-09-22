import pandas as pd
from v5_tournament_authority import audit_authority, resolve_authority, court_context

def sample():
    return pd.DataFrame([{"Year":2026,"Circuit Tour":"ATP 250","Tournament Name":"Test Open","Surface":"Hard","Setting":"Outdoor","Altitude (m)":321,"OddsPapi Tournament ID":"77","Official_Ball_Model":"Dunlop","General_CPI_Category":"Medium","Actual_CPI_Rating":39,"Tennis_Abstract_Rating":1.1,"_name_key":"test open","_tour_key":"atp 250"}])

def test_exact_authority_resolution():
    r=resolve_authority("Test Open",2026,table=sample())
    assert court_context(r)["actual_cpi"]==39
    assert r["authority_match_method"]=="exact_name"

def test_oddspapi_identity_is_only_external_resolution():
    r=resolve_authority("Provider Name",2026,oddspapi_tournament_id="77",table=sample())
    assert r["authority_match_method"]=="oddspapi_id"

def test_unknown_fails_closed_no_legacy_fallback():
    assert resolve_authority("Unknown",2026,table=sample()) is None


def test_missing_oddspapi_id_does_not_block_authority_resolution():
    df=sample().copy()
    df["OddsPapi Tournament ID"]=pd.NA
    r=resolve_authority("Test Open",2026,table=df)
    assert r is not None
    assert r["authority_match_method"]=="exact_name"
