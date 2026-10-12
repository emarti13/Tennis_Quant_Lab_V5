"""Tournament identity: sheet loading and source matching (spec 2026-10-12, draft)."""
from __future__ import annotations

import pandas as pd

from v5_tournament_identity import (
    fix_mojibake,
    load_master_schedule,
    match_source,
    player_agreement,
    player_key,
    tour_family,
    trailing_number,
)

HEADER = ["Year", "Start Date", "End Date", "Circuit Tour", "Tournament Name", "City", "State",
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


def _src(name, family, first, last=None, sid=None, players=()):
    return {"source": "test", "source_id": sid or name, "tournament_id": sid or name, "name": name,
            "family": family, "first_date": first, "last_date": last or first, "fixtures": 1,
            "players": set(players), "surface": ""}


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


def test_player_agreement_tolerates_name_variants(tmp_path):
    eds, _ = _sheet(tmp_path, [_ch("5/11/2026", "5/17/2026", "Zagreb", "Zagreb")])
    odds = pd.DataFrame([_src("ATP Challenger Zagreb", "CHALLENGER", "2026-05-10", sid="o",
                              players=[player_key("Palomero Dedura, Diego"), player_key("Ajdukovic, Duje")])])
    tml = pd.DataFrame([_src("Zagreb", "CHALLENGER", "2026-05-11", sid="t",
                             players=[player_key("Diego Dedura"), player_key("Duje Ajdukovic")])])
    pa = player_agreement(odds, tml, match_source(odds, eds), match_source(tml, eds))
    assert pa.iloc[0]["share_found"] == 1.0
