"""Resolve an OddsPapi fixture to its tournament edition and its two players.

The data layer's single answer to "what is this match?": which edition (with every court
attribute from the master schedule, plus the user's overrides) and which two players
(our own player ids). Built on the stored crosswalks and alias tables; it never matches
names on the fly. Anything it cannot resolve raises FixtureResolutionError with a code,
and gets no price (CLAUDE.md: fail closed).

Specs: docs/superpowers/specs/2026-10-12-tournament-identity-design.md (§2.2–2.6) and
docs/superpowers/specs/2026-10-13-player-identity-design.md (§2.4).
Rebuild plan: Step 2 builds this; Step 4's single pricing function is its first caller and
retires the old lookups (v5_tournament_authority, v5_master_schedule_context,
v5_tournament_context_registry, v5_player_identity) together with the old engine.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from v5_player_registry import (
    ODDS_ALIAS_COLUMNS, TML_ALIAS_COLUMNS, USABLE_STATUSES as PLAYER_USABLE, load_table, player_key,
)
from v5_tournament_identity import (
    ODDSPAPI_GAP_DAYS, enrich_locations, load_countries, load_crosswalk, load_master_schedule, resolve_edition,
)

OVERRIDE_COLUMNS = ["edition_key", "field", "value", "set_on", "note"]
# Edition fields a person may override in the app (spec §2.6). Ball and CPI are optional
# sheet columns the user fills in later.
OVERRIDABLE = {"surface", "setting", "altitude_m", "time_zone", "latitude", "longitude", "best_of"}
SURFACES = {"Hard", "Clay", "Grass"}
SETTINGS = {"Indoor", "Outdoor"}
TEAM_EVENT_WORDS = ("united cup", "laver cup", "davis cup", "billie jean king cup", "bjk cup", "hopman cup")
NO_HISTORY_STATUSES = {"no_history", "rejected"}


class FixtureResolutionError(ValueError):
    """code: FIXTURE_UNKNOWN, NO_SCHEDULE_FOR_YEAR, TOURNAMENT_UNRESOLVED, EDITION_MISSING,
    TEAM_EVENT_NOT_PRICED, SURFACE_MISSING, PLACEHOLDER, PLAYER_UNRESOLVED, SAME_PLAYER."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code, self.detail = code, detail


@dataclass
class ResolvedPlayer:
    participant_id: str
    feed_name: str
    player_id: str | None        # None: no history in our data (never a rating)
    status: str                  # confirmed / auto / user, or no_history / rejected
    rating_name: str | None      # the name today's (name-keyed) ratings use; None if absent

    @property
    def has_history(self) -> bool:
        return self.player_id is not None and self.rating_name is not None


@dataclass
class ResolvedFixture:
    fixture_id: str
    edition_key: str
    tour: str                    # MEN or WTA (the ratings pool)
    tour_family: str             # ATP, CHALLENGER, WTA, WTA125
    tournament_name: str
    surface: str
    setting: str
    best_of: int
    edition: dict                # every edition attribute after overrides
    sources: dict = field(default_factory=dict)   # attribute -> schedule / geocoded / override
    player1: ResolvedPlayer | None = None
    player2: ResolvedPlayer | None = None

    @property
    def priceable(self) -> bool:
        """Both players have history. A no-history player may be shown, never recommended."""
        return bool(self.player1 and self.player2 and self.player1.has_history and self.player2.has_history)


