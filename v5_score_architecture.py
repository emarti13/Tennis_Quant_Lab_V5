from __future__ import annotations

import math
import re


def _scoreline_sets(key: str) -> int | None:
    match = re.fullmatch(r"\s*(\d+)\s*-\s*(\d+)\s*", str(key or ""))
    if not match:
        return None
    return int(match.group(1)) + int(match.group(2))


def score_decomposition(simulation: dict) -> dict[str, float | None]:
    """Decompose a simulated match distribution into sets-played and games/set components."""
    score_probs = simulation.get("score_probs") or {}
    rows = []
    for key, prob in score_probs.items():
        sets = _scoreline_sets(key)
        try:
            p = float(prob)
        except Exception:
            continue
        if sets is not None and math.isfinite(p) and p >= 0:
            rows.append((sets, p))
    total_weight = sum(p for _, p in rows)
    if total_weight <= 0:
        return {
            "expected_sets": None,
            "expected_games_per_set": None,
            "straight_sets_probability": None,
            "deciding_set_probability": None,
        }
    expected_sets = sum(sets * p for sets, p in rows) / total_weight
    min_sets = min(sets for sets, _ in rows)
    max_sets = max(sets for sets, _ in rows)
    straight = sum(p for sets, p in rows if sets == min_sets) / total_weight
    deciding = sum(p for sets, p in rows if sets == max_sets) / total_weight
    total = simulation.get("expected_total")
    try:
        expected_total = float(total)
    except Exception:
        expected_total = float("nan")
    games_per_set = expected_total / expected_sets if math.isfinite(expected_total) and expected_sets > 0 else None
    return {
        "expected_sets": float(expected_sets),
        "expected_games_per_set": None if games_per_set is None else float(games_per_set),
        "straight_sets_probability": float(straight),
        "deciding_set_probability": float(deciding),
    }
