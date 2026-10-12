"""The guard must catch every planted bug and stay quiet on clean data."""
import v5_model_guard as G


def test_guard_selftest_catches_planted_bugs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)          # selftest writes a scratch history file
    assert G.selftest()
