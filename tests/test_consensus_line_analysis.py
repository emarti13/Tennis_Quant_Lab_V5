import pandas as pd
from consensus_line_analysis import consensus_spread, consensus_total


def test_consensus_spread_uses_one_median_player_a_line_per_fixture():
    rows = pd.DataFrame([
        {"fixture_id":"1","tour":"MEN","selection":"A","player_a":"A","line":-2.5,"pred_margin_a":4.0,"actual_margin_a":3.0},
        {"fixture_id":"1","tour":"MEN","selection":"A","player_a":"A","line":-3.0,"pred_margin_a":4.0,"actual_margin_a":3.0},
        {"fixture_id":"1","tour":"MEN","selection":"A","player_a":"A","line":-3.5,"pred_margin_a":4.0,"actual_margin_a":3.0},
    ])
    result = consensus_spread(rows)
    assert len(result) == 1
    assert result.iloc[0].line == -3.0
    assert result.iloc[0].outcome == "PUSH"


def test_consensus_total_uses_one_median_line_per_fixture():
    rows = pd.DataFrame([
        {"fixture_id":"2","tour":"WTA","line":21.5,"pred_total":23.0,"actual_total":24.0},
        {"fixture_id":"2","tour":"WTA","line":22.0,"pred_total":23.0,"actual_total":24.0},
        {"fixture_id":"2","tour":"WTA","line":22.5,"pred_total":23.0,"actual_total":24.0},
    ])
    result = consensus_total(rows)
    assert len(result) == 1
    assert result.iloc[0].line == 22.0
    assert result.iloc[0].outcome == "WIN"
