from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Any

from v5_core import simulate_match
from v5_strength_conditioning import condition_serve_pair_to_match_probability


@dataclass(frozen=True)
class ScoreDistribution:
    model_type: str
    match_win_probability_p1: float
    raw_match_win_probability_p1: float
    expected_margin: float
    expected_total: float
    margin_sd: float
    total_sd: float
    tiebreak_probability: float
    set_score_probabilities: dict[str, float]
    spread_probability_p1: dict[str, float]
    spread_push_probability: dict[str, float]
    over_probability: dict[str, float]
    total_push_probability: dict[str, float]
    conditioned_serve_probability_p1: float
    conditioned_serve_probability_p2: float
    conditioning_metadata: dict[str, float]


def predict_score_distribution(match_features: Mapping[str, Any], model_bundle: Mapping[str, Any]) -> ScoreDistribution:
    """Predict a score distribution independently of sportsbook prices/lines.

    The accepted implementation is a conditioned mechanistic simulator: winner strength is
    supplied by the already-frozen independent winner model, while the mean serve environment
    comes from tennis-only serve/return estimates. Requested spread/total lines are evaluation
    points only; they never alter the latent score distribution.
    """
    model_type = str(model_bundle.get("model_type", "conditioned_mechanistic"))
    if model_type != "conditioned_mechanistic":
        raise ValueError(f"Unsupported score model_type: {model_type}")

    p1_serve = float(match_features["serve_probability_p1"])
    p2_serve = float(match_features["serve_probability_p2"])
    target = float(match_features["winner_probability_p1"])
    best_of = int(match_features.get("best_of", 3))
    simulations = int(model_bundle.get("simulations", 5000))
    seed = int(model_bundle.get("seed", 42))
    search_sims = int(model_bundle.get("conditioning_simulations", max(600, min(1200, simulations // 4))))
    max_iter = int(model_bundle.get("conditioning_max_iter", 8))

    score_p1, score_p2, meta = condition_serve_pair_to_match_probability(
        p1_serve,
        p2_serve,
        target,
        best_of=best_of,
        n=search_sims,
        seed=seed + 17,
        max_iter=max_iter,
    )
    result = simulate_match(
        score_p1,
        score_p2,
        best_of=best_of,
        n=simulations,
        seed=seed,
        formA=0.0,
        formB=0.0,
        volA=0.0,
        volB=0.0,
        state_variation=False,
        spread_lines=match_features.get("spread_lines"),
        total_lines=match_features.get("total_lines"),
        target_pA_win=target,
    )
    return ScoreDistribution(
        model_type=model_type,
        match_win_probability_p1=float(result["pA_win"]),
        raw_match_win_probability_p1=float(result["raw_pA_win"]),
        expected_margin=float(result["expected_margin"]),
        expected_total=float(result["expected_total"]),
        margin_sd=float(result["margin_sd"]),
        total_sd=float(result["total_sd"]),
        tiebreak_probability=float(result["tiebreak_prob"]),
        set_score_probabilities=dict(result["score_probs"]),
        spread_probability_p1=dict(result["spread"]),
        spread_push_probability=dict(result["spread_push"]),
        over_probability=dict(result["over"]),
        total_push_probability=dict(result["total_push"]),
        conditioned_serve_probability_p1=float(score_p1),
        conditioned_serve_probability_p2=float(score_p2),
        conditioning_metadata={k: float(v) for k, v in meta.items() if isinstance(v, (int, float))},
    )
