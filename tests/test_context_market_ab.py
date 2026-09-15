import pandas as pd

from context_market_ab import summarize_pair


def test_summarize_pair_reports_baseline_enhanced_and_delta():
    baseline = pd.DataFrame([
        {"fixture_id":"1","tour":"MEN","outcome":"WIN"},
        {"fixture_id":"2","tour":"MEN","outcome":"LOSS"},
    ])
    enhanced = pd.DataFrame([
        {"fixture_id":"1","tour":"MEN","outcome":"WIN"},
        {"fixture_id":"2","tour":"MEN","outcome":"WIN"},
    ])
    result = summarize_pair(baseline, enhanced)
    assert result["MEN"]["baseline"]["accuracy"] == 0.5
    assert result["MEN"]["enhanced"]["accuracy"] == 1.0
    assert result["MEN"]["delta_accuracy_pp"] == 50.0
    assert result["MEN"]["matched_fixtures"] == 2


def test_summarize_pair_uses_only_common_fixtures():
    baseline = pd.DataFrame([
        {"fixture_id":"1","tour":"WTA","outcome":"WIN"},
        {"fixture_id":"2","tour":"WTA","outcome":"LOSS"},
    ])
    enhanced = pd.DataFrame([
        {"fixture_id":"1","tour":"WTA","outcome":"LOSS"},
        {"fixture_id":"3","tour":"WTA","outcome":"WIN"},
    ])
    result = summarize_pair(baseline, enhanced)
    assert result["WTA"]["matched_fixtures"] == 1
    assert result["WTA"]["baseline"]["accuracy"] == 1.0
    assert result["WTA"]["enhanced"]["accuracy"] == 0.0
