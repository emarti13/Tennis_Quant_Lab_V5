from pathlib import Path


def test_court_conditions_runtime_is_snapshot_only():
    source = Path("v5_court_conditions_source.py").read_text(encoding="utf-8")
    lowered = source.lower()
    assert "requests" not in lowered
    assert "http://" not in lowered
    assert "https://" not in lowered
    assert "read_csv" in source


def test_full_context_runtime_uses_adapter_not_web_calls():
    source = Path("v5_full_context_live.py").read_text(encoding="utf-8")
    assert "lookup_court_conditions" in source
    assert "courtspeed.com" not in source.lower()
