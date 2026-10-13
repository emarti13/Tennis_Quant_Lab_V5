"""Player identity (spec 2026-10-13): players from TennisMyLife, OddsPapi links from results."""
from __future__ import annotations

import pandas as pd

from v5_player_registry import (
    build_players,
    is_placeholder_participant,
    link_oddspapi,
    normalize_tml_id,
    player_key,
    resolve_oddspapi_player,
)


def _m(tour, tid, date, rnd, w, wid, wc, l, lid, lc, wb=None, lb=None):
    """wb / lb: birth year estimated from TennisMyLife's recorded age (None = unusable age)."""
    return {"tour": tour, "tourney_id": tid, "date": pd.Timestamp(date), "round": rnd,
            "winner_id": normalize_tml_id(wid), "winner_name": w, "winner_key": player_key(w), "winner_ioc": wc,
            "winner_birth": wb,
            "loser_id": normalize_tml_id(lid), "loser_name": l, "loser_key": player_key(l), "loser_ioc": lc,
            "loser_birth": lb}


def _pid(alias, tour, tml_id):
    return alias.set_index(["tour", "tml_id"]).loc[(tour, tml_id), "player_id"]


def test_different_tennismylife_ids_stay_apart_unless_the_evidence_joins_them():
    m = pd.DataFrame([
        # Second WTA id scheme (2026): same name and country, the new id has no usable age
        # and its matches lie inside the old id's career -> one player.
        _m("W", "t1", "2025-03-03", "R32", "Ajla Tomljanovic", "201548.0", "AUS", "A B", "1", "USA", wb=1993.35),
        _m("W", "t2", "2026-06-08", "R32", "Ajla Tomljanovic", "315232", "AUS", "C D", "2", "USA"),
        _m("W", "t3", "2026-08-03", "R32", "Ajla Tomljanovic", "201548", "AUS", "E F", "3", "USA", wb=1993.35),
        # Same name and country, years apart, born 1988 and 1994 -> two people.
        _m("M", "t4", "2013-04-08", "R32", "David Warren", "W654", "USA", "G H", "4", "USA", wb=1988.56),
        _m("M", "t5", "2016-04-04", "R32", "David Warren", "W933", "USA", "I J", "5", "USA", wb=1994.45),
        # Same name and birth date, a year apart -> one person.
        _m("M", "t6", "2022-06-27", "R32", "Hernandez Aguila Abel", "A0JF", "ESP", "K L", "6", "USA", wb=1989.66),
        _m("M", "t7", "2023-07-09", "R32", "Abel Hernandez-Aguila", "H811", "ESP", "M N", "7", "USA", wb=1989.66),
        # Same name and birth date but different countries: a person decides.
        _m("M", "t8", "2010-03-05", "R32", "Harshana Godamanna", "104631", "SRI", "O P", "8", "USA", wb=1987.95),
        _m("M", "t9", "2012-04-06", "R32", "Harshana Godamanna", "G793", "ECU", "Q R", "9", "USA", wb=1987.95),
        # Same name and country, no usable age, careers apart: a person decides.
        _m("M", "u1", "2011-04-25", "R32", "Diogo Rocha", "R630", "POR", "S T", "10", "USA"),
        _m("M", "u2", "2012-04-30", "R32", "Diogo Rocha", "RD02", "PRT", "U V", "11", "USA"),
    ])
    players, alias, review = build_players(m, set_on="2026-10-13")
    assert _pid(alias, "W", "201548") == _pid(alias, "W", "315232")
    assert _pid(alias, "M", "W654") != _pid(alias, "M", "W933")
    assert _pid(alias, "M", "A0JF") == _pid(alias, "M", "H811")
    assert _pid(alias, "M", "104631") != _pid(alias, "M", "G793")
    assert _pid(alias, "M", "R630") != _pid(alias, "M", "RD02")
    to_decide = " ".join(review[review["kind"] == "tennismylife_ids"]["reason"])
    assert "different country" in to_decide and "same birth date" in to_decide
    assert "careers more than 90 days apart" in to_decide             # POR and PRT count as one country
    assert "born 1989 and 1994" not in to_decide                      # proven different people are not a question
    assert "born 1989 and 1994" in " ".join(review[review["kind"] == "kept_apart"]["reason"])


