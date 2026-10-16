"""User decisions live in their own files; rebuilds read them and never write them."""
from __future__ import annotations

import pandas as pd
import pytest

from v5_player_registry import apply_odds_decisions, apply_tml_decisions, load_odds_decisions
from v5_tournament_identity import apply_crosswalk_decisions, load_decisions

XW = ["source", "source_id", "tournament_id", "source_name", "family", "first_date", "last_date", "edition_key",
      "status", "method", "pairs_same_edition", "pairs_best_other", "note", "set_on"]


def _xw(sid, name, status, key=""):
    return {c: "" for c in XW} | {"source": "tennismylife", "source_id": sid, "tournament_id": sid.split("@")[0],
                                  "source_name": name, "first_date": sid.split("@")[1], "last_date": sid.split("@")[1],
                                  "status": status, "edition_key": key}


def test_decisions_overlay_the_crosswalk_and_keep_its_description():
    stored = pd.DataFrame([_xw("t1@2026-09-28", "Copa Internacional", "review"),
                           _xw("t2@2026-03-02", "Old decision", "user", "E-OLD")])
    dec = pd.DataFrame([{"source_id": "t1@2026-09-28", "edition_key": "E-CURITIBA", "status": "user", "note": "n", "set_on": "d"},
                        {"source_id": "t9@2026-01-02", "edition_key": "", "status": "rejected", "note": "n", "set_on": "d"}])
    out = apply_crosswalk_decisions(stored, dec).set_index("source_id")
    assert (out.loc["t1@2026-09-28", "edition_key"], out.loc["t1@2026-09-28", "status"]) == ("E-CURITIBA", "user")
    assert out.loc["t1@2026-09-28", "source_name"] == "Copa Internacional"     # description kept
    assert out.loc["t9@2026-01-02", "status"] == "rejected"                    # decision for a row not yet built
    # A decision removed from the file stops applying: the rebuild re-decides that row.
    assert (out.loc["t2@2026-03-02", "status"], out.loc["t2@2026-03-02", "edition_key"]) == ("review", "")


def test_decision_files_are_validated(tmp_path):
    p = tmp_path / "d.csv"
    p.write_text("source_id,edition_key,status,note,set_on\nt1,,user,n,d\n", encoding="utf-8")
    with pytest.raises(ValueError, match="edition_key"):
        load_decisions(p)
    p.write_text("source_id,edition_key,status,note,set_on\nt1,E,user,n,d\nt1,E,user,n,d\n", encoding="utf-8")
    with pytest.raises(ValueError, match="one decision"):
        load_decisions(p)
    q = tmp_path / "o.csv"
    q.write_text("participant_id,player_id,status,note,set_on\n5,,user,n,d\n", encoding="utf-8")
    with pytest.raises(ValueError, match="player_id"):
        load_odds_decisions(q)
    assert load_decisions(tmp_path / "missing.csv").empty


def test_player_decisions_overlay_aliases():
    cols = ["participant_id", "tour", "names", "player_id", "status", "method", "shared_matches", "candidates", "note", "set_on"]
    alias = pd.DataFrame([dict(zip(cols, ["1", "W", "Wuerth, Tara", "W-1", "auto", "exact name", "0", "", "", "d"])),
                          dict(zip(cols, ["2", "M", "Old, Link", "M-9", "user", "user decision", "0", "", "", "d"]))])
    dec = pd.DataFrame([{"participant_id": "1", "player_id": "W-1", "status": "user", "note": "Tara Würth", "set_on": "d"}])
    out = apply_odds_decisions(alias, dec).set_index("participant_id")
    assert out.loc["1", "status"] == "user" and out.loc["1", "names"] == "Wuerth, Tara"
    assert (out.loc["2", "status"], out.loc["2", "player_id"]) == ("review", "")

    tml = pd.DataFrame([{"tour": "W", "tml_id": "215946", "player_id": "W-1", "names": "Ye Xin Ma", "countries": "CHN",
                         "matches": "8", "status": "auto", "method": "", "set_on": "d"},
                        {"tour": "W", "tml_id": "322417", "player_id": "W-2", "names": "Yexin Ma", "countries": "CHN",
                         "matches": "2", "status": "auto", "method": "", "set_on": "d"}])
    joins = pd.DataFrame([{"tour": "W", "tml_id": t, "player_id": "W-1", "note": "one player", "set_on": "d"} for t in ("215946", "322417")])
    out = apply_tml_decisions(tml, joins)
    assert set(out["player_id"]) == {"W-1"} and set(out["status"]) == {"user"}


def test_rebuild_scripts_never_write_decision_files():
    from pathlib import Path
    for script in ("scripts/reconcile_master_schedule.py", "scripts/build_player_registry.py", "scripts/refresh_identity.py"):
        text = Path(script).read_text(encoding="utf-8")
        for line in text.splitlines():
            if "decisions_" in line:
                assert ".to_csv" not in line and "write_text" not in line, (script, line)
