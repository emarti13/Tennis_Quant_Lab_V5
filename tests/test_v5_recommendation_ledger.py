import pandas as pd

from v5_recommendation_ledger import update_official_recommendations


def _obs(signal, odds, ts, *, start="2026-09-08T18:00:00Z", prob=0.60, fixture="fx1", key="fx1|moneyline|player one|", group="moneyline", selection="Player One", line=None):
    return pd.DataFrame([{
        "fixture_id": fixture, "market_group": group, "selection": selection, "line": line, "market_key": key,
        "signal": signal, "best_american_odds": odds, "best_decimal_odds": 2.0 if odds == 100 else 1.91,
        "model_probability": prob, "expected_value": 0.08, "edge_vs_consensus": 0.04,
        "snapshot_utc": ts, "start_time_utc": start, "model_version": "v5-model-1",
        "selected_model_candidate": "ensemble", "score_model_version": "v5-score-1",
        "selected_score_candidate": "conditioned_mechanistic",
    }])


def test_pass_and_review_do_not_create_official_recommendations():
    ledger, audit = update_official_recommendations(pd.DataFrame(), _obs("PASS", -110, "2026-09-08T12:00:00Z"))
    ledger, audit = update_official_recommendations(ledger, _obs("REVIEW", -105, "2026-09-08T12:15:00Z"), audit)
    assert ledger.empty


def test_same_market_first_bet_is_immutable():
    ledger, audit = update_official_recommendations(pd.DataFrame(), _obs("BET", 100, "2026-09-08T12:00:00Z"))
    ledger, audit = update_official_recommendations(ledger, _obs("BET", 130, "2026-09-08T14:00:00Z", prob=.62), audit)
    assert len(ledger) == 1
    assert ledger.iloc[0]["official_price_american"] == 100
    assert ledger.iloc[0]["official_model_probability"] == .60


def test_same_market_lean_can_upgrade_to_bet_before_start():
    ledger, audit = update_official_recommendations(pd.DataFrame(), _obs("LEAN", -110, "2026-09-08T11:00:00Z"))
    ledger, audit = update_official_recommendations(ledger, _obs("BET", 100, "2026-09-08T12:00:00Z"), audit)
    assert len(ledger) == 1
    assert ledger.iloc[0]["official_signal"] == "BET"
    assert (audit["event"] == "LEAN_SUPERSEDED_BY_BET").any()


def test_multiple_actionable_markets_same_fixture_are_independent_official_recommendations():
    rows = pd.concat([
        _obs("BET", 100, "2026-09-08T12:00:00Z"),
        _obs("BET", 154, "2026-09-08T12:00:00Z", key="fx1|spread|player two|3.5", group="spread", selection="Player Two", line=3.5),
        _obs("LEAN", 104, "2026-09-08T12:00:00Z", key="fx1|total|over|22.5", group="total", selection="Over", line=22.5),
    ], ignore_index=True)
    ledger, _ = update_official_recommendations(pd.DataFrame(), rows)
    assert len(ledger) == 3
    assert set(ledger["market_key"]) == set(rows["market_key"])


def test_no_official_recommendation_after_match_start():
    ledger, audit = update_official_recommendations(pd.DataFrame(), _obs("BET", 100, "2026-09-08T18:01:00Z"))
    assert ledger.empty
    assert (audit["event"] == "BLOCKED_POST_START").any()


def test_missing_start_or_snapshot_fails_closed():
    no_start = _obs("BET", 100, "2026-09-08T12:00:00Z").assign(start_time_utc=None)
    ledger, audit = update_official_recommendations(pd.DataFrame(), no_start)
    assert ledger.empty and (audit["event"] == "BLOCKED_MISSING_START").any()
    no_snapshot = _obs("BET", 100, "2026-09-08T12:00:00Z").assign(snapshot_utc=None)
    ledger, audit = update_official_recommendations(pd.DataFrame(), no_snapshot)
    assert ledger.empty and (audit["event"] == "BLOCKED_MISSING_SNAPSHOT").any()


def test_settled_market_is_not_rewritten_by_later_repricing():
    ledger, audit = update_official_recommendations(pd.DataFrame(), _obs("BET", 100, "2026-09-08T12:00:00Z"))
    ledger.loc[0, "result_status"] = "SETTLED"; ledger.loc[0, "settled_result"] = "WIN"; ledger.loc[0, "profit_units"] = 1.0
    updated, _ = update_official_recommendations(ledger, _obs("BET", 140, "2026-09-08T13:00:00Z"), audit)
    assert len(updated) == 1
    assert updated.loc[0, "settled_result"] == "WIN"
    assert updated.loc[0, "official_price_american"] == 100
