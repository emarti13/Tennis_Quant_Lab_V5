"""Tournament identity: sheet loading and source matching (spec 2026-10-12, draft)."""
from __future__ import annotations

import pandas as pd

from v5_tournament_identity import (
    build_crosswalk,
    confirm_matches,
    fix_mojibake,
    load_master_schedule,
    match_pair,
    match_source,
    player_key,
    resolve_edition,
    shared_pairs,
    suggest_from_other_source,
    tennismylife_tournaments,
    tour_family,
    trailing_number,
)

HEADER = ["Year", "Start Date", "End Date", "Circuit Type", "Circuit Tour", "Tournament Name", "City", "State",
          "Country Code", "Country", "Time Zone", "Category", "Currency", "Prize Money",
          "Surface Code", "Surface", "Setting", "Scheduling / Notes"]


def _sheet(tmp_path, rows):
    path = tmp_path / "sheet.tsv"
    lines = ["\t".join(HEADER)]
    for r in rows:
        lines.append("\t".join(r.get(h, "") for h in HEADER))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return load_master_schedule(path)


def _ch(start, end, name, city, code="H", surface="Hard", setting="Outdoor", notes=""):
    return {"Year": "2026", "Start Date": start, "End Date": end, "Circuit Tour": "ATP Challenger 75",
            "Tournament Name": name, "City": city, "Country Code": "ESP",
            "Surface Code": code, "Surface": surface, "Setting": setting, "Scheduling / Notes": notes}


def _src(name, family, first, last=None, sid=None, players=(), pairs=()):
    return {"source": "test", "source_id": sid or name, "tournament_id": sid or name, "name": name,
            "family": family, "first_date": first, "last_date": last or first, "fixtures": 1,
            "players": set(players), "surface": "", "pairs": {match_pair(a, b) for a, b in pairs}}


def test_text_helpers():
    assert fix_mojibake("TrophÃ¨e Clarins") == "Trophèe Clarins"
    assert fix_mojibake("Plain name") == "Plain name"
    assert trailing_number("ATP Challenger Istanbul 3, Turkiye Men Singles") == 3
    assert trailing_number("ATP Challenger Shymkent II, Kazakhstan Men Singles") == 2
    assert trailing_number("WTA 125K Antalya, Turkiye Women Singles") is None
    assert player_key("Ito, Aoi") == player_key("Aoi Ito")


def test_tour_family_flags_grand_slam_inference():
    assert tour_family("ATP Challenger 125", True) == ("CHALLENGER", None)
    assert tour_family("WTA 125", False)[0] == "WTA125"
    fam, issue = tour_family("Grand Slam", False)
    assert fam == "WTA" and "Tour" in issue


def test_sheet_issues_are_reported_not_hidden(tmp_path):
    eds, issues = _sheet(tmp_path, [
        _ch("1/5/2026", "1/11/2026", "Alpha", "Alpha", code="IH", surface="Hard", setting="Outdoor"),
        _ch("1/5/2026", "", "Beta", "Beta", notes="Cancelled"),
    ])
    messages = {(i.field, i.severity) for i in issues}
    assert ("Surface Code", "error") in messages          # IH says indoor, Setting says outdoor
    assert ("End Date", "info") in messages               # missing end date assumed, and said so
    assert eds.set_index("tournament_name").loc["Beta", "status"] == "cancelled"


def test_back_to_back_weeks_in_one_city_stay_apart(tmp_path):
    eds, _ = _sheet(tmp_path, [
        _ch("2/2/2026", "2/8/2026", "Tenerife 1", "Tenerife"),
        _ch("2/9/2026", "2/15/2026", "Tenerife 2", "Tenerife"),
    ])
    src = pd.DataFrame([
        _src("ATP Challenger Tenerife, Spain Men Singles", "CHALLENGER", "2026-02-01", "2026-02-08", "a"),
        _src("ATP Challenger Tenerife 2, Spain Men Singles", "CHALLENGER", "2026-02-08", "2026-02-15", "b"),
    ])
    m = match_source(src, eds).set_index("source_id")
    assert m.loc["a", "sheet_name"] == "Tenerife 1"
    assert m.loc["b", "sheet_name"] == "Tenerife 2"


def test_no_guess_when_nothing_or_several_fit(tmp_path):
    eds, _ = _sheet(tmp_path, [
        _ch("3/2/2026", "3/8/2026", "Hersonissos 1", "Hersonissos"),
        _ch("3/2/2026", "3/8/2026", "Brasilia", "Brasilia"),
    ])
    src = pd.DataFrame([_src("Crete 1", "CHALLENGER", "2026-03-02", sid="x")])
    m = match_source(src, eds).iloc[0]
    assert m["status"] == "unmatched" and m["edition_key"] == ""
    assert "Hersonissos 1" in m["candidates"]