def test_a_weekend_start_belongs_to_the_next_week():
    # Same player, events dated Monday June 15 and Sunday June 21: consecutive weeks.
    m = pd.DataFrame([
        _m("W", "t1", "2026-06-15", "R32", "Elina Svitolina", "202494", "UKR", "A B", "1", "USA", wb=1994.7),
        _m("W", "t9", "2025-06-15", "R32", "Elina Svitolina", "202494", "UKR", "A C", "1", "USA", wb=1994.7),
        _m("W", "t2", "2026-06-21", "R16", "Elina Svitolina", None, "UKR", "C D", "2", "USA"),
    ])
    _, alias, review = build_players(m, set_on="2026-10-13")
    assert _pid(alias, "W", "202494") == _pid(alias, "W", "name:elina svitolina")


def test_rows_filed_under_another_players_name_are_flagged():
    m = pd.DataFrame([
        _m("M", "t1", "2019-01-07", "R32", "John Millman", "MH30", "AUS", "A B", "1", "USA", wb=1989.45),
        _m("M", "t2", "2020-11-09", "R32", "Marc-Andrea Huesler", "MH30", "AUS", "C D", "2", "USA", wb=1989.45),
        _m("M", "t3", "2019-01-07", "R32", "John Millman", "MH30", "AUS", "E F", "3", "USA", wb=1989.45),
        _m("M", "t4", "2021-01-04", "R32", "Marc-Andrea Huesler", "HH06", "SUI", "G H", "4", "USA", wb=1996.48),
    ])
    _, alias, review = build_players(m, set_on="2026-10-13")
    assert _pid(alias, "M", "MH30") != _pid(alias, "M", "HH06")
    assert any("under another name" in r for r in review["reason"])


def test_player_ids_are_stable_and_user_rows_win():
    m = pd.DataFrame([_m("M", "t1", "2024-01-01", "R32", "Alex de Minaur", "DH58", "AUS", "X Y", "X1", "USA")])
    _, alias, _ = build_players(m, set_on="2026-10-13")
    stored = alias.copy()
    stored.loc[stored["tml_id"] == "DH58", "player_id"] = "M-000777"
    stored.loc[stored["tml_id"] == "DH58", "status"] = "user"
    m2 = pd.concat([m, pd.DataFrame([_m("M", "t2", "2024-02-05", "R32", "Alex De Minaur", "DH58", "AUS", "Z W", "Z1", "USA")])])
    _, alias2, _ = build_players(m2, existing_alias=stored, set_on="2026-10-14")
    assert _pid(alias2, "M", "DH58") == "M-000777"
    assert _pid(alias2, "M", "X1") == _pid(alias, "M", "X1")   # untouched ids keep their player id


def _world():
    """One Challenger edition: OddsPapi spells two players differently from TennisMyLife."""
    m = pd.DataFrame([
        _m("M", "2026-9", "2026-03-02", "R32", "Pietro Fellin", "F1", "ITA", "Tai Sach", "S1", "AUS"),
        _m("M", "2026-9", "2026-03-02", "R16", "Pietro Fellin", "F1", "ITA", "Maria Lourdes Carle", "C1", "ARG"),
        _m("M", "2026-9", "2026-03-02", "QF", "Old Hand", "O1", "ESP", "Pietro Fellin", "F1", "ITA"),
        _m("M", "2025-1", "2025-03-03", "R32", "Joao Silva", "J1", "POR", "Other Guy", "G1", "POR"),
    ])
    players, alias_tml, _ = build_players(m, set_on="2026-10-13")
    xt = pd.DataFrame([{"tournament_id": "2026-9", "first_date": "2026-03-02", "last_date": "2026-03-02",
                        "edition_key": "E1", "status": "confirmed"}])
    xo = pd.DataFrame([{"tournament_id": "77", "first_date": "2026-03-01", "last_date": "2026-03-06",
                        "edition_key": "E1", "status": "confirmed"}])

    def fx(fid, day, a_id, a, b_id, b):
        return {"fixture_id": fid, "start_time_utc": f"2026-03-0{day}T10:00:00Z", "tournament_id": 77,
                "tournament_name": "ATP Challenger Test Men Singles", "category_name": "Challenger",
                "participant1_id": a_id, "participant1_name": a, "participant2_id": b_id, "participant2_name": b}
    f = pd.DataFrame([
        fx("f1", 2, 101, "Fellin, Pietro Orlando", 102, "Sach, Tai Leonard"),
        fx("f2", 3, 101, "Fellin, Pietro Orlando", 103, "Carle, Maria Lourdes"),
        fx("f3", 4, 104, "Hand, Old", 101, "Fellin, Pietro Orlando"),
        fx("f4", 5, 105, "Silva, Joao Dinis", 106, "WQF1"),
        fx("f5", 5, 107, "Nobody, Brand New", 108, "Hand, Old"),
        fx("f6", 6, 109, "Felin, Pietro", 110, "Hand, Old"),
    ])
    return m, players, alias_tml, xt, xo, f


