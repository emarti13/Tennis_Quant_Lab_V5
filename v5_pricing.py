"""One pricing function for a fixture (rebuild plan Step 4).

`price_fixture` is the single answer to "what is this match worth, and is any price on offer
worth taking?". The daily batch and the app's override run both call it (Step 4g switches
them over); nothing else computes a model probability or an edge.

For one OddsPapi fixture:
1. Resolve it (v5_fixture_resolution): edition, surface, best-of and our two player ids,
   with the user's overrides applied. Any failure is a no-price with the resolver's code.
2. Model: the baseline Elo (v5_baseline_elo) from the state the history allows for this
   event and week. Both players need at least MIN_RATED_MATCHES rated matches (user
   decision 2026-10-18, docs/experiments/2026-10-17-baseline-elo.md); below that, no
   model price ("THIN_HISTORY").
3. Stage label (v5_fixture_stage): qualifying fixtures are priced but not eligible for
   official recommendations until the model is measured on qualifying.
4. Market: each book's live quotes for the moneyline, kept only if `is_actionable` (not
   started, fetched within 60 minutes, not withdrawn, timestamps present). Pinnacle is
   information (its fair price is shown); Bet365, BetRivers, Kalshi, Polymarket and Novig
   are execution. For an execution book, both sides get the cautious edge (v5_devig: the
   least favourable of multiplicative, additive, power and the book's own lam) and the
   expected value at the offered price.

Everything fails closed: an unknown player, an unknown event, a stale quote or a missing
timestamp never becomes a number.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

import v5_baseline_elo as be
from v5_devig import book_lam, cautious_edge, devig, expected_value
from v5_fatigue_features import tennis_week
from v5_fixture_resolution import FixtureResolutionError
from v5_live_prices import is_actionable

MIN_RATED_MATCHES = 18          # user decision 2026-10-18
INFORMATION_BOOKS = {"pinnacle"}
EXECUTION_BOOKS = {"bet365", "betrivers", "kalshi", "polymarket", "novig.us"}
EDITION_WINDOW_DAYS = 3


@dataclass
class Price:
    fixture_id: str
    status: str                       # "priced" or "no_price"
    reason: str                       # "OK" or the first failure code
    edition_key: str = ""
    tour: str = ""
    tour_family: str = ""
    surface: str = ""
    best_of: int | None = None
    stage: str = "unknown"
    stage_source: str = ""
    player1_id: str = ""
    player2_id: str = ""
    rated_matches: tuple = ()
    model_p1: float | None = None
    official_eligible: bool = False
    books: list = field(default_factory=list)      # one dict per book and side

    def as_row(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k != "books"}
        d["rated_matches"] = "|".join(str(n) for n in self.rated_matches)
        return d


def edition_events(matches: pd.DataFrame, crosswalk_tml: pd.DataFrame) -> dict[str, tuple]:
    """edition_key -> (tour, tid) of its TennisMyLife event in the rating history, from the
    stored crosswalk (rows with an edition; reused TennisMyLife ids are split by date)."""
    starts = matches.groupby(["tour", "tid"]).agg(raw=("tourney_id_raw", "first"), first=("date", "min"))
    out = {}
    cw = crosswalk_tml[(crosswalk_tml["edition_key"].astype(str) != "") & (crosswalk_tml["status"] != "rejected")]
    for r in cw.itertuples():
        lo = pd.Timestamp(r.first_date) - pd.Timedelta(days=EDITION_WINDOW_DAYS)
        hi = pd.Timestamp(r.last_date) + pd.Timedelta(days=EDITION_WINDOW_DAYS)
        hit = starts[(starts["raw"].astype(str) == str(r.tournament_id)) & starts["first"].between(lo, hi)]
        if len(hit) == 1:
            out[r.edition_key] = hit.index[0]
    return out


def _book_rows(book: str, quotes: pd.DataFrame, fixture: dict, now, model_p1: float | None) -> list[dict]:
    rows = []
    sides = {}
    for q in quotes.to_dict("records"):
        ok, why = is_actionable(q, fixture, now)
        sides[q["side"]] = (q, ok, why)
    pair_ok = all(s in sides and sides[s][1] for s in ("p1", "p2"))
    prices = [float(sides["p1"][0]["price"]), float(sides["p2"][0]["price"])] if pair_ok else None
    lam = book_lam(book)
    try:
        fair = devig(prices, lam) if prices else None
    except ValueError:                      # an impossible pair of prices: nothing to act on
        fair, pair_ok = None, False
    for i, side in enumerate(("p1", "p2")):
        q, ok, why = sides.get(side, ({}, False, "NO_PRICE"))
        if ok and not pair_ok:
            ok, why = False, "PAIR_NOT_ACTIONABLE"     # de-vig needs both sides on offer and valid
        row = {"book": book, "side": side, "role": "information" if book in INFORMATION_BOOKS else "execution",
               "price": q.get("price"), "fetched_utc": q.get("fetched_utc"), "actionable": ok, "reason": why,
               "fair": round(fair[i], 6) if ok else None, "cautious_edge": None, "expected_value": None}
        if ok and model_p1 is not None and book in EXECUTION_BOOKS:
            p_side = model_p1 if side == "p1" else 1 - model_p1
            row["cautious_edge"] = round(cautious_edge(p_side, prices, i, lam), 6)
            row["expected_value"] = round(expected_value(p_side, prices[i]), 6)
        rows.append(row)
    return rows


def price_fixture(fixture_id, *, resolver, live_elo: be.LiveElo, events: dict[str, tuple],
                  stages: dict[str, tuple] | None = None, quotes: pd.DataFrame | None = None, now=None,
                  min_rated: int = MIN_RATED_MATCHES) -> Price:
    """Price one fixture. `events`: edition_events(); `stages`: fixture_id -> (stage,
    stage_source) from v5_fixture_stage; `quotes`: live quotes (v5_live_prices columns),
    any fixtures; `now`: the time the quotes are judged at (required when quotes are given)."""
    fid = str(fixture_id)
    try:
        r = resolver.resolve(fid)
    except FixtureResolutionError as e:
        return Price(fid, "no_price", e.code)
    stage, stage_source = (stages or {}).get(fid, ("unknown", "not_labelled"))
    out = Price(fid, "no_price", "OK", r.edition_key, r.tour, r.tour_family, r.surface, r.best_of, stage, stage_source,
                r.player1.player_id or "", r.player2.player_id or "")
    fx = resolver.fixtures.loc[fid]
    fixture = {"start_time_utc": fx.get("start_time_utc"), "true_start_time_utc": fx.get("true_start_time_utc")}
    if not (r.player1.player_id and r.player2.player_id):
        out.reason = "NO_HISTORY"
    else:
        event = events.get(r.edition_key)
        start = pd.Timestamp(fixture["start_time_utc"])
        state = live_elo.state(event, week=tennis_week(start))
        try:
            got = be.fixture_probability(state, r.player1.player_id, r.player2.player_id, r.surface, live_elo.params)
        except KeyError:
            out.reason = "NO_RATING"
        else:
            out.rated_matches = (got["n_a"], got["n_b"])
            if min(got["n_a"], got["n_b"]) < min_rated:
                out.reason = "THIN_HISTORY"
            else:
                out.model_p1 = round(got["p"], 6)
                out.status = "priced"
    out.official_eligible = out.status == "priced" and stage == "main"
    if quotes is not None and len(quotes):
        if now is None:
            raise ValueError("quotes need `now` to judge freshness")
        q = quotes[(quotes["fixture_id"].astype(str) == fid) & (quotes["market_group"] == "moneyline")]
        if len(q):
            latest = q[q["fetched_utc"] == q.groupby("bookmaker")["fetched_utc"].transform("max")]
            for book, g in latest.groupby("bookmaker"):
                out.books += _book_rows(book, g, fixture, now, out.model_p1)
    return out
