import numpy as np

from v5_core import simulate_match
from v5_score_architecture import score_decomposition


def test_simulation_score_probs_decompose_set_count_and_games_per_set():
    out = simulate_match(.66, .61, best_of=3, n=1200, seed=123, state_variation=False, spread_lines=[], total_lines=[])
    d = score_decomposition(out)
    assert 2.0 <= d["expected_sets"] <= 3.0
    assert d["expected_games_per_set"] > 6.0
    assert np.isclose(out["expected_total"], d["expected_sets"] * d["expected_games_per_set"], rtol=.03)
    assert 0 <= d["straight_sets_probability"] <= 1


def test_bo5_decomposition_has_three_to_five_expected_sets_and_valid_decider_probability():
    out = simulate_match(.67, .60, best_of=5, n=1500, seed=456, state_variation=False, spread_lines=[], total_lines=[])
    d = score_decomposition(out)
    assert 3.0 <= d["expected_sets"] <= 5.0
    assert 0 <= d["deciding_set_probability"] <= 1
    assert abs(sum(out["score_probs"].values()) - 1.0) < 1e-9
