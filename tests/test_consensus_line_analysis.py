import pandas as pd
from consensus_line_analysis import consensus_spread, consensus_total


def test_consensus_spread_uses_one_primary_line_per_book_then_median():
    rows = pd.DataFrame([
        {"fixture_id":"1","tour":"MEN","bookmaker":"a","selection":"Player Á","player_a":"player a","line":-2.5,"no_vig_prob":.58,"pred_margin_a":4.0,"actual_margin_a":3.0},
        {"fixture_id":"1","tour":"MEN","bookmaker":"a","selection":"Player Á","player_a":"player a","line":-3.0,"no_vig_prob":.50,"pred_margin_a":4.0,"actual_margin_a":3.0},
        {"fixture_id":"1","tour":"MEN","bookmaker":"a","selection":"Player Á","player_a":"player a","line":-3.5,"no_vig_prob":.43,"pred_margin_a":4.0,"actual_margin_a":3.0},
        {"fixture_id":"1","tour":"MEN","bookmaker":"b","selection":"Player Á","player_a":"player a","line":-2.5,"no_vig_prob":.52,"pred_margin_a":4.0,"actual_margin_a":3.0},
        {"fixture_id":"1","tour":"MEN","bookmaker":"b","selection":"Player Á","player_a":"player a","line":-3.0,"no_vig_prob":.46,"pred_margin_a":4.0,"actual_margin_a":3.0},
    ])
    result = consensus_spread(rows)
    assert len(result) == 1
    assert result.iloc[0].line == -2.75
    assert result.iloc[0].outcome == "WIN"


def test_consensus_total_uses_one_primary_line_per_book_then_median():
    rows = pd.DataFrame([
        {"fixture_id":"2","tour":"WTA","bookmaker":"a","market_id":"21","line":21.5,"no_vig_prob":.56,"pred_total":23.0,"actual_total":24.0},
        {"fixture_id":"2","tour":"WTA","bookmaker":"a","market_id":"22","line":22.0,"no_vig_prob":.50,"pred_total":23.0,"actual_total":24.0},
        {"fixture_id":"2","tour":"WTA","bookmaker":"a","market_id":"23","line":22.5,"no_vig_prob":.45,"pred_total":23.0,"actual_total":24.0},
        {"fixture_id":"2","tour":"WTA","bookmaker":"b","market_id":"31","line":21.5,"no_vig_prob":.51,"pred_total":23.0,"actual_total":24.0},
        {"fixture_id":"2","tour":"WTA","bookmaker":"b","market_id":"32","line":22.0,"no_vig_prob":.46,"pred_total":23.0,"actual_total":24.0},
    ])
    result = consensus_total(rows)
    assert len(result) == 1
    assert result.iloc[0].line == 21.75
    assert result.iloc[0].outcome == "WIN"
