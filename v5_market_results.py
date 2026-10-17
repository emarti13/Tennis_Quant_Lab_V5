"""Winners for price-store fixtures, joined through our ids (no name matching here).

Three sources, in this order (`result_source` says which):
1. TennisMyLife;
2. Kalshi's settled match markets (user decision 2026-10-16);
3. the last in-play prices (user decision 2026-10-17; docs/experiments/2026-10-17-inplay-winners.md):
   the books that call the match agree and none is unclear. On 2026 data it called 46% of the
   matches TennisMyLife settles, with 3 wrong of 3,892 (all three retirements; none wrong on
   completed matches), and settles about half of the qualifying and WTA 125 matches
   TennisMyLife does not publish.
Where sources overlap they must agree; `scripts/check_results_sources.py` reports any
disagreement.

How a match ended (`outcome`, from the TennisMyLife score; "unknown" for the other sources):
completed, retired_lt2_sets (retired or defaulted before two completed sets),
retired_2plus_sets, walkover. **Matches that ended before two completed sets, and walkovers,
are void for measuring the model** (`void_for_measurement`; user decision 2026-10-17).
Settling real bets follows each book's own retirement rules instead (Step 5).

A TennisMyLife result belongs to a stored fixture when both resolve to the same master
schedule edition and the same two players (our `player_id`s): the TennisMyLife tournament
through crosswalk_tennismylife.csv, its two player ids through alias_tennismylife.csv. A
pair that meets twice in one edition is ambiguous and gets no winner (fail closed).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

from historical_odds_normalizer import flatten_history

from v5_player_registry import TML_ALIAS_COLUMNS, USABLE_STATUSES, load_table, load_tml_matches, tml_node
from v5_tournament_identity import TENNISMYLIFE_GAP_DAYS, load_crosswalk, resolve_edition


RESULT_COLUMNS = ["fixture_id", "winner_side", "result_source", "outcome", "void_for_measurement"]
VOID_OUTCOMES = {"retired_lt2_sets", "walkover"}
_SET = re.compile(r"^(\d+)-(\d+)(?:\(\d+\))?$")


def completed_sets(score: str) -> int:
    n = 0
    for tok in str(score).split():
        m = _SET.match(tok)
        if m:
            hi, lo = max(int(m.group(1)), int(m.group(2))), min(int(m.group(1)), int(m.group(2)))
            if (hi >= 6 and hi - lo >= 2) or (hi == 7 and lo in (5, 6)):
                n += 1
    return n


def match_outcome(score) -> str:
    """completed, retired_lt2_sets, retired_2plus_sets, walkover; unknown without a score."""
    s = str(score or "").upper()
    if not s.strip() or s == "NAN":
        return "unknown"
    if "W/O" in s or "WALKOVER" in s:
        return "walkover"
    if any(w in s for w in ("RET", "DEF", "ABD", "ABN")):
        return "retired_lt2_sets" if completed_sets(s) < 2 else "retired_2plus_sets"
    return "completed"


def tml_results(matches: pd.DataFrame, crosswalk: pd.DataFrame, alias: pd.DataFrame) -> pd.DataFrame:
    """One row per TennisMyLife match that resolves: edition_key, winner_id, loser_id (ours), outcome."""
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
            rows.append({"edition_key": edition, "winner_id": w, "loser_id": l,
                         "outcome": match_outcome(getattr(m, "score", ""))})
    return pd.DataFrame(rows, columns=["edition_key", "winner_id", "loser_id", "outcome"])


def fixture_winners(fixtures: pd.DataFrame, results: pd.DataFrame) -> pd.DataFrame:
    """fixture_id -> winner_side (p1/p2) and outcome, for stored fixtures with edition and both
    player ids. A pair that meets twice in one edition gets nothing (ambiguous)."""
    pair = lambda a, b: "|".join(sorted((a, b)))
    res = results.assign(pair=[pair(w, l) for w, l in zip(results["winner_id"], results["loser_id"])])
    if "outcome" not in res:
        res["outcome"] = "unknown"
    res = res.drop_duplicates(["edition_key", "pair"], keep=False).set_index(["edition_key", "pair"])
    out = []
    for f in fixtures.itertuples():
        if not (f.edition_key and f.player1_id and f.player2_id):
            continue
        key = (f.edition_key, pair(f.player1_id, f.player2_id))
        if key in res.index:
            r = res.loc[key]
            out.append({"fixture_id": f.fixture_id, "winner_side": "p1" if r["winner_id"] == f.player1_id else "p2",
                        "outcome": r["outcome"]})
    return pd.DataFrame(out, columns=["fixture_id", "winner_side", "outcome"])


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


INPLAY_DIR = Path("market_history") / "inplay_calls"
INPLAY_COLUMNS = ["fixture_id", "cutoff_utc", "call", "books", "source"]
WIN_PRICE, LOSE_PRICE = 1.10, 5.0          # a book calls the match: winner at or below, loser at or above


def inplay_call(payload: dict, cutoff: pd.Timestamp) -> tuple[str, dict]:
    """The middle rule: each book's last active in-play moneyline quotes (market 121; outcome
    121 = participant 1, 122 = participant 2); the books that call agree and none is unclear.
    Returns ("p1" | "p2" | "none", {book: p1/p2/unclear/incomplete})."""
    last: dict[tuple, tuple] = {}
    for r in flatten_history(payload or {}):
        if r["market_id"] != "121" or r["outcome_id"] not in ("121", "122") or r["active"] is False:
            continue
        t = pd.Timestamp(r["created_at"])
        if t > cutoff and ((r["bookmaker"], r["outcome_id"]) not in last or t > last[(r["bookmaker"], r["outcome_id"])][0]):
            last[(r["bookmaker"], r["outcome_id"])] = (t, r["price_decimal"])
    books = {}
    for book in {b for b, _ in last}:
        p1, p2 = last.get((book, "121"), (None, None))[1], last.get((book, "122"), (None, None))[1]
        if p1 is None or p2 is None:
            books[book] = "incomplete"
        elif p1 <= WIN_PRICE and p2 >= LOSE_PRICE:
            books[book] = "p1"
        elif p2 <= WIN_PRICE and p1 >= LOSE_PRICE:
            books[book] = "p2"
        else:
            books[book] = "unclear"
    called = {c for c in books.values() if c in ("p1", "p2")}
    return (called.pop() if len(called) == 1 and "unclear" not in books.values() else "none"), books


def inplay_record(fixture_id: str, cutoff: pd.Timestamp, payload: dict, source: str) -> dict:
    call, books = inplay_call(payload, cutoff)
    return {"fixture_id": fixture_id, "cutoff_utc": pd.Timestamp(cutoff).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "call": call, "books": json.dumps(books, sort_keys=True), "source": source}


def append_inplay(records: list[dict], base: str | Path = ".") -> int:
    """Append-only per month of the start: the first call stored for a fixture stands."""
    from v5_market_history import _append
    df = pd.DataFrame(records, columns=INPLAY_COLUMNS)
    added = 0
    for month, chunk in df.groupby(df["cutoff_utc"].str[:7]):
        added += _append(chunk, Path(base) / INPLAY_DIR / f"{month}.csv", INPLAY_COLUMNS, ["fixture_id"])
    return added


def inplay_winners(base: str | Path = ".") -> pd.DataFrame:
    paths = sorted((Path(base) / INPLAY_DIR).glob("*.csv"))
    if not paths:
        return pd.DataFrame(columns=["fixture_id", "winner_side"])
    calls = pd.concat([pd.read_csv(p, dtype=str, keep_default_na=False) for p in paths]).drop_duplicates("fixture_id")
    calls = calls[calls["call"].isin(["p1", "p2"])]
    return calls.rename(columns={"call": "winner_side"})[["fixture_id", "winner_side"]]


def combine_winners(tml: pd.DataFrame, kalshi: pd.DataFrame, inplay: pd.DataFrame | None = None) -> pd.DataFrame:
    """TennisMyLife first; then Kalshi; then the in-play call. Each row says its source, how the
    match ended (known only from TennisMyLife) and whether it is void for measurement."""
    tml = tml if "outcome" in tml else tml.assign(outcome="unknown")
    parts = [tml.assign(result_source="tennismylife")]
    have = set(tml["fixture_id"])
    for name, frame in (("kalshi", kalshi), ("inplay", inplay)):
        if frame is None or frame.empty:
            continue
        extra = frame[~frame["fixture_id"].isin(have)].assign(result_source=name, outcome="unknown")
        have |= set(extra["fixture_id"])
        parts.append(extra)
    out = pd.concat(parts, ignore_index=True)
    out["void_for_measurement"] = out["outcome"].isin(VOID_OUTCOMES)
    return out[RESULT_COLUMNS]


def load_fixture_winners(fixtures: pd.DataFrame, base: str | Path = ".", *,
                         sources=("tennismylife", "kalshi", "inplay")) -> pd.DataFrame:
    base = Path(base)
    tml = pd.DataFrame(columns=["fixture_id", "winner_side", "outcome"])
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
    inp = pd.DataFrame(columns=["fixture_id", "winner_side"])
    if "inplay" in sources:
        inp = inplay_winners(base)
        inp = inp[inp["fixture_id"].isin(fixtures["fixture_id"])]
    return combine_winners(tml, kal, inp)
