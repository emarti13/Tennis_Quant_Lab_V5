from __future__ import annotations

import math


# Fitted only on 2025 chronological walk-forward tennis outcomes.
# 2026 was held out and used only to evaluate the fitted relationship.
CALIBRATION = {
    "MEN": {
        "version": "2025-outcome-sr-elo-v1",
        "fit_year": 2025,
        "validation_year": 2026,
        "inputs": ["serve_return", "surface_elo"],
        "coefficients": {
            "serve_return_logit_difference": 2.559868394630198,
            "surface_elo_logit": 0.703321947598873,
        },
        "validation_2026": {
            "n": 8545,
            "combined_brier": 0.22320858523654624,
            "combined_log_loss": 0.6365989409527228,
            "serve_return_brier": 0.2401237367217678,
            "serve_return_log_loss": 0.672886252878344,
            "raw_elo_brier": 0.2235760567998644,
            "raw_elo_log_loss": 0.637892332948673,
        },
    },
    "WTA": {
        "version": "2025-outcome-sr-elo-v1",
        "fit_year": 2025,
        "validation_year": 2026,
        "inputs": ["serve_return", "surface_elo"],
        "coefficients": {
            "serve_return_logit_difference": 1.847033800863458,
            "surface_elo_logit": 0.6476029651728824,
        },
        "validation_2026": {
            "n": 2012,
            "combined_brier": 0.21047305151045673,
            "combined_log_loss": 0.6071149085613129,
            "serve_return_brier": 0.21496582246788884,
            "serve_return_log_loss": 0.6170022822240407,
            "raw_elo_brier": 0.21274211651427805,
            "raw_elo_log_loss": 0.6125461048722258,
        },
    },
}


def _clip_probability(value: float) -> float:
    return min(max(float(value), 1e-6), 1.0 - 1e-6)


def _logit(value: float) -> float:
    p = _clip_probability(value)
    return math.log(p / (1.0 - p))


def _logistic(value: float) -> float:
    if value >= 0:
        z = math.exp(-value)
        return 1.0 / (1.0 + z)
    z = math.exp(value)
    return z / (1.0 + z)


def calibration_record(tour: str) -> dict:
    key = "WTA" if str(tour).upper() == "WTA" else "MEN"
    record = CALIBRATION[key]
    # Return a defensive copy so callers cannot mutate the production constants.
    return {
        **record,
        "inputs": list(record["inputs"]),
        "coefficients": dict(record["coefficients"]),
        "validation_2026": dict(record["validation_2026"]),
    }


def calibrated_match_probability(
    player1_serve_probability: float,
    player2_serve_probability: float,
    player1_surface_elo_probability: float,
    tour: str,
) -> float:
    """Independent pre-market P(player1 wins) from 2025 outcome calibration.

    Inputs are tennis-only features available before the match: the opponent-adjusted
    serve/return point probabilities and the surface-blended Elo probability. No
    bookmaker price, line, vig, or recommendation-side information enters here.
    """
    record = calibration_record(tour)
    coef = record["coefficients"]
    x_sr = _logit(player1_serve_probability) - _logit(player2_serve_probability)
    x_elo = _logit(player1_surface_elo_probability)
    linear = (
        coef["serve_return_logit_difference"] * x_sr
        + coef["surface_elo_logit"] * x_elo
    )
    return _logistic(linear)
