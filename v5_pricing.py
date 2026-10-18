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

import numpy as np
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
    setting: str = ""
    best_of: int | None = None
    stage: str = "unknown"
    stage_source: str = ""
    player1_id: str = ""
    player2_id: str = ""
    rated_matches: tuple = ()
    model_p1: float | None = None
    official_eligible: bool = False
    books: list = field(default_factory=list)      # one dict per book and side
    rating_vectors: dict = field(default_factory=dict)   # player_id -> the rating vector used (saved for the app)

    def as_row(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k not in ("books", "rating_vectors")}
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
    out = Price(fid, "no_price", "OK", r.edition_key, r.tour, r.tour_family, r.surface, r.setting, r.best_of, stage,
                stage_source, r.player1.player_id or "", r.player2.player_id or "")
    fx = resolver.fixtures.loc[fid]
    fixture = {"start_time_utc": fx.get("start_time_utc"), "true_start_time_utc": fx.get("true_start_time_utc")}
    if not (r.player1.player_id and r.player2.player_id):
        out.reason = "NO_HISTORY"
    else:
        event = events.get(r.edition_key, r.edition_key)
        start = pd.Timestamp(fixture["start_time_utc"])
        state = live_elo.state(event, week=tennis_week(start))
        for pid in (r.player1.player_id, r.player2.player_id):
            vec = state(pid)
            if vec is not None:
                out.rating_vectors[pid] = [float(x) for x in vec]
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


# ---------------------------------------------------------------- shared by the daily batch and the override run
MODEL_VERSION = "baseline_elo_v1"
STAGE_LOOKBACK_DAYS = 21


@dataclass
class PricingContext:
    """Everything price_fixture needs, loaded once per run."""
    resolver: object
    live_elo: be.LiveElo
    events: dict
    stages: dict

    @classmethod
    def from_repo(cls, base=".", *, now=None, matches: pd.DataFrame | None = None) -> "PricingContext":
        from pathlib import Path

        from v5_fixture_resolution import FixtureResolver
        from v5_fixture_stage import edition_levels, fixture_stages
        from v5_market_results import load_fixture_winners
        from v5_tournament_identity import load_master_schedule

        base = Path(base)
        now = pd.Timestamp(now or pd.Timestamp.now(tz="UTC"))
        matches = be.load_matches(base) if matches is None else matches
        resolver = FixtureResolver.from_repo(base)
        live = be.run(matches, be.PRODUCTION_PARAMS, live=True)
        crosswalk = pd.read_csv(base / "context_registry" / "master_schedule" / "crosswalk_tennismylife.csv",
                                dtype=str, keep_default_na=False)
        # Stage labels for the fixtures around now (earlier days of each edition count).
        reg = resolver.fixtures.reset_index()
        start = pd.to_datetime(reg["start_time_utc"], utc=True, errors="coerce")
        recent = reg[(start >= now - pd.Timedelta(days=STAGE_LOOKBACK_DAYS)) & (start <= now + pd.Timedelta(days=8))].copy()
        ids = pd.DataFrame([resolver.identify(f) for f in recent["fixture_id"]], index=recent.index)
        recent[["edition_key", "player1_id", "player2_id"]] = ids[["edition_key", "player1_id", "player2_id"]]
        schedules = [load_master_schedule(p)[0] for p in sorted((base / "context_registry" / "master_schedule").glob("master_schedule_*.csv"))]
        levels = edition_levels(pd.concat(schedules)) if schedules else {}
        winners = load_fixture_winners(recent.assign(cutoff_utc=recent["start_time_utc"]), base)
        st = fixture_stages(recent, None, levels, winners)
        stages = {r.fixture_id: (r.stage, r.stage_source) for r in st.itertuples()}
        return cls(resolver, live, edition_events(matches, crosswalk), stages)

    @classmethod
    def from_board(cls, base=".") -> "PricingContext":
        """The app's context: the batch's saved rating states and stage labels, no history files."""
        from pathlib import Path

        from v5_fixture_resolution import FixtureResolver

        base = Path(base)
        states = pd.read_csv(base / RATING_STATES_PATH, dtype={"edition_key": str, "player_id": str})
        board = pd.read_csv(base / "v5_daily_ready" / "latest_board.csv", dtype={"fixture_id": str}, low_memory=False)
        first = board.drop_duplicates("fixture_id")
        stages = {r.fixture_id: (r.stage, r.stage_source) for r in first.itertuples()} if "stage" in first else {}
        return cls(FixtureResolver.from_repo(base), StoredElo(states), {}, stages)

    def with_overrides(self, rows: list[dict]) -> "PricingContext":
        """A copy whose resolver applies extra edition overrides (the app's edits) after the
        stored ones, so the edits win."""
        import copy

        resolver = copy.copy(self.resolver)
        resolver.overrides = pd.concat([self.resolver.overrides, pd.DataFrame(rows)], ignore_index=True)
        return PricingContext(resolver, self.live_elo, self.events, self.stages)

    def price(self, fixture_id, **kw) -> Price:
        return price_fixture(fixture_id, resolver=self.resolver, live_elo=self.live_elo, events=self.events,
                             stages=self.stages, **kw)


