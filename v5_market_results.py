"""Winners for price-store fixtures, joined through our ids (no name matching here).

Two sources: TennisMyLife first, then Kalshi's settled match markets for what TennisMyLife
does not publish (WTA 125; user decision 2026-10-16). `result_source` says which. Where both
have a fixture they must agree; `scripts/check_results_sources.py` reports any disagreement.

A TennisMyLife result belongs to a stored fixture when both resolve to the same master
schedule edition and the same two players (our `player_id`s): the TennisMyLife tournament
through crosswalk_tennismylife.csv, its two player ids through alias_tennismylife.csv. A
pair that meets twice in one edition is ambiguous and gets no winner (fail closed).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from v5_player_registry import TML_ALIAS_COLUMNS, USABLE_STATUSES, load_table, load_tml_matches, tml_node
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
        w = pid.get((m.tour, tml_node(m.winner_id, m.winner_name)))
        l = pid.get((m.tour, tml_node(m.loser_id, m.loser_name)))
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


def kalshi_winners(markets: pd.DataFrame) -> pd.DataFrame:
    """fixture_id -> winner_side from Kalshi's settled player markets tied to a fixture.

    A fixture has a winner only when its markets agree: one side settled "yes" and no other
    side settled "yes" (a "no" for the other side, when stored, must say the same). Any other
    settlement (for example "scalar" after a retirement or a void) gives no result."""
    m = markets[(markets["fixture_id"].astype(str) != "") & markets["side"].isin(["p1", "p2"])]
    out = []
    for fid, g in m.groupby("fixture_id"):
        results = dict(zip(g["side"], g["result"].astype(str).str.lower()))
        if set(results.values()) - {"yes", "no"}:
            continue
        yes = [side for side, r in results.items() if r == "yes"]
        if len(yes) == 1 and not (len(results) == 2 and list(results.values()).count("no") != 1):
            out.append({"fixture_id": fid, "winner_side": yes[0]})
    return pd.DataFrame(out, columns=["fixture_id", "winner_side"])


def load_kalshi_markets(base: str | Path = ".") -> pd.DataFrame:
    """Stored Kalshi markets with their fixture from the rebuilt map (fixture_map.csv) when
    there is one, else the match made at pull time."""
    kdir = Path(base) / "market_history" / "kalshi"
    paths = sorted((kdir / "markets").glob("*.csv"))
    cols = ["ticker", "fixture_id", "side", "result"]
    markets = pd.concat([pd.read_csv(p, dtype=str, keep_default_na=False, usecols=cols) for p in paths]) if paths \
        else pd.DataFrame(columns=cols)
    fmap = kdir / "fixture_map.csv"
    if fmap.exists() and len(markets):
        m = pd.read_csv(fmap, dtype=str, keep_default_na=False).set_index("ticker")
        known = markets["ticker"].isin(m.index)
        markets.loc[known, "fixture_id"] = markets.loc[known, "ticker"].map(m["fixture_id"])
        markets.loc[known, "side"] = markets.loc[known, "ticker"].map(m["side"])
    return markets


def combine_winners(tml: pd.DataFrame, kalshi: pd.DataFrame) -> pd.DataFrame:
    """TennisMyLife first; Kalshi for fixtures TennisMyLife does not have."""
    a = tml.assign(result_source="tennismylife")
    b = kalshi[~kalshi["fixture_id"].isin(tml["fixture_id"])].assign(result_source="kalshi")
    return pd.concat([a, b], ignore_index=True)[["fixture_id", "winner_side", "result_source"]]


def load_fixture_winners(fixtures: pd.DataFrame, base: str | Path = ".", *, sources=("tennismylife", "kalshi")) -> pd.DataFrame:
    base = Path(base)
    tml = pd.DataFrame(columns=["fixture_id", "winner_side"])
    if "tennismylife" in sources:
        matches = load_tml_matches(base / ".v5_history_cache", base / "v5_results_ready" / "tennismylife_results.csv",
                                   base / "context_registry" / "players" / "tml_row_corrections.csv")
        crosswalk = load_crosswalk(base / "context_registry" / "master_schedule" / "crosswalk_tennismylife.csv")
        alias = load_table(base / "context_registry" / "players" / "alias_tennismylife.csv", TML_ALIAS_COLUMNS)
        tml = fixture_winners(fixtures, tml_results(matches, crosswalk, alias))
    kal = pd.DataFrame(columns=["fixture_id", "winner_side"])
    if "kalshi" in sources:
        kal = kalshi_winners(load_kalshi_markets(base))
        kal = kal[kal["fixture_id"].isin(fixtures["fixture_id"])]
    return combine_winners(tml, kal)
