import numpy as np
import pandas as pd

from v5_tournament_score_challenger import evaluate_score_challenger_frame


def _frame():
    rows=[]
    for year,n in ((2025,120),(2026,100)):
        for i in range(n):
            x=(i-(n/2))/30.0
            auth=((i % 9)-4)/4.0
            rows.append({
                "year":year,
                "x_sr_a":x,
                "x_elo_a":0.4*x,
                "ctx_serve_dominance_diff":0.2*x,
                "ctx_return_dominance_diff":-0.15*x,
                "ctx_rank_diff":0.1*x,
                "ctx_auth_altitude_x_serve_dom":auth,
                "ctx_auth_altitude_x_serve_dep":0.5*auth,
                "actual_margin_a":2.0*x+2.2*auth+0.15*np.sin(i),
                "actual_total":22.0+1.5*abs(x)+1.3*abs(auth)+0.1*np.cos(i),
            })
    return pd.DataFrame(rows)


def test_score_challenger_reports_spread_and_total_deltas_separately():
    report=evaluate_score_challenger_frame(_frame(),fit_year=2025,validation_year=2026)
    assert report["validation_rows"] == 100
    assert "control" in report["models"]
    assert "altitude" in report["models"]
    delta=report["deltas_vs_control"]["altitude"]
    assert set(("margin_crps_gain","total_crps_gain","margin_rmse_ratio","total_rmse_ratio")) <= set(delta)
    assert report["eligibility"]["altitude"]["spread"] is True
    assert report["eligibility"]["altitude"]["total"] is True
