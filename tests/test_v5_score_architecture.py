import numpy as np

from v5_core import simulate_match


def test_simulation_exposes_set_count_and_games_per_set_decomposition():
    out = simulate_match(.66, .61, best_of=3, n=1200, seed=123, state_variation=False, spread_lines=[], total_lines=[])
    assert 2.0 <= out["expected_sets"] <= 3.0
    assert out["expected_games_per_set"] > 6.0
    assert np.isclose(out["expected_total"], out["expected_sets"] * out["expected_games_per_set"], rtol=.03)
    assert 0 <= out["straight_sets_probability"] <= 1


def test_bo5_simulation_has_three_to_five_expected_sets_and_scoreline_probabilities_sum_to_one():
    out = simulate_match(.67, .60, best_of=5, n=1500, seed=456, state_variation=False, spread_lines=[], total_lines=[])
    assert 3.0 <= out["expected_sets"] <= 5.0
    assert 0 <= out["deciding_set_probability"] <= 1
    assert abs(sum(out["score_probs"].values()) - 1.0) < 1e-9
