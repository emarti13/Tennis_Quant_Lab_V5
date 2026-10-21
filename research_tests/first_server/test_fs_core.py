"""Checks for fs_core: inference against point-by-point simulation, the exact model against the
paper's identities and against simulation. Run: python -m pytest research_tests/first_server -q"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fs_core as f  # noqa: E402


def _sim_match(rng, pa, pb, best_of=3, a_first=True, final_rule="tb7"):
    """Point-by-point match; returns (sets from A's side, SG A, SG B, A won)."""
    need = (best_of + 1) // 2
    sets, sg = [], {"A": 0, "B": 0}
    server = "A" if a_first else "B"
    sa = sb = 0
    while sa < need and sb < need:
        final = sa == need - 1 and sb == need - 1
        rule = final_rule if final else "tb7"
        tb_at = {"tb7": 6, "tb10": 6, "tb7@12": 12, "adv": None}[rule]
        ga = gb = 0
        tb = False
        while True:
            if tb_at is not None and ga == tb_at and gb == tb_at:
                target = 10 if rule == "tb10" else 7
                x = y = 0
                k = 0
                first = server
                while True:
                    srv = first if ((k + 1) // 2) % 2 == 0 else ("B" if first == "A" else "A")
                    p = pa if srv == "A" else 1 - pb
                    if rng.random() < p:
                        x += 1
                    else:
                        y += 1
                    k += 1
                    if (x >= target or y >= target) and abs(x - y) >= 2:
                        break
                if x > y:
                    ga += 1
                else:
                    gb += 1
                tb = True
                server = "B" if first == "A" else "A"
                break
            p = pa if server == "A" else pb
            sg[server] += 1
            x = y = 0
            while not ((x >= 4 or y >= 4) and abs(x - y) >= 2):
                if rng.random() < p:
                    x += 1
                else:
                    y += 1
            srv_won = x > y
            if (server == "A") == srv_won:
                ga += 1
            else:
                gb += 1
            server = "B" if server == "A" else "A"
            if (ga >= 6 or gb >= 6) and abs(ga - gb) >= 2:
                break
        sets.append((ga, gb, tb))
        sa += ga > gb
        sb += gb > ga
    return sets, sg["A"], sg["B"], sa == need


def test_inference_matches_simulation():
    rng = np.random.default_rng(1)
    det = right = 0
    for i in range(3000):
        a_first = bool(i % 2)
        sets, sga, sgb, a_won = _sim_match(rng, 0.66, 0.60, 3, a_first)
        w_sets = sets if a_won else [(b, a, t) for a, b, t in sets]
        w_sv, l_sv = (sga, sgb) if a_won else (sgb, sga)
        who, how = f.infer_first_server(w_sets, w_sv, l_sv)
        assert how in ("svgms", "indeterminate")
        if who is not None:
            det += 1
            truth = "W" if (a_first == a_won) else "L"
            right += who == truth
    assert det > 0 and right == det


def test_parse_sets():
    assert f.parse_sets("7-6(5) 6-2", 3) == [(7, 6, True), (6, 2, False)]
    assert f.parse_sets("6-4 3-6 7-6(10-8)", 3) == [(6, 4, False), (3, 6, False), (7, 6, True)]
    assert f.parse_sets("6-4 RET", 3) is None
    assert f.parse_sets("6-4 6-4", 5) is None
    assert f.parse_sets("6-4 4-6 12-10", 3) == [(6, 4, False), (4, 6, False), (12, 10, False)]
    assert f.parse_sets("6-5 6-4", 3) is None


def test_implied_service_games_tiebreaks():
    # 7-6 6-2: 21 slots, one tiebreak; data says 10/10 service games
    assert f.implied_service_games([(7, 6, True), (6, 2, False)], True) == (10, 10)
    assert f.implied_service_games([(7, 6, True), (6, 2, False)], False) == (10, 10)


def test_model_identities():
    pa, pb = np.array([0.70, 0.64, 0.58]), np.array([0.60, 0.62, 0.55])
    A, B = f.match_dist(pa, pb, 3, "tb7", True), f.match_dist(pa, pb, 3, "tb7", False)
    assert np.allclose(A["pwin"], B["pwin"])                       # Newton-Keller: win prob independent of server
    assert np.all(f.expect_T(A) < f.expect_T(B))                   # Prop 3.2: stronger first -> fewer games
    assert np.all(f.expect_H(A) > f.expect_H(B))                   # Prop 3.3
    assert np.allclose(A["T_det"].sum(1) + A["T_ind"].sum(1), 1)
    for rule in ("tb10", "adv", "tb7@12"):
        d = f.match_dist(pa, pb, 5, rule, True)
        assert d["lost"].max() < 1e-4                         # advantage sets capped at 30 games


def test_model_matches_simulation():
    rng = np.random.default_rng(7)
    n = 6000
    T, det = [], []
    for _ in range(n):
        sets, sga, sgb, a_won = _sim_match(rng, 0.68, 0.61, 3, True)
        T.append(sum(a + b for a, b, _ in sets))
        det.append(f.implied_service_games(sets, True) != f.implied_service_games(sets, False))
    d = f.match_dist([0.68], [0.61], 3, "tb7", True)
    assert abs(np.mean(T) - f.expect_T(d)[0]) < 0.15
    assert abs(np.mean(det) - d["T_det"].sum()) < 0.02


def test_path_likelihood_sums_to_one():
    pa, pb = np.array([0.66]), np.array([0.6])
    tot = 0.0
    so = {af: f.set_outcomes(pa, pb, af) for af in (True, False)}
    keys = list(so[True].keys())
    for k1 in keys:
        for k2 in keys:
            seqs = [[k1, k2]] if (k1[0] > k1[1]) == (k2[0] > k2[1]) else [[k1, k2, k3] for k3 in keys]
            for s in seqs:
                tot += f.path_likelihood(pa, pb, [s], 3, "tb7", True)[0]
    assert abs(tot - 1) < 1e-9
