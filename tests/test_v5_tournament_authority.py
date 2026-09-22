import pandas as pd
from v5_tournament_authority import audit_authority, resolve_authority, court_context


def sample():
    return pd.DataFrame([{
        "Year": 2026,
        "Circuit Tour": "ATP 250",
        "Tournament Name": "Test Open",
        "City": "Test City",
        "Date": "1-Jan",
        "End Date": "7-Jan",
        "Surface": "Hard",
        "Setting": "Outdoor",
        "Altitude (m)": 321,
        "OddsPapi Tournament ID": "77",
        "Official_Ball_Model": "Dunlop",
        "General_CPI_Category": "Medium",
        "Actual_CPI_Rating": 39,
        "Tennis_Abstract_Rating": 1.1,
    }])


def test_exact_authority_resolution():
    r = resolve_authority("Test Open", 2026, table=sample())
    assert court_context(r)["actual_cpi"] == 39
    assert r["authority_match_method"] == "exact_name"


def test_oddspapi_identity_is_only_external_resolution():
    r = resolve_authority("Provider Name", 2026, oddspapi_tournament_id="77", table=sample())
    assert r["authority_match_method"] == "oddspapi_id"


def test_unknown_fails_closed_no_legacy_fallback():
    assert resolve_authority("Unknown", 2026, table=sample()) is None


def test_missing_oddspapi_id_does_not_block_authority_resolution():
    df = sample().copy()
    df["OddsPapi Tournament ID"] = pd.NA
    r = resolve_authority("Test Open", 2026, table=df)
    assert r is not None
    assert r["authority_match_method"] == "exact_name"


def _alias_table():
    return pd.DataFrame([
        {
            "Year": 2026,
            "Circuit Tour": "ATP MASTERS 1000",
            "Tournament Name": "BNP PARIBAS OPEN",
            "City": "Indian Wells",
            "Date": "4-Mar",
            "End Date": "15-Mar",
            "Surface": "Hard",
            "Setting": "Outdoor",
            "Altitude (m)": 79,
            "OddsPapi Tournament ID": pd.NA,
        },
        {
            "Year": 2026,
            "Circuit Tour": "WTA 1000",
            "Tournament Name": "BNP Paribas Open",
            "City": "Indian Wells",
            "Date": "2-Mar",
            "End Date": "15-Mar",
            "Surface": "Hard",
            "Setting": "Outdoor",
            "Altitude (m)": 79,
            "OddsPapi Tournament ID": pd.NA,
        },
    ])


def test_city_alias_resolves_without_oddspapi_id_when_tour_surface_date_disambiguate():
    r = resolve_authority(
        "Indian Wells",
        2026,
        tour="MEN",
        surface="Hard",
        match_date="2026-03-10",
        table=_alias_table(),
    )
    assert r is not None
    assert r["Circuit Tour"] == "ATP MASTERS 1000"
    assert r["authority_match_method"] == "city_alias"


def test_alias_does_not_cross_tours():
    r = resolve_authority(
        "Indian Wells",
        2026,
        tour="WTA",
        surface="Hard",
        match_date="2026-03-10",
        table=_alias_table(),
    )
    assert r is not None
    assert r["Circuit Tour"] == "WTA 1000"


def test_unrelated_name_still_fails_closed_even_in_date_window():
    assert resolve_authority(
        "Totally Different Event",
        2026,
        tour="MEN",
        surface="Hard",
        match_date="2026-03-10",
        table=_alias_table(),
    ) is None