def test_cancelled_editions_are_never_matched(tmp_path):
    eds, _ = _sheet(tmp_path, [_ch("3/2/2026", "3/8/2026", "Fujairah 1", "Fujairah", notes="Cancelled")])
    src = pd.DataFrame([_src("ATP Challenger Fujairah, UAE Men Singles", "CHALLENGER", "2026-03-02")])
    assert match_source(src, eds).iloc[0]["status"] == "unmatched"


def test_shared_matches_tolerate_name_variants():
    odds = {match_pair("Palomero Dedura, Diego", "Ajdukovic, Duje"), match_pair("Ito, Aoi", "Sato, Ena")}
    tml = {match_pair("Diego Dedura", "Duje Ajdukovic"), match_pair("Aoi Ito", "Mai Kim")}
    assert shared_pairs(tml, odds) == 1   # same two players; a shared player alone is not a shared match


def _results(rows):
    return pd.DataFrame([{"tourney_id": tid, "tourney_date": d, "tourney_name": name, "result_file": "2026_challenger.csv",
                          "tourney_level": "C", "surface": "Hard", "winner_name": w, "loser_name": l}
                         for tid, d, name, w, l in rows])


def test_tennismylife_id_reused_for_two_editions_is_split(tmp_path):
    # TennisMyLife gave both 2026 San Diego Challengers the id 2026-2971.
    eds, _ = _sheet(tmp_path, [_ch("1/26/2026", "2/1/2026", "San Diego", "San Diego"),
                               _ch("9/21/2026", "9/27/2026", "San Diego 2", "San Diego")])
    tml = tennismylife_tournaments(_results([("2026-2971", 20260126, "San Diego", "A One", "B Two"),
                                             ("2026-2971", 20260921, "San Diego 2", "C Three", "D Four")]), 2026)
    assert sorted(tml["source_id"]) == ["2026-2971@2026-01-26", "2026-2971@2026-09-21"]
    m = match_source(tml, eds).set_index("source_id")
    assert m.loc["2026-2971@2026-01-26", "sheet_name"] == "San Diego"
    assert m.loc["2026-2971@2026-09-21", "sheet_name"] == "San Diego 2"


def _two_weeks(tmp_path):
    eds, _ = _sheet(tmp_path, [_ch("3/2/2026", "3/8/2026", "Abidjan", "Abidjan"),
                               _ch("3/9/2026", "3/15/2026", "Abidjan 2", "Abidjan")])
    week1 = [("P1", "P2"), ("P3", "P4"), ("P5", "P6"), ("P7", "P8")]
    week2 = [("P1", "P2"), ("Q1", "Q2"), ("Q3", "Q4"), ("Q5", "Q6")]  # two players meet again a week later
    tml = pd.DataFrame([_src("Abidjan", "CHALLENGER", "2026-03-02", sid="t1", pairs=week1),
                        _src("Abidjan 2", "CHALLENGER", "2026-03-09", sid="t2", pairs=week2)])
    return eds, week1, week2, tml


def test_confirmation_uses_shared_matches_relative_to_neighbours(tmp_path):
    eds, week1, week2, tml = _two_weeks(tmp_path)
    odds = pd.DataFrame([_src("ATP Challenger Abidjan", "CHALLENGER", "2026-03-01", sid="o1", pairs=week1),
                         _src("ATP Challenger Abidjan 2", "CHALLENGER", "2026-03-08", sid="o2", pairs=week2[:2])])
    om, tm = match_source(odds, eds), match_source(tml, eds)
    c = confirm_matches(odds, om, tml, tm).set_index("source_id")
    assert c.loc["o1", "confirmation"] == "confirmed" and c.loc["o1", "pairs_same_edition"] == 4
    assert c.loc["o2", "confirmation"] == "unconfirmed"   # 2 shared with its own week, 1 with the week before

    # Map the second block to the wrong week on purpose: the results say otherwise.
    bad = om.copy()
    bad.loc[bad.source_id == "o1", "edition_key"] = tm.set_index("source_id").loc["t2", "edition_key"]
    c = confirm_matches(odds, bad, tml, tm).set_index("source_id")
    assert c.loc["o1", "confirmation"] == "conflict"
    assert c.loc["o1", "best_other"] == tm.set_index("source_id").loc["t1", "edition_key"]