RATING_STATES_PATH = "v5_daily_ready/rating_states.csv"
RATING_COLUMNS = ["edition_key", "player_id", "overall", "hard", "clay", "grass", "n", "n_hard", "n_clay", "n_grass"]


class StoredElo:
    """The ratings the daily batch priced each edition's players from (rating_states.csv),
    for the app, which has no history files: the same state, so the same price."""

    def __init__(self, states: pd.DataFrame, params: be.EloParams = be.PRODUCTION_PARAMS):
        self.params = params
        self.by_edition: dict[str, dict] = {}
        for r in states.itertuples(index=False):
            self.by_edition.setdefault(r.edition_key, {})[r.player_id] = np.array(
                [r.overall, r.hard, r.clay, r.grass, r.n, r.n_hard, r.n_clay, r.n_grass], dtype=float)

    def state(self, event, week=None):
        return self.by_edition.get(event, {}).get


def rating_state_rows(prices: list["Price"]) -> pd.DataFrame:
    rows = [[p.edition_key, pid, *vec] for p in prices for pid, vec in p.rating_vectors.items()]
    return pd.DataFrame(rows, columns=RATING_COLUMNS).drop_duplicates(["edition_key", "player_id"])


def _fair_american(p: float) -> float:
    return round(-100 * p / (1 - p)) if p >= 0.5 else round(100 * (1 - p) / p)


def board_rows(feed_rows: pd.DataFrame, price: Price, *, frozen_at: str) -> pd.DataFrame:
    """The board rows for one fixture's market rows (the feed's own columns kept).

    Only the moneyline gets a model probability (the baseline gives the match winner; set
    and game scores are not modelled until a score model passes its own gate, user decision
    2026-10-18). A selection is player 1 or 2 by the feed's own names. Edge, EV and signal
    are filled in by repricing from the latest prices."""
    out = feed_rows.copy()
    p1 = price.model_p1
    sel = out["selection"].astype(str)
    is_ml = out["market_group"].astype(str) == "moneyline"
    side_p = pd.Series(float("nan"), index=out.index)
    if p1 is not None:
        side_p[is_ml & (sel == out["player1"].astype(str))] = p1
        side_p[is_ml & (sel == out["player2"].astype(str))] = 1 - p1
    out["model_probability"] = side_p
    out["model_win_probability"] = side_p
    out["model_push_probability"] = side_p.where(side_p.isna(), 0.0)
    out["model_loss_probability"] = 1 - side_p
    out["model_fair_american"] = [None if pd.isna(p) else _fair_american(p) for p in side_p]
    out["full_context_probability_p1"] = p1        # the frozen P(player 1) column the forecast ledger keys on
    out["model_version"] = MODEL_VERSION
    out["price_status"] = price.status
    out["price_reason"] = price.reason
    out["no_price_reason"] = [price.reason if pd.isna(p) else "" for p in side_p]
    out.loc[~is_ml & side_p.isna(), "no_price_reason"] = "NOT_MODELLED"
    for k in ("edition_key", "tour", "tour_family", "surface", "setting", "best_of", "stage", "stage_source",
              "player1_id", "player2_id", "official_eligible"):
        out[k if k != "tour" else "tour_v5"] = getattr(price, k)
    out["surface_source"] = "master_schedule"
    out["rated_matches"] = "|".join(str(n) for n in price.rated_matches)
    out["resolved_player1"] = out["player1"]
    out["resolved_player2"] = out["player2"]
    out["frozen_at_utc"] = frozen_at
    out["result_status"] = "OPEN"
    out["settled_result"] = ""
    out["profit_units"] = float("nan")
    return out
