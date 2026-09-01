from __future__ import annotations

from v5_core import logistic, logit, simulate_match


def condition_serve_pair_to_match_probability(
    p1_serve: float,
    p2_serve: float,
    target_p1_win: float,
    *,
    best_of: int = 3,
    n: int = 1000,
    seed: int = 41,
    max_iter: int = 8,
    max_abs_logit_difference: float = 3.0,
):
    """Adjust relative serve strength so score simulation reflects calibrated match strength.

    The mean of the two serve logits is held fixed. Only the difference between
    players is changed. This therefore changes matchup dominance/margins without
    using a sportsbook line or arbitrarily changing the overall hold environment.
    """
    target = min(max(float(target_p1_win), 1e-5), 1.0 - 1e-5)
    e1 = logit(p1_serve); e2 = logit(p2_serve)
    mean_logit = (e1 + e2) / 2.0
    original_diff = e1 - e2

    def evaluate(diff):
        a = logistic(mean_logit + diff / 2.0)
        b = logistic(mean_logit - diff / 2.0)
        result = simulate_match(
            a, b, best_of=best_of, n=int(n), seed=int(seed),
            state_variation=False, spread_lines=[], total_lines=[],
        )
        return a, b, float(result["raw_pA_win"])

    low = -abs(float(max_abs_logit_difference))
    high = abs(float(max_abs_logit_difference))
    candidates = []
    for boundary in (low, high, original_diff):
        a, b, p = evaluate(boundary)
        candidates.append((abs(p - target), boundary, a, b, p))

    for _ in range(int(max_iter)):
        mid = (low + high) / 2.0
        a, b, p = evaluate(mid)
        candidates.append((abs(p - target), mid, a, b, p))
        if p < target:
            low = mid
        else:
            high = mid

    _, diff, a, b, achieved = min(candidates, key=lambda item: item[0])
    return a, b, {
        "target_probability": target,
        "achieved_probability": achieved,
        "original_logit_difference": original_diff,
        "adjusted_logit_difference": diff,
        "mean_serve_logit": mean_logit,
        "search_simulations": int(n),
        "search_iterations": int(max_iter),
    }
