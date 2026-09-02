from pathlib import Path

import numpy as np
import pandas as pd

from diagnose_v5_context_model import probability_band_report, feature_coverage_report, load_tournament_registry


def test_probability_band_report_separates_longshots_and_favorites():
    frame = pd.DataFrame({
        "target_a_win": [0, 0, 1, 0, 1, 1],
        "baseline_a_probability": [.05, .15, .35, .65, .85, .95],
        "candidate_probability": [.08, .18, .40, .60, .82, .92],
    })
    report = probability_band_report(frame, probability_col="candidate_probability")
    assert report["under_10"]["n"] == 1
    assert report["10_to_20"]["n"] == 1
    assert report["80_to_90"]["n"] == 1
    assert report["over_90"]["n"] == 1
    assert np.isclose(report["under_10"]["mean_prediction"], .08)
    assert report["under_10"]["actual_win_rate"] == 0
    assert report["over_90"]["actual_win_rate"] == 1


def test_feature_coverage_reports_non_missing_fraction_and_constant_features():
    frame = pd.DataFrame({
        "ctx_a": [1.0, 2.0, np.nan, 4.0],
        "ctx_b": [0.0, 0.0, 0.0, 0.0],
        "ctx_c": [np.nan, np.nan, np.nan, np.nan],
        "other": [1, 2, 3, 4],
    })
    report = feature_coverage_report(frame)
    assert report["ctx_a"]["non_missing_fraction"] == .75
    assert report["ctx_a"]["constant"] is False
    assert report["ctx_b"]["constant"] is True
    assert report["ctx_c"]["non_missing_fraction"] == 0.0
    assert report["ctx_c"]["constant"] is True


def test_load_tournament_registry_reads_persisted_registry(tmp_path: Path):
    registry_dir = tmp_path / "context_registry"
    registry_dir.mkdir()
    pd.DataFrame([
        {"canonical_event_id":"MEN:0600","canonical_name":"Canada","tour":"MEN","start_year":2026,"end_year":2026,"city":"Montreal","latitude":45.5,"longitude":-73.6,"timezone":"America/Toronto","altitude_m":36},
    ]).to_csv(registry_dir / "tournaments.csv", index=False)
    registry = load_tournament_registry(tmp_path)
    assert len(registry) == 1
    assert registry.iloc[0]["city"] == "Montreal"


def test_load_tournament_registry_is_explicit_when_registry_missing(tmp_path: Path):
    registry = load_tournament_registry(tmp_path)
    assert registry.empty
