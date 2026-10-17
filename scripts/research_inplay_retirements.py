"""Research: how in-play winner calls behave on retirements, walkovers and defaults.

Usage:  python scripts/research_inplay_retirements.py   (after research_inplay_winners.py)

Joins TennisMyLife scores to the stored fixtures through our ids (same edition, same two
player ids, as v5_market_results does) and classifies each match: completed; retired or
defaulted with fewer than 2 completed sets; retired or defaulted with 2 or more; walkover.
Then reports, per class, how often the in-play call (loose and strict) names the
TennisMyLife winner.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from v5_player_registry import TML_ALIAS_COLUMNS, USABLE_STATUSES, load_table, tml_node  # noqa: E402
from v5_tournament_identity import TENNISMYLIFE_GAP_DAYS, load_crosswalk, resolve_edition  # noqa: E402

SET = re.compile(r"^(\d+)-(\d+)(?:\(\d+\))?$")


def completed_sets(score: str) -> int:
    n = 0
    for tok in str(score).split():
        m = SET.match(tok)
        if not m:
            continue
        a, b = int(m.group(1)), int(m.group(2))
        hi, lo = max(a, b), min(a, b)
        if (hi >= 6 and hi - lo >= 2) or (hi == 7 and lo in (5, 6)):
            n += 1
    return n


def classify(score: str) -> str:
    s = str(score).upper()
    if "W/O" in s or "WALKOVER" in s:
        return "walkover"
    if "RET" in s or "DEF" in s or "ABD" in s or "ABN" in s:
        return "retired_lt2_sets" if completed_sets(score) < 2 else "retired_2plus_sets"
    return "completed"


def main() -> int:
    r = pd.read_csv(BASE / "v5_results_ready" / "tennismylife_results.csv", dtype=str, keep_default_na=False)
    r["tour"] = r["result_file"].str.contains("wta", case=False).map({True: "W", False: "M"})
    r["date"] = pd.to_datetime(r["tourney_date"].str[:8], format="%Y%m%d", errors="coerce")
    alias = load_table(BASE / "context_registry" / "players" / "alias_tennismylife.csv", TML_ALIAS_COLUMNS)
    pid = {(a.tour, str(a.tml_id)): a.player_id for a in alias[alias["status"].isin(USABLE_STATUSES)].itertuples()}
    xw = load_crosswalk(BASE / "context_registry" / "master_schedule" / "crosswalk_tennismylife.csv")
    eds, rows = {}, []
    for m in r.itertuples():
        k = (m.tourney_id, m.date)
        if k not in eds:
            eds[k] = resolve_edition(xw, m.tourney_id, m.date, gap_days=TENNISMYLIFE_GAP_DAYS) if pd.notna(m.date) else None
        w = pid.get((m.tour, tml_node(m.winner_id or None, m.winner_name)))
        l = pid.get((m.tour, tml_node(m.loser_id or None, m.loser_name)))
        if eds[k] and w and l:
            rows.append({"edition_key": eds[k], "pair": "|".join(sorted((w, l))), "winner_id": w, "score": m.score})
    res = pd.DataFrame(rows).drop_duplicates(["edition_key", "pair"], keep=False)
    calls = pd.read_csv(BASE / "docs" / "experiments" / "data" / "inplay_winner_calls.csv", dtype=str, keep_default_na=False)
    calls["pair"] = ["|".join(sorted((a, b))) for a, b in zip(calls["player1_id"], calls["player2_id"])]
    d = calls.merge(res, on=["edition_key", "pair"])
    d["truth"] = (d["winner_id"] == d["player1_id"]).map({True: "p1", False: "p2"})
    d["class"] = d["score"].map(classify)
    report = {}
    for cls, g in d.groupby("class"):
        entry = {"matches": int(len(g))}
        for col in ("call", "strict"):
            called = g[g[col].isin(["p1", "p2"])]
            entry[col] = {"called": int(len(called)), "agree": int((called[col] == called["truth"]).sum()),
                          "disagree": int((called[col] != called["truth"]).sum())}
        report[cls] = entry
    examples = d[(d["class"] != "completed") & d["call"].isin(["p1", "p2"]) & (d["call"] != d["truth"])]
    report["wrong_examples"] = examples[["fixture_id", "edition_key", "score", "call", "strict", "truth"]].head(15).to_dict("records")
    out = BASE / "docs" / "experiments" / "data" / "inplay_retirements.json"
    out.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
