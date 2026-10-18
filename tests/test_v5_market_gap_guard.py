"""Model guard: a model price far from the market's fair price is REVIEW, never BET or LEAN."""
import pandas as pd
import pytest

from v5_production_artifacts import stable_market_key
from v5_reprice_markets import MARKET_GAP_LIMIT, apply_market_gap_guard, market_reference, reprice_market_snapshot


def _book(fid, book, a, b):
    return [{"fixture_id": fid, "bookmaker": book, "market_group": "moneyline", "selection": "A", "decimal_odds": a},
            {"fixture_id": fid, "bookmaker": book, "market_group": "moneyline", "selection": "B", "decimal_odds": b}]


def test_reference_is_pinnacle_de_vigged_and_only_pinnacle():
    ref = market_reference(pd.DataFrame(_book("f1", "pinnacle", 1.80, 2.10) + _book("f1", "bet365", 1.50, 2.70)))
    assert len(ref) == 2 and set(ref["reference_source"]) == {"pinnacle"}
    assert ref["reference_probability"].sum() == pytest.approx(1.0)


def test_a_gap_above_the_limit_becomes_review_and_a_small_gap_keeps_its_signal():
    rows = pd.DataFrame([
        {"market_key": stable_market_key("f1", "moneyline", "A"), "model_probability": 0.75, "signal": "BET"},
        {"market_key": stable_market_key("f2", "moneyline", "A"), "model_probability": 0.60, "signal": "BET"},
    ])
    ref = pd.DataFrame([{"market_key": stable_market_key("f1", "moneyline", "A"), "reference_probability": 0.55, "reference_source": "pinnacle"},
                        {"market_key": stable_market_key("f2", "moneyline", "A"), "reference_probability": 0.50, "reference_source": "pinnacle"}])
    out = apply_market_gap_guard(rows, ref).set_index("market_key")
    flagged, kept = out.iloc[0], out.iloc[1]
    assert flagged["signal"] == "REVIEW" and flagged["guard_reason"] == "MODEL_MARKET_GAP"
    assert flagged["model_market_gap"] == pytest.approx(0.20) and flagged["model_market_gap"] > MARKET_GAP_LIMIT
    assert kept["signal"] == "BET" and kept["guard_reason"] == ""


def test_without_pinnacle_the_consensus_fair_price_is_the_reference():
    rows = pd.DataFrame([{"market_key": "k", "model_probability": 0.80, "signal": "BET", "consensus_no_vig_prob": 0.55}])
    out = apply_market_gap_guard(rows, None).iloc[0]
    assert out["market_reference_source"] == "consensus" and out["signal"] == "REVIEW"


def test_repricing_applies_the_guard():
    prices = pd.DataFrame([{"fixture_id": "f1", "market_group": "moneyline", "selection": "A", "line": None,
                            "best_decimal_odds": 2.4, "consensus_no_vig_prob": 0.41}])
    frozen = pd.DataFrame([{"market_key": stable_market_key("f1", "moneyline", "A"), "model_probability": 0.70,
                            "model_win_probability": 0.70, "model_push_probability": 0.0}])
    out = reprice_market_snapshot(prices, frozen, prices_fresh=True).iloc[0]
    assert out["expected_value"] > 0.05 and out["signal"] == "REVIEW"     # EV alone would say BET
