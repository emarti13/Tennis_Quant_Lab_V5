import pandas as pd

from v5_reprice_markets import update_repricing_artifacts
from v5_run_repricing import _append_market_history


def _market(market_key, group, selection, signal, ev):
    return {
        "fixture_id": "fx1",
        "market_key": market_key,
        "market_group": group,
        "selection": selection,
        "line": 22.5 if group == "total" else None,
        "signal": signal,
        "expected_value": ev,
        "best_american_odds": 110,
        "best_decimal_odds": 2.10,
        "model_probability": 0.60,
        "model_win_probability": 0.60,
        "model_push_probability": 0.0,
        "edge_vs_consensus": 0.08,
        "consensus_no_vig_prob": 0.52,
        "snapshot_utc": "2026-09-14T12:00:00Z",
        "start_time_utc": "2026-09-14T18:00:00Z",
    }


def test_multiple_independent_actionable_markets_same_fixture_become_official():
    # Repricing is already complete here; monkeypatching is intentionally avoided.
    # Feed rows are passed as prices with matching frozen probabilities so the real
    # production handoff decides what enters the official ledger.
    prices = pd.DataFrame([
        _market("fx1|moneyline|p2|", "moneyline", "P2", "BET", .20),
        _market("fx1|spread|p2|3.5", "spread", "P2", "BET", .35),
        _market("fx1|total|over|22.5", "total", "Over", "LEAN", .12),
    ])
    frozen = prices[["market_key", "model_probability", "model_win_probability", "model_push_probability"]].copy()

    # Exercise the ledger handoff using already-repriced semantics by supplying
    # the actionable observations directly through a second-stage expectation:
    from v5_recommendation_ledger import update_official_recommendations
    official, _ = update_official_recommendations(pd.DataFrame(), prices)

    assert set(official["market_key"]) == {
        "fx1|moneyline|p2|",
        "fx1|spread|p2|3.5",
        "fx1|total|over|22.5",
    }
    assert len(official) == 3


def test_ancillary_market_history_is_not_pruned_by_age():
    existing = pd.DataFrame([
        {"snapshot_utc": "2026-01-01T12:00:00Z", "market_key": "old|review", "signal": "REVIEW"},
        {"snapshot_utc": "2026-01-01T12:05:00Z", "market_key": "old|pass", "signal": "PASS"},
    ])
    fresh = pd.DataFrame([
        {"snapshot_utc": "2026-09-14T12:00:00Z", "market_key": "new|bet", "signal": "BET"},
    ])

    history = _append_market_history(existing, fresh, pd.Timestamp("2026-09-14T12:00:00Z"))

    assert set(history["market_key"]) == {"old|review", "old|pass", "new|bet"}
