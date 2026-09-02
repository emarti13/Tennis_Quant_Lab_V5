from __future__ import annotations

import json
import math
from pathlib import Path


def _logit(p):
    p = min(max(float(p), 1e-8), 1.0 - 1e-8)
    return math.log(p / (1.0 - p))


def _logistic(x):
    return 1.0 / (1.0 + math.exp(-float(x)))


def load_production_config(path: str | Path = "v5_production_config.json") -> dict:
    p = Path(path)
    if not p.exists():
        return {"winner_models":{"MEN":{"production_model":"accepted_baseline"},"WTA":{"production_model":"accepted_baseline"}},"score_markets":{}}
    return json.loads(p.read_text(encoding="utf-8"))


def score_segment(tour: str, best_of: int) -> str:
    normalized = "WTA" if str(tour).upper() == "WTA" else "MEN"
    return "WTA_BO3" if normalized == "WTA" else ("MEN_BO5" if int(best_of) == 5 else "MEN_BO3")


def score_policy(tour: str, best_of: int, config: dict) -> dict:
    segment = score_segment(tour, best_of)
    raw = (config.get("score_markets") or {}).get(segment, {})
    selected = raw.get("selected_parameters") or {}
    return {
        "segment": segment,
        "enabled": bool(raw.get("enabled", False)),
        "offset": float(raw.get("offset", selected.get("offset", 0.0)) or 0.0),
        "dominance": float(raw.get("dominance", selected.get("dominance", selected.get("dominance_multiplier", 1.0))) or 1.0),
    }


def apply_score_calibration(p1: float, p2: float, policy: dict) -> tuple[float, float]:
    if not policy.get("enabled", False):
        return float(p1), float(p2)
    e1, e2 = _logit(p1), _logit(p2)
    mean = (e1 + e2) / 2.0 + float(policy.get("offset", 0.0))
    diff = (e1 - e2) * float(policy.get("dominance", 1.0))
    return _logistic(mean + diff / 2.0), _logistic(mean - diff / 2.0)


def enforce_market_policy(signal: str, market_group: str, tour: str, best_of: int, config: dict) -> str:
    if str(market_group) not in {"game_spread", "total_games"}:
        return str(signal)
    if score_policy(tour, best_of, config)["enabled"]:
        return str(signal)
    return "REVIEW" if str(signal) in {"BET", "LEAN"} else str(signal)