class FixtureResolver:
    """Loads the stored tables once; resolve() is then a pure lookup."""

    def __init__(self, *, fixtures: pd.DataFrame, editions_by_year: dict[int, pd.DataFrame],
                 crosswalk_oddspapi: pd.DataFrame, overrides: pd.DataFrame, alias_oddspapi: pd.DataFrame,
                 alias_tennismylife: pd.DataFrame, ratings_by_tour: dict[str, pd.DataFrame] | None = None):
        self.fixtures = fixtures.assign(fixture_id=fixtures["fixture_id"].astype(str)).drop_duplicates("fixture_id", keep="last").set_index("fixture_id")
        self.editions_by_year = {y: e.set_index("edition_key", drop=False) for y, e in editions_by_year.items()}
        self.crosswalk = crosswalk_oddspapi
        self.overrides = overrides
        self.alias_odds = alias_oddspapi.assign(participant_id=alias_oddspapi["participant_id"].astype(str)).set_index("participant_id")
        self.names_of = alias_tennismylife.groupby("player_id")["names"].apply(
            lambda s: [n for v in s for n in str(v).split(" | ") if n]).to_dict()
        self.rating_names = {}
        for tour, r in (ratings_by_tour or {}).items():
            matches = pd.to_numeric(r.get("elo_matches", pd.Series(0, index=r.index)), errors="coerce").fillna(0)
            best = r.assign(_m=matches).groupby("player")["_m"].max()
            idx = {}
            for name, m in best.items():
                idx.setdefault(player_key(name), []).append((m, name))
            self.rating_names[tour] = idx

    @classmethod
    def from_repo(cls, base: str | Path = ".", *, years=None, ratings_by_tour=None) -> "FixtureResolver":
        base = Path(base)
        ms = base / "context_registry" / "master_schedule"
        cache = load_table(ms / "geocode_cache.csv", ["location_key", "results_json"])
        aliases = load_table(ms / "location_aliases.csv", ["city", "country_iso2", "query", "match_name", "region", "note"])
        countries = load_countries(base / "context_registry" / "countries.csv")
        editions = {}
        for sheet in sorted(ms.glob("master_schedule_*.csv")):
            year = int(sheet.stem.rsplit("_", 1)[1])
            if years is None or year in years:
                e, _ = load_master_schedule(sheet)
                editions[year], _ = enrich_locations(e, cache, countries, aliases=aliases)
        players = base / "context_registry" / "players"
        return cls(
            fixtures=pd.read_csv(base / "oddspapi_registry" / "fixtures.csv", low_memory=False),
            editions_by_year=editions,
            crosswalk_oddspapi=load_crosswalk(ms / "crosswalk_oddspapi.csv"),
            overrides=load_table(ms / "overrides.csv", OVERRIDE_COLUMNS),
            alias_oddspapi=load_table(players / "alias_oddspapi.csv", ODDS_ALIAS_COLUMNS),
            alias_tennismylife=load_table(players / "alias_tennismylife.csv", TML_ALIAS_COLUMNS),
            ratings_by_tour=ratings_by_tour,
        )

    # ------------------------------------------------------------------ tournament
    def _edition(self, fx: pd.Series, start: pd.Timestamp) -> pd.Series:
        year = int(start.year)
        if year not in self.editions_by_year:
            raise FixtureResolutionError("NO_SCHEDULE_FOR_YEAR", f"no master_schedule_{year}.csv")
        key = resolve_edition(self.crosswalk, fx["tournament_id"], start, gap_days=ODDSPAPI_GAP_DAYS)
        if not key:
            raise FixtureResolutionError("TOURNAMENT_UNRESOLVED", f"{fx['tournament_name']} (OddsPapi {fx['tournament_id']}) on {start.date()}")
        eds = self.editions_by_year[year]
        if key not in eds.index:
            raise FixtureResolutionError("EDITION_MISSING", f"{key} is no longer in the master schedule")
        return eds.loc[key]

    def _apply_overrides(self, edition: pd.Series) -> tuple[dict, dict]:
        e = edition.to_dict()
        sources = {k: "schedule" for k in e}
        for k in ("latitude", "longitude", "altitude_m", "time_zone"):
            sources[k] = "sheet" if e.get("location_source") == "sheet" else e.get("location_source") or "missing"
        rows = self.overrides[self.overrides["edition_key"] == e["edition_key"]]
        for r in rows.itertuples():
            if r.field in OVERRIDABLE:
                e[r.field] = r.value
                sources[r.field] = "override"
        return e, sources

    # ------------------------------------------------------------------ players
    def _player(self, participant_id, feed_name: str, tour: str) -> ResolvedPlayer:
        from v5_player_registry import is_placeholder_participant
        if is_placeholder_participant(feed_name):
            raise FixtureResolutionError("PLACEHOLDER", f"{feed_name} is a draw slot, not a player")
        pid = str(int(participant_id)) if pd.notna(participant_id) else ""
        if pid not in self.alias_odds.index:
            raise FixtureResolutionError("PLAYER_UNRESOLVED", f"{feed_name} (OddsPapi {pid}) is not in the player tables yet")
        row = self.alias_odds.loc[pid]
        status = row["status"]
        if status in NO_HISTORY_STATUSES:
            return ResolvedPlayer(pid, feed_name, None, status, None)
        if status not in PLAYER_USABLE or not row["player_id"]:
            raise FixtureResolutionError("PLAYER_UNRESOLVED", f"{feed_name} (OddsPapi {pid}) is held for review")
        return ResolvedPlayer(pid, feed_name, row["player_id"], status, self._rating_name(row["player_id"], tour))

    def _rating_name(self, player_id: str, tour: str) -> str | None:
        """Today's ratings are keyed by name, and a player can sit under two spellings
        (rebuild plan Step 4 moves ratings to player_id). Use the spelling with the most
        rated matches."""
        idx = self.rating_names.get(tour, {})
        found = [hit for n in self.names_of.get(player_id, []) for hit in idx.get(player_key(n), [])]
        return max(found)[1] if found else None

    # ------------------------------------------------------------------ fixture
    def resolve(self, fixture_id) -> ResolvedFixture:
        fid = str(fixture_id)
        if fid not in self.fixtures.index:
            raise FixtureResolutionError("FIXTURE_UNKNOWN", f"fixture {fid} is not in oddspapi_registry/fixtures.csv")
        fx = self.fixtures.loc[fid]
        start = pd.Timestamp(fx["start_time_utc"])
        start = start.tz_localize("UTC") if start.tzinfo is None else start.tz_convert("UTC")
        edition, sources = self._apply_overrides(self._edition(fx, start))
        name = f"{edition['tournament_name']} {edition.get('circuit_tour', '')}".lower()
        if any(w in name for w in TEAM_EVENT_WORDS):
            raise FixtureResolutionError("TEAM_EVENT_NOT_PRICED", edition["tournament_name"])
        surface = str(edition.get("surface") or "").title()
        if surface not in SURFACES:
            raise FixtureResolutionError("SURFACE_MISSING", f"{edition['edition_key']} has no surface")
        setting = str(edition.get("setting") or "").title()
        family = edition["tour_family"]
        tour = "WTA" if family in {"WTA", "WTA125"} else "MEN"
        best_of = edition.get("best_of")
        if sources.get("best_of") != "override":
            # Men's Grand Slam main draw is best of five; its qualifying runs before the edition starts.
            slam = str(edition.get("circuit_tour") or "").strip().lower() == "grand slam"
            best_of = 5 if (tour == "MEN" and slam and start.date() >= pd.Timestamp(edition["start_date"]).date()) else 3
        p1 = self._player(fx["participant1_id"], str(fx["participant1_name"]), tour)
        p2 = self._player(fx["participant2_id"], str(fx["participant2_name"]), tour)
        if p1.player_id and p1.player_id == p2.player_id:
            raise FixtureResolutionError("SAME_PLAYER", f"{p1.feed_name} and {p2.feed_name} are one player ({p1.player_id})")
        return ResolvedFixture(fid, edition["edition_key"], tour, family, edition["tournament_name"], surface,
                               setting if setting in SETTINGS else "", int(best_of), edition, sources, p1, p2)
