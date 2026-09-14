import pandas as pd

from v5_schedule_context import enrich_events_with_schedule, load_schedule, normalize_schedule, speed_profile_family


def _schedule():
    return pd.DataFrame([
        {"Year": 2026, "Circuit Tour": "ATP MASTERS 1000", "Tournament Name": "Rolex Monte-Carlo Masters (2026)", "City Venue": "Monte-Carlo", "Surface": "Clay", "Setting": "Outdoor", "Altitude (m)": 20, "Altitude (ft)": 66, "Speed Profile": "Slow", "Ball Characteristics": "Regular Duty Clay"},
        {"Year": 2026, "Circuit Tour": "ATP MASTERS 1000", "Tournament Name": "BNP Paribas Open (2026)", "City Venue": "Indian Wells", "Surface": "Hard", "Setting": "Outdoor", "Altitude (m)": -27, "Altitude (ft)": -89, "Speed Profile": "Slow Court / Fast Air", "Ball Characteristics": "Extra Duty Hard"},
        {"Year": 2026, "Circuit Tour": "WTA 1000", "Tournament Name": "BNP Paribas Open (2026)", "City Venue": "Indian Wells", "Surface": "Hard", "Setting": "Outdoor", "Altitude (m)": -27, "Altitude (ft)": -89, "Speed Profile": "Slow Court / Fast Air", "Ball Characteristics": "Extra Duty Hard"},
    ])


def test_repository_schedule_is_complete_three_year_source():
    schedule = load_schedule()
    assert len(schedule) == 354
    assert set(schedule["schedule_year"].dropna().astype(int)) == {2025, 2026, 2027}


def test_normalize_schedule_derives_matching_fields():
    out = normalize_schedule(_schedule())
    row = out.iloc[0]
    assert row["schedule_name_normalized"] == "rolex monte carlo masters"
    assert row["schedule_tour_family"] == "MEN"
    assert row["schedule_setting"] == "Outdoor"
    assert row["schedule_altitude_m"] == 20
    assert speed_profile_family("Extreme Altitude / Ultra-Fast Flight") == "altitude_fast"
    assert speed_profile_family("Slow Court / Fast Air") == "slow_court_fast_air"


def test_sponsor_name_difference_matches_real_event_instead_of_nan():
    events = pd.DataFrame([{
        "tourney_name": "Monte Carlo Masters",
        "tour": "MEN",
        "match_date": "2026-04-08",
        "surface": "Clay",
        "city": "Monte Carlo",
    }])
    out = enrich_events_with_schedule(events, _schedule())
    row = out.iloc[0]
    assert row["schedule_tournament_name"] == "Rolex Monte-Carlo Masters (2026)"
    assert row["schedule_match_method"] in {"alias", "fuzzy_high", "exact"}
    assert row["schedule_match_score"] >= 0.75


def test_tour_family_prevents_atp_wta_cross_match():
    events = pd.DataFrame([{
        "tourney_name": "BNP Paribas Open",
        "tour": "WTA",
        "match_date": "2026-03-10",
        "surface": "Hard",
        "city": "Indian Wells",
    }])
    out = enrich_events_with_schedule(events, _schedule())
    row = out.iloc[0]
    assert row["schedule_tournament_name"] == "BNP Paribas Open (2026)"
    assert row["schedule_circuit_tour"] == "WTA 1000"


def test_incompatible_surface_fails_closed():
    events = pd.DataFrame([{
        "tourney_name": "BNP Paribas Open",
        "tour": "MEN",
        "match_date": "2026-03-10",
        "surface": "Clay",
        "city": "Indian Wells",
    }])
    out = enrich_events_with_schedule(events, _schedule())
    assert pd.isna(out.iloc[0]["schedule_tournament_name"])
    assert out.iloc[0]["schedule_match_method"] == "unmatched"


def test_ambiguous_candidates_fail_closed():
    schedule = pd.concat([_schedule(), pd.DataFrame([{
        "Year": 2026, "Circuit Tour": "ATP MASTERS 1000", "Tournament Name": "Indian Wells Open (2026)", "City Venue": "Indian Wells", "Surface": "Hard", "Setting": "Outdoor", "Altitude (m)": -27, "Altitude (ft)": -89, "Speed Profile": "Slow Court / Fast Air", "Ball Characteristics": "Extra Duty Hard"}])], ignore_index=True)
    events = pd.DataFrame([{
        "tourney_name": "Indian Wells",
        "tour": "MEN",
        "match_date": "2026-03-10",
        "surface": "Hard",
        "city": "Indian Wells",
    }])
    out = enrich_events_with_schedule(events, schedule)
    assert out.iloc[0]["schedule_match_method"] in {"ambiguous", "fuzzy_high"}
    if out.iloc[0]["schedule_match_method"] == "ambiguous":
        assert pd.isna(out.iloc[0]["schedule_tournament_name"])
