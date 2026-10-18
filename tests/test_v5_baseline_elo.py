"""Leak-free Elo: ordering rules, walkovers, fail-closed lookups, and history/live parity."""
from __future__ import annotations

import pandas as pd
import pytest

import v5_baseline_elo as be

ROUND = {"Q1": (0, 0.0), "Q2": (0, 1.0), "R32": (1, 12.0), "R16": (1, 13.0), "QF": (1, 14.0), "F": (1, 16.0), "?": (1, float("nan"))}


def mk(rows):
    out = []
    for i, (tid, date, rnd, w, l, *rest) in enumerate(rows):
        stage, rank = ROUND[rnd]
        out.append({"tour": "MEN", "tid": tid, "tourney_name": tid, "level": "A", "date": pd.Timestamp(date),
                    "stage": stage, "rank": rank, "round": rnd, "winner_key": w, "loser_key": l,
                    "surface": "Hard", "walkover": bool(rest and rest[0] == "wo"), "key": f"{tid}-{i:03d}"})
    return pd.DataFrame(out)


def preds(rows, **kw):
    return be.run(mk(rows), be.EloParams(**kw)).set_index("key")["p_winner"].to_dict()


def test_later_rounds_never_change_earlier_prices():
    a = [("e1", "2026-03-02", "R32", "A", "B"), ("e1", "2026-03-02", "R16", "A", "C"), ("e1", "2026-03-02", "F", "A", "D")]
    b = [a[0], a[1], ("e1", "2026-03-02", "F", "D", "A")]          # the final's result flipped
    pa, pb = preds(a), preds(b)
    assert pa["e1-000"] == pb["e1-000"] and pa["e1-001"] == pb["e1-001"]


def test_same_round_is_concurrent():
    a = [("e1", "2026-03-02", "R32", "A", "B"), ("e1", "2026-03-02", "R32", "C", "D"), ("e1", "2026-03-02", "R16", "A", "C")]
    b = [("e1", "2026-03-02", "R32", "C", "D"), ("e1", "2026-03-02", "R32", "A", "B"), a[2]]   # file order swapped
    pa = be.run(mk(a)).set_index(["winner_key", "loser_key"])["p_winner"]
    pb = be.run(mk(b)).set_index(["winner_key", "loser_key"])["p_winner"]
    assert pa[("A", "B")] == 0.5 and pa[("C", "D")] == 0.5        # neither saw the other
    assert pa.sort_index().equals(pb.sort_index())                # row order does not matter
    assert pa[("A", "C")] == 0.5                                   # both won one: still level


def test_an_event_in_the_same_week_is_not_seen_but_the_next_week_is():
    rows = [("e1", "2026-03-02", "R32", "A", "B"),
            ("e2", "2026-03-02", "R32", "A", "C"),                 # same week, other event
            ("e3", "2026-03-09", "R32", "A", "D")]                 # next week
    p = preds(rows)
    assert p["e2-001"] == 0.5 and p["e3-002"] > 0.5


def test_walkovers_are_not_priced_and_move_nothing():
    p = preds([("e1", "2026-03-02", "R32", "A", "B", "wo"), ("e2", "2026-03-09", "R32", "A", "B")])
    assert "e1-000" not in p and p["e2-001"] == 0.5


def test_unknown_round_sees_only_the_event_start_and_informs_nothing_in_it():
    p = preds([("e1", "2026-03-02", "R32", "A", "B"), ("e1", "2026-03-02", "?", "A", "C"),
               ("e1", "2026-03-02", "R16", "C", "D")])
    assert p["e1-001"] == 0.5 and p["e1-002"] == 0.5
    later = preds([("e1", "2026-03-02", "?", "A", "C"), ("e2", "2026-03-09", "R32", "A", "C")])
    assert later["e2-001"] > 0.5                                    # it counts once the event is over


