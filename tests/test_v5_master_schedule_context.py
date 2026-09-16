from pathlib import Path

import pandas as pd

from v5_master_schedule_context import enrich_daily_board_context, resolve_master_schedule_context


SCHEDULE = Path(__file__).resolve().parents[1] / "context_registry" / "tennis_master_schedule.csv"


def test_current_challenger_provider_names_resolve_to_2026_schedule():
    expected = {
        "ATP Challenger Columbus, USA Men Singles": ("Hard", "Indoor", 275),
        "ATP Challenger Saint Tropez, France Men Singles": ("Hard", "Outdoor", 10),
        "ATP Challenger Bad Waltersdorf, Austria Men Singles": ("Clay", "Outdoor", 291),
        "ATP Challenger Bogota, Colombia Men Singles": ("Clay", "Outdoor", 2640),
    }
    for tournament, values in expected.items():
        result = resolve_master_schedule_context(tournament, "MEN", year=2026, schedule_path=SCHEDULE)
        assert result is not None, tournament
        assert (result["surface"], result["environment"], result["altitude_m"]) == values


def test_current_wta_sao_paulo_resolves_hard_not_challenger_clay():
    result = resolve_master_schedule_context(
        "WTA Sao Paulo, Brazil Women, Singles", "WTA", year=2026, schedule_path=SCHEDULE
    )
    assert result is not None
    assert result["official_tournament"] == "SP Open"
    assert result["surface"] == "Hard"
    assert result["environment"] == "Outdoor"


def test_enrichment_fills_missing_context_without_overwriting_existing_values():
    frame = pd.DataFrame([{
        "Tournament": "ATP Challenger Columbus, USA Men Singles", "Tour": "MEN",
        "Surface": None, "Environment": "Outdoor", "Altitude m": None, "Ball Type": None,
    }])
    out = enrich_daily_board_context(frame, year=2026, schedule_path=SCHEDULE)
    assert out.loc[0, "Surface"] == "Hard"
    assert out.loc[0, "Environment"] == "Outdoor"  # existing explicit value is preserved
    assert out.loc[0, "Altitude m"] == 275
    assert out.loc[0, "Ball Type"] == "Regular Duty"
