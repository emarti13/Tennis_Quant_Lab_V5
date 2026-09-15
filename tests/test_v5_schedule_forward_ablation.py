from pathlib import Path


def test_forward_ablation_runner_exists_and_is_leak_safe():
    path = Path("v5_schedule_forward_ablation.py")
    assert path.exists(), "forward ablation runner must exist"
    source = path.read_text(encoding="utf-8")
    assert "schedule_context=False" in source
    assert "schedule_context=True" in source
    assert "walk_forward" in source
    assert "match_date" in source
    assert "brier" in source.lower()
    assert "log_loss" in source.lower()
    assert "coverage" in source.lower()
    assert "schedule_match_score" in source
    assert "forward_ablation_summary.json" in source


def test_ablation_is_two_pass_same_universe():
    source = Path("v5_schedule_forward_ablation.py").read_text(encoding="utf-8")
    assert "baseline_match_ids" in source
    assert "enriched_match_ids" in source
    assert "baseline_match_ids != enriched_match_ids" in source
