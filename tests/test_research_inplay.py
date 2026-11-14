"""The score-based fair price: known values, symmetry, and consistency between levels of the score."""
import pytest

from research_kit import inplay as ip


def test_game_known_values_and_deuce():
    assert ip.p_game(0.5) == pytest.approx(0.5)
    assert ip.p_game(0.6) == pytest.approx(0.7357, abs=1e-4)          # textbook value
    assert ip.p_game(0.65) == pytest.approx(0.8296, abs=1e-4)
    assert ip.p_game(0.6, 3, 3) == pytest.approx(0.36 / 0.52)         # deuce
    assert ip.p_game(0.6, 4, 3) == pytest.approx(0.6 + 0.4 * 0.36 / 0.52)
    assert ip.p_game(0.6, 4, 0) == 1.0 and ip.p_game(0.6, 0, 4) == 0.0


def test_symmetric_players_are_even_at_every_level():
    assert ip.p_tiebreak(0.62, 0.62, 0, 0, True) == pytest.approx(0.5)
    assert ip.p_match(0.62, 0.62) == pytest.approx(0.5)
    assert ip.p_match(0.62, 0.62, best_of=5, final_set_tb=10) == pytest.approx(0.5)


def test_swapping_players_gives_the_complement():
    a = ip.p_match(0.66, 0.60, sets=(1, 0), games=(2, 3), points=(1, 2), a_serves=True)
    b = ip.p_match(0.60, 0.66, sets=(0, 1), games=(3, 2), points=(2, 1), a_serves=False)
    assert a + b == pytest.approx(1.0, abs=1e-9)


def test_score_states_chain_consistently():
    pa, pb = 0.65, 0.61
    # the start of a game equals the average over who wins its first point
    s0 = ip.p_match(pa, pb, games=(2, 2), points=(0, 0), a_serves=True)
    s1 = pa * ip.p_match(pa, pb, games=(2, 2), points=(1, 0), a_serves=True) + (1 - pa) * ip.p_match(pa, pb, games=(2, 2), points=(0, 1), a_serves=True)
    assert s0 == pytest.approx(s1, abs=1e-12)
    # winning the last point of a game moves to the next game with the other server
    end = ip.p_match(pa, pb, games=(2, 2), points=(3, 0), a_serves=True)
    nxt_w = ip.p_match(pa, pb, games=(3, 2), points=(0, 0), a_serves=False)
    nxt_l = ip.p_match(pa, pb, games=(2, 2), points=(3, 1), a_serves=True)
    assert end == pytest.approx(pa * nxt_w + (1 - pa) * nxt_l, abs=1e-12)


def test_match_point_and_finished_match():
    assert ip.p_match(0.65, 0.6, sets=(2, 0)) == 1.0
    mp = ip.p_match(0.65, 0.6, sets=(1, 0), games=(5, 4), points=(3, 0), a_serves=True)
    assert 0.95 < mp < 1.0                                          # 40-0 serving for the match


def test_solver_reproduces_the_pre_match_price():
    for p_pre in (0.2, 0.5, 0.73, 0.89):
        pa, pb = ip.solve_serve(p_pre, 0.64)
        assert (pa + pb) / 2 == pytest.approx(0.64)
        assert ip.p_match(pa, pb) == pytest.approx(p_pre, abs=1e-5)
    with pytest.raises(ValueError):
        ip.solve_serve(1.0, 0.64)


def test_a_break_matters_more_when_serve_dominates():
    # same pre-match price (60%), A breaks for 3-1 in the first set: the swing is larger at a high serve level
    out = []
    for lvl in (0.58, 0.66):
        pa, pb = ip.solve_serve(0.60, lvl)
        out.append(ip.p_match(pa, pb, games=(3, 1), a_serves=True) - 0.60)
    assert out[1] > out[0] > 0


def test_serve_level_lookup():
    assert ip.serve_level("ATP", "hard", True) == 0.6553
    assert ip.serve_level("WTA", "Clay", False) == ip.WTA_LEVEL
    assert ip.serve_level("CH", None, None) == 0.6165
