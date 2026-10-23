"""Known-answer tests for run_intrans: Hodge split on hand-built graphs, and the visibility rule
(a match never sees its own event or an event not yet finished).
Run: python -m pytest research_tests/intransitivity -q"""
import math
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_intrans as ri  # noqa: E402


def _store(results, t=10.0):
    """results: list of (winner, loser, games share of winner), all on hard, tier weight 1."""
    st = ri.Store()
    for w, l, g in results:
        st.add(w, l, g, t, 0, 1.0)
    return st


def _logit(p):
    return math.log(p / (1 - p))


def test_two_players_only():
    st = _store([("A", "B", 0.6)])
    istar, ev = ri.intransitivity(st, "A", "B", 0, 10.0)
    a = abs(_logit(0.6))
    assert math.isclose(istar / ev, 1 / (1 + a), rel_tol=1e-9)      # no cycle possible: cyclic part 0


def test_transitive_triangle_has_no_cyclic_part():
    # logits consistent with potentials 2, 1, 0: A-B 1, B-C 1, A-C 2
    p = lambda x: 1 / (1 + math.exp(-x))
    st = _store([("A", "B", p(1)), ("B", "C", p(1)), ("A", "C", p(2))])
    istar, ev = ri.intransitivity(st, "A", "B", 0, 10.0)
    grad = math.sqrt(1 + 1 + 4)
    assert math.isclose(istar / ev, 1 / (1 + grad), rel_tol=1e-6)


def test_pure_cycle_has_no_transitive_part():
    st = _store([("A", "B", 0.7), ("B", "C", 0.7), ("C", "A", 0.7)])
    istar, ev = ri.intransitivity(st, "A", "B", 0, 10.0)
    cyc = math.sqrt(3) * _logit(0.7)
    assert math.isclose(istar / ev, 1 + cyc, rel_tol=1e-6)
    st2 = _store([("A", "B", 0.7), ("B", "C", 0.7), ("A", "C", 0.7)])   # same strengths, transitive
    i2, ev2 = ri.intransitivity(st2, "A", "B", 0, 10.0)
    assert istar / ev > 2 * (i2 / ev2)


def test_no_direct_history_gives_zero():
    st = _store([("A", "C", 0.6), ("B", "C", 0.6)])
    assert ri.intransitivity(st, "A", "B", 0, 10.0) == (0.0, 0.0)


def test_visibility_rule():
    # E1 finishes week 2 (done_week 2); E2 starts week 3 and sees E1; E3 starts week 2 and must not see E1.
    ev = pd.DataFrame({"first_week": [1, 3, 2], "done_week": [2, 4, 3]},
                      index=pd.MultiIndex.from_tuples([("M", "E1"), ("M", "E2"), ("M", "E3")], names=["tour", "tid"]))
    rows = [("E1", "k1", "A", "B"), ("E2", "k2", "A", "B"), ("E3", "k3", "A", "B"), ("E2", "k4", "A", "B")]
    m = pd.DataFrame([{"tour": "M", "tid": e, "key": k, "winner_key": w, "loser_key": l, "g": 0.6, "t": 10.0,
                       "s": 0, "beta": 1.0} for e, k, w, l in rows])
    out = ri.compute_istar(m, ev, {"k1", "k2", "k3", "k4"})
    assert out["k1"] == (0.0, 0.0)          # nothing earlier
    assert out["k3"] == (0.0, 0.0)          # E1 not finished when E3 starts
    assert out["k2"][0] > 0                 # E1 visible
    assert out["k2"] == out["k4"]           # E2's own matches never feed each other
