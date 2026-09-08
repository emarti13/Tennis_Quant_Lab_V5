import pandas as pd

from v5_recommendation_ledger import update_official_recommendations


def _obs(signal, odds, ts, *, start="2026-09-08T18:00:00Z", prob=0.60):
    return pd.DataFrame([{
        "fixture_id": "fx1",
        "market_group": "moneyline",
        "selection": "Player One",
        "line": None,
        "market_key": "fx1|moneyline|player one|",
        "signal": signal,
        "best_american_odds": odds,
        "best_decimal_odds": 2.0 if odds == 100 else 1.91,
        "model_probability": prob,
        "expected_value": 0.08,
        "edge_vs_consensus": 0.04,
        "snapshot_utc": ts,
        "start_time_utc": start,
        "model_version": "v5-model-1",
        "selected_model_candidate": "ensemble",
        "score_model_version": "v5-score-1",
        "selected_score_candidate": "conditioned_mechanistic",
    }])


def test_pass_and_review_do_not_create_official_recommendations():
    ledger, audit = update_official_recommendations(pd.DataFrame(), _obs("PASS", -110, "2026-09-08T12:00:00Z"))
    assert ledger.empty
    ledger, audit = update_official_recommendations(ledger, _obs("REVIEW", -105, "2026-09-08T12:15:00Z"), audit)
    assert ledger.empty


def test_first_bet_crossing_freezes_exactly_one_immutable_record():
    ledger, audit = update_official_recommendations(pd.DataFrame(), _obs("BET", 100, "2026-09-08T12:00:00Z"))
    assert len(ledger) == 1
    first = ledger.iloc[0].copy()
    ledger, audit = update_official_recommendations(ledger, _obs("BET", 130, "2026-09-08T14:00:00Z", prob=0.62), audit)
    assert len(ledger) == 1
    row = ledger.iloc[0]
    assert row["official_signal"] == "BET"
    assert row["official_price_american"] == first["official_price_american"] == 100
    assert row["official_model_probability"] == first["official_model_probability"] == 0.60
    assert row["official_at_utc"] == first["official_at_utc"] == "2026-09-08T12:00:00Z"


def test_lean_can_be_superseded_by_bet_before_match_start_without_duplicate_settlement_row():
    ledger, audit = update_official_recommendations(pd.DataFrame(), _obs("LEAN", -110, "2026-09-08T11:00:00Z"))
    assert len(ledger) == 1
    assert ledger.iloc[0]["official_signal"] == "LEAN"

    ledger, audit = update_official_recommendations(ledger, _obs("BET", 100, "2026-09-08T12:00:00Z"), audit)
    assert len(ledger) == 1
    assert ledger.iloc[0]["official_signal"] == "BET"
    assert ledger.iloc[0]["official_at_utc"] == "2026-09-08T12:00:00Z"
    assert (audit["event"] == "LEAN_SUPERSEDED_BY_BET").any()


def test_no_official_recommendation_after_match_start():
    ledger, audit = update_official_recommendations(
        pd.DataFrame(),
        _obs("BET", 100, "2026-09-08T18:01:00Z", start="2026-09-08T18:00:00Z"),
    )
    assert ledger.empty
    assert (audit["event"] == "BLOCKED_POST_START").any()
