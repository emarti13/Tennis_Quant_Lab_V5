import numpy as np
import pandas as pd

from v5_tournament_context_registry import (
    apply_overrides,
    canonical_tournament_key,
    load_overrides,
    upsert_tournament_context,
)


def test_tournament_context_persists_and_is_inherited(tmp_path):
    path = tmp_path / "tournament_context_overrides.csv"
    upsert_tournament_context(path, "Cincinnati ATP", {"surface": "Hard", "external_altitude_m": 147.0, "external_ball_type": "Wilson US Open"})

    fresh = load_overrides(path)
    slate = pd.DataFrame([{"tournament": "Cincinnati ATP", "surface": np.nan, "external_altitude_m": np.nan, "external_ball_type": np.nan}])
    resolved = apply_overrides(slate, fresh)

    assert resolved.loc[0, "surface"] == "Hard"
    assert resolved.loc[0, "external_altitude_m"] == 147.0
    assert resolved.loc[0, "external_ball_type"] == "Wilson US Open"


def test_later_edit_replaces_only_supplied_value(tmp_path):
    path = tmp_path / "tournament_context_overrides.csv"
    upsert_tournament_context(path, "Cincinnati ATP", {"surface": "Hard", "external_ball_type": "Wilson US Open"})
    upsert_tournament_context(path, "Cincinnati ATP", {"external_ball_type": "Dunlop ATP"})

    row = load_overrides(path).iloc[0]
    assert row["surface"] == "Hard"
    assert row["external_ball_type"] == "Dunlop ATP"


def test_missing_context_remains_missing_not_zero(tmp_path):
    path = tmp_path / "tournament_context_overrides.csv"
    upsert_tournament_context(path, "Cincinnati ATP", {"surface": "Hard"})
    slate = pd.DataFrame([{"tournament": "Cincinnati ATP", "external_altitude_m": np.nan}])

    resolved = apply_overrides(slate, load_overrides(path))

    assert pd.isna(resolved.loc[0, "external_altitude_m"])


def test_canonical_key_is_stable_across_tour_decorations():
    assert canonical_tournament_key("ATP Cincinnati") == canonical_tournament_key("Cincinnati ATP")
