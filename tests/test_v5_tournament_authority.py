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
    # Location matching runs before the bare city alias; either is a location match.
    assert r["authority_match_method"] in {"schedule_identity", "city_alias"}


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


def test_provider_location_plus_schedule_date_resolves_marketing_name_without_id():
    df = pd.DataFrame([
        {
            "Year": 2026, "Circuit Tour": "WTA 500", "Tournament Name": "Korea Open",
            "City": "Seoul", "Country": "South Korea", "Date": "21-Sep", "End Date": "27-Sep",
            "Surface": "Hard", "Setting": "Outdoor", "Altitude (m)": 38,
            "OddsPapi Tournament ID": pd.NA,
        },
        {
            "Year": 2026, "Circuit Tour": "WTA 250", "Tournament Name": "Other Korea Event",
            "City": "Busan", "Country": "South Korea", "Date": "21-Sep", "End Date": "27-Sep",
            "Surface": "Clay", "Setting": "Outdoor", "Altitude (m)": 5,
            "OddsPapi Tournament ID": pd.NA,
        },
    ])
    r = resolve_authority(
        "WTA Seoul, Korea Republic Women Singles", 2026,
        tour="WTA", match_date="2026-09-24", table=df,
    )
    assert r is not None
    assert r["Tournament Name"] == "Korea Open"
    assert r["Surface"] == "Hard"
    assert r["authority_match_method"] == "schedule_identity"


def test_surface_argument_never_selects_tournament_identity():
    df = pd.DataFrame([{
        "Year": 2026, "Circuit Tour": "WTA 500", "Tournament Name": "Korea Open",
        "City": "Seoul", "Country": "South Korea", "Date": "21-Sep", "End Date": "27-Sep",
        "Surface": "Hard", "Setting": "Outdoor", "Altitude (m)": 38,
        "OddsPapi Tournament ID": pd.NA,
    }])
    r = resolve_authority(
        "WTA Seoul, Korea Republic Women Singles", 2026,
        tour="WTA", surface="Clay", match_date="2026-09-24", table=df,
    )
    assert r is not None
    assert r["Surface"] == "Hard"


def test_same_city_multiple_events_are_disambiguated_by_date_not_city_alone():
    df = pd.DataFrame([
        {
            "Year": 2026, "Circuit Tour": "ATP GRAND SLAM", "Tournament Name": "Roland Garros",
            "City": "Paris", "Country": "France", "Date": "24-May", "End Date": "7-Jun",
            "Surface": "Clay", "Setting": "Outdoor", "Altitude (m)": 35,
            "OddsPapi Tournament ID": pd.NA,
        },
        {
            "Year": 2026, "Circuit Tour": "ATP MASTERS 1000", "Tournament Name": "Paris Masters",
            "City": "Paris", "Country": "France", "Date": "26-Oct", "End Date": "1-Nov",
            "Surface": "Hard", "Setting": "Indoor", "Altitude (m)": 35,
            "OddsPapi Tournament ID": pd.NA,
        },
    ])
    r = resolve_authority(
        "ATP Paris, France Men Singles", 2026,
        tour="MEN", match_date="2026-10-28", table=df,
    )
    assert r is not None
    assert r["Tournament Name"] == "Paris Masters"
    assert r["Surface"] == "Hard"


def test_same_city_overlapping_events_fail_closed_instead_of_guessing():
    df = pd.DataFrame([
        {
            "Year": 2026, "Circuit Tour": "ATP 250", "Tournament Name": "Paris Event A",
            "City": "Paris", "Country": "France", "Date": "1-Sep", "End Date": "7-Sep",
            "Surface": "Hard", "Setting": "Indoor", "Altitude (m)": 35,
            "OddsPapi Tournament ID": pd.NA,
        },
        {
            "Year": 2026, "Circuit Tour": "ATP 250", "Tournament Name": "Paris Event B",
            "City": "Paris", "Country": "France", "Date": "1-Sep", "End Date": "7-Sep",
            "Surface": "Clay", "Setting": "Outdoor", "Altitude (m)": 35,
            "OddsPapi Tournament ID": pd.NA,
        },
    ])
    r = resolve_authority(
        "ATP Paris, France Men Singles", 2026,
        tour="MEN", match_date="2026-09-03", table=df,
    )
    assert r is None
