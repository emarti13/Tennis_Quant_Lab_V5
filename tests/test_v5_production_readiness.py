from v5_production_readiness import build_readiness


def test_readiness_keeps_baseline_when_advanced_candidate_does_not_pass_and_requires_score_gates():
    context = {"tours":{"MEN":{"status":"evaluated"},"WTA":{"status":"evaluated"}}}
    advanced = {"production_gate":{
        "MEN":{"selected_candidate":"accepted_baseline","candidate_beats_baseline":False,"metrics":{"brier":.22}},
        "WTA":{"selected_candidate":"ensemble","candidate_beats_baseline":True,"metrics":{"brier":.20}},
    }}
    score = {"segments":{
        "MEN_BO3":{"production_gate":{"accepted":True}},
        "MEN_BO5":{"production_gate":{"accepted":False}},
        "WTA_BO3":{"production_gate":{"accepted":True}},
    }}
    out = build_readiness(context, advanced, score)
    assert out["winner_models"]["MEN"]["production_model"] == "accepted_baseline"
    assert out["winner_models"]["WTA"]["production_model"] == "ensemble"
    assert out["score_markets"]["MEN_BO5"]["enabled"] is False
    assert out["ready_for_main"] is True
    assert out["full_score_market_promotion"] is False


def test_readiness_rejects_main_when_winner_validation_missing():
    context = {"tours":{"MEN":{"status":"insufficient_rows"},"WTA":{"status":"evaluated"}}}
    advanced = {"production_gate":{}}
    score = {"segments":{}}
    out = build_readiness(context, advanced, score)
    assert out["ready_for_main"] is False
