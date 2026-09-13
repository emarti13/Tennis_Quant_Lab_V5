import pandas as pd
import pytest

from v5_official_performance import official_performance_report
from v5_reprice_markets import update_repricing_artifacts
from v5_settlement import settle_ledger


def _forecast():
    return pd.DataFrame([{
        "fixture_id": "fx1",
        "forecast_date": "2026-09-08",
        "market_group": "moneyline",
        "selection": "Player One",
        "line": None,
        "market_key": "fx1|moneyline|player one|",
        "model_probability": 0.60,
        "model_win_probability": 0.60,
        "model_push_probability": 0.0,
        "model_loss_probability": 0.40,
        "model_fair_american": -150.0,
        "state_confidence": 0.90,
        "surface_source": "Auto — tournament map",
        "model_version": "v5-model-1",
        "selected_model_candidate": "ensemble",
        "score_model_version": "v5-score-1",
        "selected_score_candidate": "conditioned_mechanistic",
    }])


def _price(american, decimal, consensus, snapshot):
    return pd.DataFrame([{
        "snapshot_utc": snapshot,
        "fixture_id": "fx1",
        "start_time_utc": "2026-09-08T18:00:00Z",
        "tournament": "US Open Men Singles",
        "tour": "ATP",
        "player1": "Player One",
        "player2": "Player Two",
        "resolved_player1": "Player One",
        "resolved_player2": "Player Two",
        "market_group": "moneyline",
        "selection": "Player One",
        "line": None,
        "best_bookmaker": "pinnacle",
        "best_decimal_odds": decimal,
        "best_american_odds": american,
        "consensus_no_vig_prob": consensus,
    }])


def test_daily_forecast_four_price_refreshes_one_official_record_one_settlement():
    frozen = _forecast()
    official = pd.DataFrame()
    audit = pd.DataFrame()
    first_official = None

    snapshots = [
        (100, 2.00, 0.49, "2026-09-08T10:00:00Z"),
        (120, 2.20, 0.47, "2026-09-08T12:00:00Z"),
        (-105, 1.952, 0.53, "2026-09-08T14:00:00Z"),
        (135, 2.35, 0.45, "2026-09-08T16:00:00Z"),
    ]

    for american, decimal, consensus, timestamp in snapshots:
        repriced, official, audit = update_repricing_artifacts(
            _price(american, decimal, consensus, timestamp),
            frozen,
            prices_fresh=True,
            existing_official=official,
            existing_audit=audit,
        )
        assert repriced.iloc[0]["model_probability"] == pytest.approx(0.60)
        assert len(official) <= 1
        if len(official) == 1 and first_official is None:
            first_official = official.iloc[0].copy()

    assert first_official is not None
    assert len(official) == 1
    assert official.iloc[0]["market_key"] == "fx1|moneyline|player one|"
    assert official.iloc[0]["official_at_utc"] == first_official["official_at_utc"]
    assert official.iloc[0]["official_price_american"] == first_official["official_price_american"]
    assert official.iloc[0]["official_model_probability"] == pytest.approx(0.60)

    results = pd.DataFrame([{
        "winner_name": "Player One",
        "loser_name": "Player Two",
        "tourney_date": 20260907,
        "tourney_name": "US Open",
        "score": "6-4 6-4",
    }])
    settled, stats = settle_ledger(official, results, settled_at="2026-09-08T20:00:00Z")
    assert stats["settled"] == 1
    assert len(settled) == 1
    assert settled.iloc[0]["settled_result"] == "WIN"

    report = official_performance_report(settled)
    assert report["official_recommendations"] == 1
    assert report["unique_fixtures"] == 1
    assert report["wins"] == 1
    assert report["losses"] == 0