def test_crosswalk_statuses_and_kept_rows(tmp_path):
    eds, week1, week2, tml = _two_weeks(tmp_path)
    odds = pd.DataFrame([_src("ATP Challenger Abidjan", "CHALLENGER", "2026-03-01", sid="11@2026-03-01", pairs=week1),
                         _src("ATP Challenger Abidjan 2", "CHALLENGER", "2026-03-08", sid="12@2026-03-08"),
                         _src("ATP Challenger Nowhere", "CHALLENGER", "2026-03-01", sid="13@2026-03-01")])
    om, tm = match_source(odds, eds), match_source(tml, eds)
    xw, drift = build_crosswalk(om, confirm_matches(odds, om, tml, tm), set_on="2026-03-20")
    st = xw.set_index("source_id")["status"]
    assert st["11@2026-03-01"] == "confirmed"
    assert st["12@2026-03-08"] == "auto"      # matched, but no shared matches to confirm it yet
    assert st["13@2026-03-01"] == "review"    # unmatched: never guessed
    assert drift.empty

    # A user decision survives a later run that would decide differently.
    stored = xw.copy()
    stored.loc[stored.source_id == "13@2026-03-01", ["status", "edition_key"]] = ["user", "MANUAL"]
    xw2, drift = build_crosswalk(om, confirm_matches(odds, om, tml, tm), stored, set_on="2026-03-21")
    row = xw2.set_index("source_id").loc["13@2026-03-01"]
    assert (row["status"], row["edition_key"]) == ("user", "MANUAL")
    assert list(drift["source_id"]) == ["13@2026-03-01"]


def test_resolve_edition_fails_closed():
    xw = pd.DataFrame([
        {"tournament_id": "11", "first_date": "2026-03-01", "last_date": "2026-03-07", "edition_key": "E1", "status": "confirmed"},
        {"tournament_id": "11", "first_date": "2026-09-20", "last_date": "2026-09-26", "edition_key": "E2", "status": "auto"},
        {"tournament_id": "12", "first_date": "2026-03-01", "last_date": "2026-03-07", "edition_key": "E3", "status": "review"},
    ])
    assert resolve_edition(xw, 11, "2026-03-05", gap_days=4) == "E1"
    assert resolve_edition(xw, "11", "2026-03-10", gap_days=4) == "E1"   # a late fixture in a running block
    assert resolve_edition(xw, 11, "2026-09-21", gap_days=4) == "E2"     # same id, other edition
    assert resolve_edition(xw, 11, "2026-06-01", gap_days=4) is None     # no block covers the date
    assert resolve_edition(xw, 12, "2026-03-05", gap_days=4) is None     # held for review
    assert resolve_edition(xw, 99, "2026-03-05", gap_days=4) is None     # never seen


def test_circuit_type_decides_mens_and_womens_events(tmp_path):
    slam = {"Year": "2026", "Start Date": "8/31/2026", "Circuit Tour": "Grand Slam", "Tournament Name": "US Open",
            "City": "New York", "Country": "United States", "Surface Code": "H", "Surface": "Hard", "Setting": "Outdoor"}
    eds, issues = _sheet(tmp_path, [{**slam, "Circuit Type": "Men"}, {**slam, "Circuit Type": "Women"}])
    assert sorted(eds["tour_family"]) == ["ATP", "WTA"]
    assert not any(i.field == "Circuit Tour" for i in issues)   # no end-date guess needed


def test_same_event_listed_under_two_tours_is_flagged_but_weekly_events_are_not(tmp_path):
    def wta(start, tour, name, city):
        return {"Year": "2026", "Start Date": start, "Circuit Type": "Women", "Circuit Tour": tour,
                "Tournament Name": name, "City": city, "Surface Code": "H", "Surface": "Hard", "Setting": "Outdoor"}
    _, issues = _sheet(tmp_path, [
        wta("1/2/2026", "United Cup", "United Cup", "Perth"),
        wta("1/5/2026", "WTA 500", "United Cup", "Perth"),
        wta("2/23/2026", "WTA 125", "Megasaray Hotels Open", "Antalya"),
        wta("3/2/2026", "WTA 125", "Megasaray Hotels Open", "Antalya"),
    ])
    flagged = {i.row for i in issues if i.message.startswith("Possible duplicate")}
    assert flagged == {2, 3}


def test_location_choice_requires_country_and_flags_wrong_state():
    from v5_tournament_identity import pick_location

    candidates = [
        {"name": "Little Rock", "country_code": "US", "admin1": "Arkansas", "latitude": 34.7, "longitude": -92.3},
        {"name": "Little Rock", "country_code": "GB", "admin1": "England", "latitude": 52.0, "longitude": -1.0},
    ]
    pick, status, note = pick_location(candidates, "US", "Arizona")
    assert status == "state_mismatch" and pick is None and "Arizona" in note   # wrong state: no guess
    assert pick_location(candidates, "US", "Arkansas")[1] == "matched"
    assert pick_location(candidates, "FR", "")[1] == "unresolved"   # never a result from another country


