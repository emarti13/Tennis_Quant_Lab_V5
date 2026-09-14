from __future__ import annotations

import pandas as pd


def _row(**overrides):
    row = {
        "fixture_id": "fx-1",
        "start_time_utc": "2026-01-01T12:00:00Z",
        "market_group": "moneyline",
        "selection": "Alpha",
        "line": None,
        "expected_value": 0.08,
        "edge_vs_consensus": 0.04,
        "state_confidence": 0.42,
        "surface_source": "CourtSpeed",
        "production_market_enabled": True,
        "settled_result": "WIN",
        "profit_units": 1.5,
        "model_probability": 0.55,
        "best_american_odds": 150,
        "tour_v5": "MEN",
        "surface": "Hard",
    }
    row.update(overrides)
    return pd.Series(row)


def test_replay_isolates_confidence_gate_from_pricing_signal():
    from diagnose_signal_confidence_gate import pricing_signal_without_confidence, replay_signal

    row = _row()
    assert pricing_signal_without_confidence(row) == "BET"
    assert replay_signal(row, 0.45) == "REVIEW"
    assert replay_signal(row, 0.40) == "BET"


def test_non_confidence_review_gates_remain_review():
    from diagnose_signal_confidence_gate import pricing_signal_without_confidence, replay_signal

    surface_review = _row(state_confidence=0.90, surface_source="Auto default — review")
    disabled_market = _row(state_confidence=0.90, market_group="game_spread", production_market_enabled=False)
    assert pricing_signal_without_confidence(surface_review) == "REVIEW"
    assert replay_signal(surface_review, 0.0) == "REVIEW"
    assert pricing_signal_without_confidence(disabled_market) == "REVIEW"
    assert replay_signal(disabled_market, 0.0) == "REVIEW"


def test_policy_replay_does_not_depend_on_stored_signal():
    from diagnose_signal_confidence_gate import replay_signal

    a = _row(signal="REVIEW")
    b = _row(signal="BET")
    assert replay_signal(a, 0.40) == replay_signal(b, 0.40) == "BET"


def test_fixture_cap_selects_one_best_actionable_market():
    from diagnose_signal_confidence_gate import select_fixture_actions

    frame = pd.DataFrame([
        dict(_row(fixture_id="fx-1", selection="A", expected_value=0.06, edge_vs_consensus=0.03)),
        dict(_row(fixture_id="fx-1", selection="B", expected_value=0.11, edge_vs_consensus=0.05)),
        dict(_row(fixture_id="fx-2", selection="C", expected_value=0.03, edge_vs_consensus=0.015, settled_result="LOSS", profit_units=-1.0)),
    ])
    picked = select_fixture_actions(frame, threshold=0.40)
    assert len(picked) == 2
    assert picked[picked["fixture_id"] == "fx-1"].iloc[0]["selection"] == "B"


def test_policy_metrics_include_units_roi_and_drawdown():
    from diagnose_signal_confidence_gate import policy_metrics

    frame = pd.DataFrame([
        {"fixture_id": "a", "start_time_utc": "2026-01-01", "settled_result": "WIN", "profit_units": 1.0, "expected_value": .05, "edge_vs_consensus": .03, "state_confidence": .7},
        {"fixture_id": "b", "start_time_utc": "2026-01-02", "settled_result": "LOSS", "profit_units": -1.0, "expected_value": .05, "edge_vs_consensus": .03, "state_confidence": .7},
        {"fixture_id": "c", "start_time_utc": "2026-01-03", "settled_result": "LOSS", "profit_units": -1.0, "expected_value": .05, "edge_vs_consensus": .03, "state_confidence": .7},
    ])
    m = policy_metrics(frame)
    assert m["bets"] == 3
    assert m["net_units"] == -1.0
    assert m["roi"] == -1.0 / 3.0
    assert m["max_drawdown_units"] == 2.0
