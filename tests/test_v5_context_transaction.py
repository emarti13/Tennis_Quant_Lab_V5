import pandas as pd
import pytest

from v5_context_transaction import changed_context_values, commit_successful_adjustments


def _row(**changes):
    base = {
        "Tournament": "WTA Sao Paulo, Brazil Women, Singles",
        "Tour": "WTA", "Surface": "Hard", "Best Of": 3, "Environment": "Outdoor",
        "Court Speed": 0.1, "CPI": 38.0, "Ace Rate %": 5.0, "Rally Length": 4.5,
        "Relative Air Density": 0.92, "Altitude m": 760.0, "Ball Type": "Wilson",
    }
    base.update(changes)
    return pd.Series(base)


def test_changed_context_values_only_returns_actual_edits():
    original = _row()
    edited = _row(**{"CPI": 41.0, "Ball Type": "Dunlop"})
    assert changed_context_values(original, edited) == {
        "external_cpi_override": 41.0,
        "external_ball_type": "Dunlop",
    }


def test_failed_adjusted_run_never_calls_persistence(tmp_path):
    calls = []
    with pytest.raises(RuntimeError):
        commit_successful_adjustments(
            tmp_path / "overrides.csv", pd.DataFrame([_row()]), pd.DataFrame([_row(CPI=41.0)]),
            adjusted_run_succeeded=False, writer=lambda *args, **kwargs: calls.append((args, kwargs)),
        )
    assert calls == []
    assert not (tmp_path / "overrides.csv").exists()


def test_successful_adjusted_run_persists_only_changed_fields_and_verifies_readback(tmp_path):
    path = tmp_path / "overrides.csv"
    original = pd.DataFrame([_row()])
    edited = pd.DataFrame([_row(**{"CPI": 41.0, "Ball Type": "Dunlop"})])
    committed = commit_successful_adjustments(path, original, edited, adjusted_run_succeeded=True)
    assert committed == 1
    saved = pd.read_csv(path)
    assert saved.loc[0, "external_cpi_override"] == pytest.approx(41.0)
    assert saved.loc[0, "external_ball_type"] == "Dunlop"
    assert pd.isna(saved.loc[0].get("surface"))