def test_live_state_prices_a_fixture_exactly_as_the_history_did():
    rows = [("e0", "2026-02-23", "R32", "A", "B"), ("e0", "2026-02-23", "F", "B", "C"),
            ("e1", "2026-03-02", "Q1", "C", "D"), ("e1", "2026-03-02", "Q2", "C", "E"),
            ("e1", "2026-03-02", "R32", "C", "A"), ("e1", "2026-03-02", "R16", "A", "B")]
    m = mk(rows)
    params = be.EloParams(k=1.3, blend=0.6, newcomer=1450)
    hist = be.run(m, params).set_index("key")
    for key in ("e1-004", "e1-005"):                               # both players rated before
        r = m.set_index("key").loc[key]
        state = be.rating_state(m, ("MEN", "e1"), r["stage"], r["rank"], params)
        live = be.fixture_probability(state, r["winner_key"], r["loser_key"], "Hard", params)
        assert live["p"] == pytest.approx(hist.loc[key, "p_winner"], abs=1e-12)
    # a first match is priced at the newcomer rating in the history, but refused live
    state = be.rating_state(m, ("MEN", "e1"), 0, 0.0, params)
    with pytest.raises(KeyError):
        be.fixture_probability(state, "C", "D", "Hard", params)


def test_an_unknown_player_raises():
    m = mk([("e1", "2026-03-02", "R32", "A", "B"), ("e1", "2026-03-02", "R16", "A", "C")])
    state = be.rating_state(m, ("MEN", "e1"), 1, 13.0)
    with pytest.raises(KeyError):
        be.fixture_probability(state, "A", "nobody", "Hard")


def test_players_are_keyed_by_registry_id_else_by_tennismylife_id(tmp_path):
    reg = tmp_path / be.REGISTRY_TML
    reg.parent.mkdir(parents=True)
    pd.DataFrame([{"tour": "M", "tml_id": "N409", "player_id": "M-000018", "status": "auto"},
                  {"tour": "M", "tml_id": "X1", "player_id": "M-000099", "status": "review"}]).to_csv(reg, index=False)
    m = pd.DataFrame([{"tour": "MEN", "winner_id": "N409", "loser_id": "X1"}])
    got = be.player_keys(m, tmp_path)
    assert got.loc[0, "winner_key"] == "M-000018" and got.loc[0, "loser_key"] == "tml:M:X1"


def test_surface_defaults_to_hard_for_carpet_and_unknown():
    assert be.surface_of("Clay") == "Clay" and be.surface_of("Carpet") == "Hard" and be.surface_of(None) == "Hard"


def test_live_elo_prices_the_next_round_and_a_new_event_as_the_history_does():
    from v5_fatigue_features import tennis_week
    rows = [("e0", "2026-02-23", "R32", "A", "B"), ("e0", "2026-02-23", "F", "B", "C"),
            ("e1", "2026-03-02", "R32", "A", "C"), ("e1", "2026-03-02", "R32", "B", "D"),
            ("e1", "2026-03-02", "F", "A", "B"),
            ("e2", "2026-03-09", "R32", "C", "A")]
    params = be.EloParams(k=0.8, blend=0.3)
    full = be.run(mk(rows), params).set_index("key")["p_winner"]
    # the final of e1 not played yet
    live = be.run(mk(rows[:4]), params, live=True)
    got = be.fixture_probability(live.state(("MEN", "e1")), "A", "B", "Hard", params)
    assert got["p"] == pytest.approx(full["e1-004"], abs=1e-12)
    # e2 not started yet: everything before its week counts
    live = be.run(mk(rows[:5]), params, live=True)
    got = be.fixture_probability(live.state(("MEN", "e2"), week=tennis_week("2026-03-09")), "C", "A", "Hard", params)
    assert got["p"] == pytest.approx(full["e2-005"], abs=1e-12)
    with pytest.raises(ValueError):
        live.state(("MEN", "e2"))                                   # no results and no week: refuse
