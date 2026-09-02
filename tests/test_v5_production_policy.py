import math

from v5_production_policy import score_segment, score_policy, apply_score_calibration, enforce_market_policy


def test_score_segment_maps_tour_and_best_of():
    assert score_segment("MEN", 3) == "MEN_BO3"
    assert score_segment("MEN", 5) == "MEN_BO5"
    assert score_segment("WTA", 3) == "WTA_BO3"


def test_disabled_score_market_is_forced_to_review_but_moneyline_is_unchanged():
    config = {"score_markets":{"MEN_BO5":{"enabled":False}}}
    assert enforce_market_policy("BET", "game_spread", "MEN", 5, config) == "REVIEW"
    assert enforce_market_policy("BET", "total_games", "MEN", 5, config) == "REVIEW"
    assert enforce_market_policy("BET", "moneyline", "MEN", 5, config) == "BET"


def test_enabled_score_policy_applies_common_offset_and_dominance_in_logit_space():
    config = {"score_markets":{"MEN_BO3":{"enabled":True,"offset":-0.2,"dominance":1.5}}}
    policy = score_policy("MEN", 3, config)
    a, b = apply_score_calibration(.66, .60, policy)
    assert a < .66 and b < .60
    assert abs((math.log(a/(1-a))-math.log(b/(1-b))) - 1.5*(math.log(.66/.34)-math.log(.60/.40))) < 1e-10
