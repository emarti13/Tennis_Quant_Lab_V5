"""Known-answer tests for point_model (run: python -m pytest research_tests/inplay_charting -q)."""
import os
import random
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from point_model import Match, _game_from, _tb_from  # noqa: E402


def test_hold_known_value():
    # p = 0.6: classical result P(hold) = 0.7357
    assert _game_from(0, 0, 0.6) == pytest.approx(0.73565, abs=1e-4)


def test_symmetric_players_are_even():
    for rule in ("tb7", "tb10", "adv"):
        for bo in (3, 5):
            assert Match(0.63, 0.63, bo, rule).pre() == pytest.approx(0.5, abs=1e-12)


def test_tiebreak_symmetric_even():
    assert _tb_from(0, 0, True, 0.65, 0.65, 7) == pytest.approx(0.5, abs=1e-12)
    assert _tb_from(0, 0, False, 0.65, 0.65, 10) == pytest.approx(0.5, abs=1e-12)


def test_terminal_and_consistency():
    m = Match(0.66, 0.62, 3, "tb7")
    assert m.prob(2, 0, 0, 0, True) == 1.0 and m.prob(0, 2, 0, 0, True) == 0.0
    # point-level entry at 0-0 equals game-level state
    assert m.prob(1, 0, 3, 2, True, 0, 0) == pytest.approx(m._m(1, 0, 3, 2, True))
    # winning a point on serve raises A's chance
    assert m.prob(0, 0, 0, 0, True, 1, 0) > m.prob(0, 0, 0, 0, True, 0, 0) > m.prob(0, 0, 0, 0, True, 0, 1)


def _simulate(pa, pb, bo, rule, rng, start=None):
    """Plain Monte Carlo of the same rules, for an independent check."""
    need = bo // 2 + 1
    sa = sb = 0
    a_srv = rng.random() < 0.5 if start is None else start
    while sa < need and sb < need:
        final = sa == sb == need - 1
        set_rule = rule if final else "tb7"
        ga = gb = 0
        while True:
            if ga == gb == 6 and set_rule != "adv":
                target = 10 if set_rule == "tb10" else 7
                a = b = 0
                first = a_srv
                while not ((a >= target or b >= target) and abs(a - b) >= 2):
                    n = a + b
                    fs = n == 0 or ((n - 1) // 2) % 2 == 1
                    srv_a = fs == first
                    win = rng.random() < (pa if srv_a else 1 - pb)
                    a, b = (a + 1, b) if win else (a, b + 1)
                a_won = a > b
                a_srv = not a_srv
                ga, gb = (ga + 1, gb) if a_won else (ga, gb + 1)
                break
            p = pa if a_srv else pb
            i = j = 0
            while not ((i >= 4 or j >= 4) and abs(i - j) >= 2):
                if rng.random() < p:
                    i += 1
                else:
                    j += 1
            srv_won = i > j
            a_won = srv_won == a_srv
            ga, gb = (ga + 1, gb) if a_won else (ga, gb + 1)
            a_srv = not a_srv
            if (ga >= 6 or gb >= 6) and abs(ga - gb) >= 2:
                break
        if ga > gb:
            sa += 1
        else:
            sb += 1
    return sa == need


@pytest.mark.parametrize("bo,rule", [(3, "tb7"), (5, "adv"), (5, "tb10")])
def test_matches_monte_carlo(bo, rule):
    rng = random.Random(7)
    pa, pb = 0.67, 0.61
    n = 40000
    sim = sum(_simulate(pa, pb, bo, rule, rng) for _ in range(n)) / n
    exact = Match(pa, pb, bo, rule).pre()
    assert sim == pytest.approx(exact, abs=4 * (exact * (1 - exact) / n) ** 0.5)
