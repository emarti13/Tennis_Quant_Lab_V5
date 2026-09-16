import pytest

from v5_canonical_schedule import (
    canonical_tournament_id,
    normalize_schedule_surface,
    resolve_canonical_tournament,
)


@pytest.mark.parametrize(
    "code, expected",
    [
        ("H", ("Hard", "Outdoor")),
        ("IH", ("Hard", "Indoor")),
        ("I H", ("Hard", "Indoor")),
        ("C", ("Clay", "Outdoor")),
        ("CL", ("Clay", "Outdoor")),
        ("IC", ("Clay", "Indoor")),
        ("I C", ("Clay", "Indoor")),
        ("G", ("Grass", "Outdoor")),
    ],
)
def test_schedule_surface_normalization_preserves_environment(code, expected):
    assert normalize_schedule_surface(code) == expected


def test_canonical_id_discriminates_season_tour_category_and_location():
    wta = canonical_tournament_id(2026, "WTA", "WTA 250", "SP Open", "Sao Paulo")
    challenger = canonical_tournament_id(2026, "ATP", "Challenger 100", "Sao Paulo", "Sao Paulo")
    old_wta125 = canonical_tournament_id(2025, "WTA", "WTA 125", "Sao Paulo 125", "Sao Paulo")

    assert len({wta, challenger, old_wta125}) == 3


def test_wta_sao_paulo_feed_alias_resolves_to_hard_wta_event_not_challenger():
    resolved = resolve_canonical_tournament(
        "WTA Sao Paulo, Brazil Women, Singles",
        season=2026,
        tour="WTA",
        event_date="2026-09-16",
    )

    assert resolved["official_name"] == "SP Open"
    assert resolved["surface"] == "Hard"
    assert resolved["environment"] == "Outdoor"
    assert "challenger" not in resolved["canonical_id"]


def test_sao_paulo_challenger_resolves_to_distinct_clay_event():
    resolved = resolve_canonical_tournament(
        "Sao Paulo Challenger",
        season=2026,
        tour="ATP",
        category="Challenger 100",
        event_date="2026-03-25",
    )

    assert resolved["surface"] == "Clay"
    assert resolved["environment"] == "Outdoor"
    assert resolved["canonical_id"] != resolve_canonical_tournament(
        "WTA Sao Paulo, Brazil Women, Singles",
        season=2026,
        tour="WTA",
        event_date="2026-09-16",
    )["canonical_id"]


def test_ambiguous_city_only_identity_fails_closed():
    assert resolve_canonical_tournament("Sao Paulo", season=2026) is None
