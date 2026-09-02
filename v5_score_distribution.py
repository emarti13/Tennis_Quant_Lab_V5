from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Any
import math

import numpy as np
import pandas as pd

from v5_core import simulate_match
from v5_score_walkforward import predict_gaussian_score_model
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


def _normal_cdf(x: float, mean: float, sd: float) -> float:
    sd = max(float(sd), 1e-6)
    z = (float(x) - float(mean)) / (sd * math.sqrt(2.0))
    return float(0.5 * (1.0 + math.erf(z)))


def _spread_key(line) -> str:
    return f"{float(line):+.1f}"


def _total_key(line) -> str:
    return f"{float(line):.1f}"


def _conditioned_mechanistic(match_features: Mapping[str, Any], model_bundle: Mapping[str, Any]) -> tuple[dict, float, float, dict]:
    p1_serve = float(match_features["serve_probability_p1"]); p2_serve = float(match_features["serve_probability_p2"])
    target = float(match_features["winner_probability_p1"]); best_of = int(match_features.get("best_of", 3))
    simulations = int(model_bundle.get("simulations", 5000)); seed = int(model_bundle.get("seed", 42))
    search_sims = int(model_bundle.get("conditioning_simulations", max(600, min(1200, simulations // 4))))
    score_p1, score_p2, meta = condition_serve_pair_to_match_probability(
        p1_serve, p2_serve, target, best_of=best_of, n=search_sims, seed=seed + 17,
        max_iter=int(model_bundle.get("conditioning_max_iter", 8)),
    )
    result = simulate_match(
        score_p1, score_p2, best_of=best_of, n=simulations, seed=seed,
        formA=0.0, formB=0.0, volA=0.0, volB=0.0, state_variation=False,
        spread_lines=match_features.get("spread_lines"), total_lines=match_features.get("total_lines"), target_pA_win=target,
    )
    return result, float(score_p1), float(score_p2), meta


def predict_score_distribution(match_features: Mapping[str, Any], model_bundle: Mapping[str, Any]) -> ScoreDistribution:
    """Predict score markets after the independent winner probability is frozen.

    The mechanistic simulation always supplies score/set/tiebreak support. If chronological
    score validation promotes a contextual Gaussian margin/total model, only the margin/total
    distribution is replaced; the frozen winner probability is never changed by the score layer.
    """
    model_type = str(model_bundle.get("model_type", "conditioned_mechanistic"))
    if model_type not in {"conditioned_mechanistic", "gaussian_contextual", "gaussian_hybrid"}:
        raise ValueError(f"Unsupported score model_type: {model_type}")

    target = float(match_features["winner_probability_p1"])
    result, score_p1, score_p2, meta = _conditioned_mechanistic(match_features, model_bundle)
    expected_margin = float(result["expected_margin"]); expected_total = float(result["expected_total"])
    margin_sd = float(result["margin_sd"]); total_sd = float(result["total_sd"])
    spread = dict(result["spread"]); spread_push = dict(result["spread_push"])
    over = dict(result["over"]); total_push = dict(result["total_push"])

    if model_type in {"gaussian_contextual", "gaussian_hybrid"}:
        model = model_bundle.get("model") or {}
        features = dict(match_features.get("score_features") or model_bundle.get("score_features") or {})
        if model_type == "gaussian_hybrid":
            # The hybrid was trained with the conditioned mechanistic margin as one
            # additional tennis-only feature. Recreate that feature live from the
            # same frozen winner probability and serve environment before applying
            # the validated residual score geometry.
            features["mechanistic_margin_a"] = float(result["expected_margin"])
        if not model:
            raise ValueError("Contextual score model requires model")
        required = [str(name) for name in model.get("feature_names", [])]
        missing = [name for name in required if name not in features]
        if missing:
            raise ValueError("Contextual score model missing score_features: " + ", ".join(missing))
        pred = predict_gaussian_score_model(model, pd.DataFrame([features]))
        expected_margin = float(pred["margin_mean"][0]); margin_sd = float(pred["margin_sd"][0])
        expected_total = float(pred["total_mean"][0]); total_sd = float(pred["total_sd"][0])
        spread = {}
        spread_push = {}
        for line in match_features.get("spread_lines") or []:
            key = _spread_key(line)
            spread[key] = float(1.0 - _normal_cdf(-float(line), expected_margin, margin_sd))
            spread_push[key] = 0.0
        over = {}
        total_push = {}
        for line in match_features.get("total_lines") or []:
            key = _total_key(line)
            over[key] = float(1.0 - _normal_cdf(float(line), expected_total, total_sd))
            total_push[key] = 0.0

    return ScoreDistribution(
        model_type=model_type,
        match_win_probability_p1=target,
        raw_match_win_probability_p1=float(result["raw_pA_win"]),
        expected_margin=expected_margin,
        expected_total=expected_total,
        margin_sd=margin_sd,
        total_sd=total_sd,
        tiebreak_probability=float(result["tiebreak_prob"]),
        set_score_probabilities=dict(result["score_probs"]),
        spread_probability_p1=spread,
        spread_push_probability=spread_push,
        over_probability=over,
        total_push_probability=total_push,
        conditioned_serve_probability_p1=score_p1,
        conditioned_serve_probability_p2=score_p2,
        conditioning_metadata={k: float(v) for k, v in meta.items() if isinstance(v, (int, float))},
    )