def test_oddspapi_players_link_through_shared_matches_not_names():
    m, players, alias_tml, xt, xo, f = _world()
    odds, review, drift = link_oddspapi(f, xo, m, xt, alias_tml, players, year=2026, set_on="2026-10-13")
    st = odds.set_index("participant_id")
    fellin = _pid(alias_tml, "M", "F1")
    assert (st.loc["101", "player_id"], st.loc["101", "status"]) == (fellin, "confirmed")   # 3 shared matches
    assert st.loc["102", "player_id"] == _pid(alias_tml, "M", "S1")                          # "Tai Leonard" = "Tai"
    assert st.loc["105", "status"] == "review"        # partial name: Joao Dinis Silva vs Joao Silva, a person decides
    assert st.loc["106", "status"] == "placeholder"
    assert st.loc["107", "status"] == "no_history"
    assert (st.loc["109", "status"], st.loc["109", "method"]) == ("review", "near spelling")   # Felin ~ Fellin
    assert resolve_oddspapi_player(odds, 105) == (None, "review")
    assert resolve_oddspapi_player(odds, 106) == (None, "placeholder")
    assert resolve_oddspapi_player(odds, 999) == (None, "unknown")
    assert resolve_oddspapi_player(odds, 101) == (fellin, "confirmed")


def test_stored_user_links_survive_and_disagreements_are_reported():
    m, players, alias_tml, xt, xo, f = _world()
    odds, _, _ = link_oddspapi(f, xo, m, xt, alias_tml, players, year=2026, set_on="2026-10-13")
    stored = odds.copy()
    stored.loc[stored["participant_id"] == "105", ["player_id", "status"]] = [_pid(alias_tml, "M", "J1"), "user"]
    stored.loc[stored["participant_id"] == "102", ["player_id", "status"]] = ["M-999999", "user"]
    odds2, _, drift = link_oddspapi(f, xo, m, xt, alias_tml, players, stored, year=2026, set_on="2026-10-14")
    st = odds2.set_index("participant_id")
    assert (st.loc["105", "status"], st.loc["105", "player_id"]) == ("user", _pid(alias_tml, "M", "J1"))
    assert st.loc["102", "player_id"] == "M-999999"
    assert "102" in set(drift["participant_id"])


def test_umlaut_spellings_are_one_name():
    # OddsPapi "Wuerth, Tara" and TennisMyLife "Tara Wurth" are Tara Würth (user, 2026-10-13).
    assert player_key("Wuerth, Tara") == player_key("Tara Wurth") == player_key("Tara Würth")
    assert player_key("Mueller, Jan") == player_key("Jan Müller") and player_key("Manuel Goes") == player_key("Goes, Manuel")
    assert player_key("Andres Guerra") != player_key("Andres Gurra") and "rodriguez" in player_key("Rodriguez, Ana")


def test_placeholders_and_ids():
    for name in ("WQF1", "Qf8", "WSF2", "R16P14", "Q1", "LL2", "TBD", "Qualifier"):
        assert is_placeholder_participant(name), name
    for name in ("Quinn, Ethan", "Qu, Yihan", "Llamas Ruiz, Pablo", "Cretu, Cezar (2001)", "Emanuela Lares"):
        assert not is_placeholder_participant(name), name
    assert normalize_tml_id("211817.0") == "211817" and normalize_tml_id("nan") is None and normalize_tml_id(" DH58 ") == "DH58"
