"""Winners for price-store fixtures, joined through our ids (no name matching here).

A TennisMyLife result belongs to a stored fixture when both resolve to the same master
schedule edition and the same two players (our `player_id`s): the TennisMyLife tournament
through crosswalk_tennismylife.csv, its two player ids through alias_tennismylife.csv. A
pair that meets twice in one edition is ambiguous and gets no winner (fail closed).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from v5_player_registry import TML_ALIAS_COLUMNS, USABLE_STATUSES, load_table, load_tml_matches
from v5_tournament_identity import TENNISMYLIFE_GAP_DAYS, load_crosswalk, resolve_edition


def tml_results(matches: pd.DataFrame, crosswalk: pd.DataFrame, alias: pd.DataFrame) -> pd.DataFrame:
    """One row per TennisMyLife match that resolves: edition_key, winner_id, loser_id (ours)."""
    usable = alias[alias["status"].isin(USABLE_STATUSES)]
    pid = {(r.tour, str(r.tml_id)): r.player_id for r in usable.itertuples()}
    editions: dict[tuple, str | None] = {}
    rows = []
    for m in matches.itertuples():
        key = (str(m.tourney_id), m.date)
        if key not in editions:
            editions[key] = resolve_edition(crosswalk, m.tourney_id, m.date, gap_days=TENNISMYLIFE_GAP_DAYS) \
                if pd.notna(m.date) else None
        edition = editions[key]
        w, l = pid.get((m.tour, str(m.winner_id))), pid.get((m.tour, str(m.loser_id)))
        if edition and w and l and w != l:
            rows.append({"edition_key": edition, "winner_id": w, "loser_id": l})
    return pd.DataFrame(rows, columns=["edition_key", "winner_id", "loser_id"])


def fixture_winners(fixtures: pd.DataFrame, results: pd.DataFrame) -> pd.DataFrame:
    """fixture_id -> winner_side (p1/p2) for stored fixtures with edition and both player ids."""
    pair = lambda a, b: "|".join(sorted((a, b)))
    res = results.assign(pair=[pair(w, l) for w, l in zip(results["winner_id"], results["loser_id"])])
    counts = res.groupby(["edition_key", "pair"]).size()
    unique = res.set_index(["edition_key", "pair"])[["winner_id"]][~res.set_index(["edition_key", "pair"]).index.isin(
        counts[counts > 1].index)]
    winner = unique["winner_id"].to_dict()
    out = []
    for f in fixtures.itertuples():
        if not (f.edition_key and f.player1_id and f.player2_id):
            continue
        w = winner.get((f.edition_key, pair(f.player1_id, f.player2_id)))
        if w:
            out.append({"fixture_id": f.fixture_id, "winner_side": "p1" if w == f.player1_id else "p2"})
    return pd.DataFrame(out, columns=["fixture_id", "winner_side"])


def load_fixture_winners(fixtures: pd.DataFrame, base: str | Path = ".") -> pd.DataFrame:
    base = Path(base)
    matches = load_tml_matches(base / ".v5_history_cache", base / "v5_results_ready" / "tennismylife_results.csv",
                               base / "context_registry" / "players" / "tml_row_corrections.csv")
    crosswalk = load_crosswalk(base / "context_registry" / "master_schedule" / "crosswalk_tennismylife.csv")
    alias = load_table(base / "context_registry" / "players" / "alias_tennismylife.csv", TML_ALIAS_COLUMNS)
    return fixture_winners(fixtures, tml_results(matches, crosswalk, alias))
