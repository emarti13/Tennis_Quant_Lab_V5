"""Fixture resolution: edition + players from the stored tables, failing closed."""
from __future__ import annotations

import pandas as pd
import pytest

from v5_fixture_resolution import FixtureResolutionError, FixtureResolver


def _edition(key, name, family, start, surface="Hard", setting="Outdoor", circuit="ATP 250"):
    return {"edition_key": key, "tournament_name": name, "tour_family": family, "circuit_tour": circuit,
            "start_date": start, "surface": surface, "setting": setting, "location_source": "geocoded",
            "latitude": 1.0, "longitude": 2.0, "altitude_m": 10, "time_zone": "Europe/Rome"}


def _fixture(fid, tid, tname, start, a=(1, "Alpha, Al"), b=(2, "Beta, Bo")):
    return {"fixture_id": fid, "tournament_id": tid, "tournament_name": tname, "start_time_utc": start,
            "participant1_id": a[0], "participant1_name": a[1], "participant2_id": b[0], "participant2_name": b[1]}


def _xw(tid, first, last, key, status="confirmed"):
    return {"tournament_id": str(tid), "first_date": first, "last_date": last, "edition_key": key, "status": status}


def _resolver(**over):
    editions = pd.DataFrame([
        _edition("CH|porto", "Porto", "CHALLENGER", "2026-08-31", surface="Clay"),
        _edition("ATP|uso", "US Open", "ATP", "2026-08-31", circuit="Grand Slam"),
        _edition("ATP|uc", "United Cup", "ATP", "2026-01-02", circuit="United Cup"),
        _edition("WTA|x", "Some Open", "WTA125", "2026-09-07", surface="Clay"),
    ])
    fixtures = pd.DataFrame([
        _fixture("f-porto", 10, "ATP Challenger Porto", "2026-09-01T10:00:00Z"),
        _fixture("f-uso-q", 20, "US Open Men Singles", "2026-08-25T10:00:00Z"),
        _fixture("f-uso", 20, "US Open Men Singles", "2026-09-02T10:00:00Z"),
        _fixture("f-review", 30, "ATP Challenger Crete", "2026-03-02T10:00:00Z"),
        _fixture("f-2027", 10, "ATP Challenger Porto", "2027-09-01T10:00:00Z"),
        _fixture("f-slot", 10, "ATP Challenger Porto", "2026-09-02T10:00:00Z", a=(9, "WQF1")),
        _fixture("f-new", 10, "ATP Challenger Porto", "2026-09-02T10:00:00Z", b=(3, "Gamma, Ga")),
        _fixture("f-held", 10, "ATP Challenger Porto", "2026-09-02T10:00:00Z", b=(4, "Delta, De")),
        _fixture("f-unknown", 10, "ATP Challenger Porto", "2026-09-02T10:00:00Z", b=(5, "Eps, Ep")),
        _fixture("f-uc", 40, "United Cup", "2026-01-03T10:00:00Z"),
        _fixture("f-wta", 50, "WTA 125K Some", "2026-09-08T10:00:00Z"),
    ])
    xw = pd.DataFrame([_xw(10, "2026-08-30", "2026-09-06", "CH|porto"), _xw(20, "2026-08-24", "2026-09-13", "ATP|uso"),
                       _xw(30, "2026-03-02", "2026-03-08", "", "review"), _xw(10, "2027-08-30", "2027-09-06", "CH|porto"),
                       _xw(40, "2026-01-02", "2026-01-11", "ATP|uc"), _xw(50, "2026-09-06", "2026-09-13", "WTA|x")])
    alias_odds = pd.DataFrame([
        {"participant_id": "1", "player_id": "M-1", "status": "confirmed"},
        {"participant_id": "2", "player_id": "M-2", "status": "auto"},
        {"participant_id": "3", "player_id": "", "status": "no_history"},
        {"participant_id": "4", "player_id": "", "status": "review"},
    ])
    alias_tml = pd.DataFrame([{"tour": "M", "tml_id": "A1", "player_id": "M-1", "names": "Al Alpha | Al ALPHA"},
                              {"tour": "M", "tml_id": "B1", "player_id": "M-2", "names": "Bo Beta"}])
    ratings = {"MEN": pd.DataFrame([{"player": "Al Alpha", "elo_matches": 50}, {"player": "Al ALPHA", "elo_matches": 3},
                                    {"player": "Bo Beta", "elo_matches": 20}]),
               "WTA": pd.DataFrame([{"player": "Al Alpha", "elo_matches": 1}])}
    args = dict(fixtures=fixtures, editions_by_year={2026: editions}, crosswalk_oddspapi=xw,
                overrides=pd.DataFrame(columns=["edition_key", "field", "value", "set_on", "note"]),
                alias_oddspapi=alias_odds, alias_tennismylife=alias_tml, ratings_by_tour=ratings)
    args.update(over)
    return FixtureResolver(**args)