def test_sheet_location_wins_and_missing_location_is_reported(tmp_path):
    import json
    from v5_tournament_identity import enrich_locations, load_countries, location_key

    eds, _ = _sheet(tmp_path, [
        {**_ch("3/2/2026", "3/8/2026", "Hersonissos 1", "Hersonissos"), "Country Code": "GRE"},
        {**_ch("3/9/2026", "3/15/2026", "Nowhere", "Nowhereville"), "Country Code": "GRE"},
    ])
    eds.loc[eds.tournament_name == "Hersonissos 1", "sheet_time_zone"] = "Europe/Athens"
    cache = pd.DataFrame([{
        "location_key": location_key("Hersonissos", "", "GR"),
        "results_json": json.dumps([{"name": "Hersonissos", "country_code": "GR", "admin1": "Crete",
                                     "latitude": 35.3, "longitude": 25.37, "elevation": 107, "timezone": "Europe/Athens"}]),
    }])
    out, issues = enrich_locations(eds, cache, load_countries())
    h = out.set_index("tournament_name")
    assert h.loc["Hersonissos 1", "location_source"] == "geocoded" and h.loc["Hersonissos 1", "region"] == "Crete"
    assert h.loc["Hersonissos 1", "country_name"] == "Greece"
    assert h.loc["Nowhere", "location_source"] == "missing" and h.loc["Nowhere", "time_zone"] == ""
    assert any("location not found" in i.message for i in issues)


def test_location_rules_real_places_largest_town_and_no_guess():
    from v5_tournament_identity import pick_location

    def c(name, admin1, pop, lat, lon, code="PPL"):
        return {"name": name, "country_code": "MX", "admin1": admin1, "population": pop,
                "latitude": lat, "longitude": lon, "feature_code": code}

    # Official name extends the city's name; tiny same-named villages lose to the real city.
    pick, status, _ = pick_location([c("Acapulco de Juárez", "Guerrero", 658609, 16.85, -99.91),
                                     c("Acapulco", "Chiapas", 185, 16.11, -91.51)], "MX", "", query="Acapulco")
    assert status == "matched" and pick["admin1"] == "Guerrero"
    # Airports are never a city's location.
    pick, status, _ = pick_location([c("Los Cabos International Airport", "Baja California Sur", None, 23.15, -109.72, "AIRP")],
                                    "MX", "", query="Los Cabos")
    assert pick is None and status == "unresolved"
    # Several entries within 50 km are one place (Hong Kong-style duplicates).
    pick, status, _ = pick_location([c("Hong Kong", None, 7396076, 22.28, 114.17), c("Hong Kong", None, 1195529, 22.27, 114.18)],
                                    "MX", "", query="Hong Kong")
    assert status == "matched"
    # Same-named places far apart with no clear largest: left empty, never guessed.
    pick, status, _ = pick_location([c("Jingshan", "Anhui", None, 31.3, 118.4), c("Jingshan", "Beijing", None, 39.9, 116.4)],
                                    "MX", "", query="Jingshan")
    assert pick is None and status == "ambiguous"


def test_unmatched_rows_get_a_suggestion_from_the_other_sources_results_but_stay_in_review(tmp_path):
    # "Copa Internacional de Tenis" matches no sheet row by name; its matches are the
    # same as OddsPapi's Curitiba block, which is mapped. Suggest, do not map (user, 2026-10-15).
    week = [("P1", "P2"), ("P3", "P4"), ("P5", "P6"), ("P7", "P8")]
    tml = pd.DataFrame([_src("Copa Internacional de Tenis", "CHALLENGER", "2026-09-28", sid="t1", pairs=week)])
    odds = pd.DataFrame([_src("ATP Challenger Curitiba", "CHALLENGER", "2026-09-27", sid="o1", pairs=week),
                         _src("ATP Challenger Columbus", "CHALLENGER", "2026-09-27", sid="o2", pairs=[("Q1", "Q2")])])
    xw_t = pd.DataFrame([{"source_id": "t1", "first_date": "2026-09-28", "status": "review", "edition_key": ""}])
    xw_o = pd.DataFrame([{"source_id": "o1", "edition_key": "CH|curitiba", "status": "auto"},
                         {"source_id": "o2", "edition_key": "CH|columbus", "status": "auto"}])
    assert suggest_from_other_source(tml, xw_t, odds, xw_o) == {"t1": ("CH|curitiba", 4)}
    assert xw_t["status"].iloc[0] == "review"
