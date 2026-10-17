"""Stage label: Kalshi's round text first, then the edition's calendar and who already played."""
from __future__ import annotations

import pandas as pd

from v5_fixture_stage import fixture_stages, kalshi_round

E = "CHALLENGER|2026-03-02|x|x"      # starts Monday 2026-03-02
W = "WTA|2026-03-02|y|y"
GS = "WTA|2026-05-25|roland-garros|paris"
LEVELS = {E: "ATP Challenger 75", W: "WTA 250", GS: "Grand Slam"}


def fx(fid, ed, when, a, b):
    return {"fixture_id": fid, "edition_key": ed, "start_time_utc": when, "participant1_id": a, "participant2_id": b}


def stages(rows, kalshi=None):
    return fixture_stages(pd.DataFrame(rows), kalshi, LEVELS).set_index("fixture_id")["stage"].to_dict()


def test_calendar_and_who_already_played():
    rows = [fx("q1", E, "2026-03-01T10:00:00Z", "1", "2"),     # Sunday: qualifying
            fx("q2", E, "2026-03-02T10:00:00Z", "1", "3"),     # Monday, 1 already played: qualifying final
            fx("m1", E, "2026-03-02T12:00:00Z", "8", "9"),     # Monday, both fresh, edition began Sunday: main
            fx("m2", E, "2026-03-03T10:00:00Z", "1", "8")]     # Tuesday: main
    assert stages(rows) == {"q1": "qualifying", "q2": "qualifying", "m1": "main", "m2": "main"}


def test_start_day_with_nothing_earlier_is_unknown():
    assert stages([fx("a", E, "2026-03-02T10:00:00Z", "1", "2")]) == {"a": "unknown"}


def test_tour_level_qualifier_against_a_direct_entrant_is_main_draw():
    rows = [fx("q1", W, "2026-03-01T10:00:00Z", "1", "2"),
            fx("r1", W, "2026-03-02T10:00:00Z", "1", "7"),     # only the qualifier played before
            fx("qf", W, "2026-03-02T11:00:00Z", "3", "4")]     # both fresh
    rows.append(fx("qx", W, "2026-03-01T12:00:00Z", "5", "6"))
    rows.append(fx("q2", W, "2026-03-02T12:00:00Z", "5", "2"))  # both played before: qualifying final
    got = stages(rows)
    assert got["r1"] == "main" and got["q2"] == "qualifying"


def test_grand_slam_main_draw_starts_the_sunday_before_the_listed_start():
    rows = [fx("q", GS, "2026-05-22T10:00:00Z", "1", "2"), fx("s", GS, "2026-05-24T10:00:00Z", "1", "3")]
    assert stages(rows) == {"q": "qualifying", "s": "main"}


def test_kalshi_round_text_decides_when_kalshi_lists_the_match():
    assert kalshi_round("... the 2026 ATP Challenger Kingston Qualification Final after ...") == "qualifying"
    assert kalshi_round("... the 2026 ATP Shanghai Round Of 128 after ...") == "main"
    assert kalshi_round("no round here") is None
    k = pd.DataFrame([{"fixture_id": "x", "rules_primary": "the 2026 ATP Challenger X Round Of 32"}])
    assert stages([fx("x", E, "2026-03-01T10:00:00Z", "1", "2")], k) == {"x": "main"}