def test_resolves_edition_court_and_players():
    r = _resolver().resolve("f-porto")
    assert (r.edition_key, r.surface, r.setting, r.tour, r.best_of) == ("CH|porto", "Clay", "Outdoor", "MEN", 3)
    assert r.player1.player_id == "M-1" and r.player1.rating_name == "Al Alpha"   # spelling with most rated matches
    assert r.priceable and r.sources["surface"] == "schedule"


def test_mens_slam_main_draw_is_best_of_five_but_qualifying_is_not():
    R = _resolver()
    assert R.resolve("f-uso").best_of == 5
    assert R.resolve("f-uso-q").best_of == 3      # qualifying is played before the edition starts


def test_overrides_win_and_say_so():
    ov = pd.DataFrame([{"edition_key": "CH|porto", "field": "surface", "value": "Hard", "set_on": "2026-10-15", "note": "user"}])
    r = _resolver(overrides=ov).resolve("f-porto")
    assert r.surface == "Hard" and r.sources["surface"] == "override"


def test_wta_125_uses_the_womens_ratings():
    assert _resolver().resolve("f-wta").tour == "WTA"


@pytest.mark.parametrize("fid,code", [
    ("nope", "FIXTURE_UNKNOWN"),
    ("f-review", "TOURNAMENT_UNRESOLVED"),       # crosswalk row held for review: no price
    ("f-2027", "NO_SCHEDULE_FOR_YEAR"),
    ("f-slot", "PLACEHOLDER"),
    ("f-held", "PLAYER_UNRESOLVED"),             # player held for review
    ("f-unknown", "PLAYER_UNRESOLVED"),          # participant not in the tables yet
    ("f-uc", "TEAM_EVENT_NOT_PRICED"),
])
def test_fails_closed(fid, code):
    with pytest.raises(FixtureResolutionError) as e:
        _resolver().resolve(fid)
    assert e.value.code == code


def test_edition_removed_from_the_sheet_fails_closed():
    eds = pd.DataFrame([_edition("CH|other", "Other", "CHALLENGER", "2026-08-31")])
    with pytest.raises(FixtureResolutionError) as e:
        _resolver(editions_by_year={2026: eds}).resolve("f-porto")
    assert e.value.code == "EDITION_MISSING"


def test_no_history_player_is_shown_but_not_priceable():
    r = _resolver().resolve("f-new")
    assert r.player2.player_id is None and r.player2.status == "no_history"
    assert not r.priceable


def test_identify_fills_what_resolves_and_names_the_first_failure():
    R = _resolver()
    assert R.identify("f-porto") == {"edition_key": "CH|porto", "player1_id": "M-1", "player2_id": "M-2", "resolution": "ok"}
    assert R.identify("f-new") == {"edition_key": "CH|porto", "player1_id": "M-1", "player2_id": "", "resolution": "NO_HISTORY"}
    held = R.identify("f-held")
    assert (held["edition_key"], held["player1_id"], held["resolution"]) == ("CH|porto", "M-1", "PLAYER_UNRESOLVED")
    review = R.identify("f-review")
    assert (review["edition_key"], review["player1_id"], review["resolution"]) == ("", "M-1", "TOURNAMENT_UNRESOLVED")
    assert R.identify("nope")["resolution"] == "FIXTURE_UNKNOWN"
