"""Leak-free surface Elo keyed by our player_id (rebuild plan Step 4, baseline model).

Replaces the Elo in build_v5_states.py, which updates in tourney_date + file order (a match
can see later rounds of the same event) and keys players by name. Here:

- Matches come from v5_fatigue_features.load_repo_matches (the files production reads,
  de-duplicated, reused tourney ids split), and players are keyed by our player_id
  (context_registry/players/alias_tennismylife.csv); a TennisMyLife id with no registry row
  (players who stopped before 2026) is kept as "tml:<tour>:<id>", the same person.
- Ordering follows v5_fatigue_features: inside an event, rounds in (stage, round) order and
  the same round is concurrent (all its matches are priced before any of them updates);
  another event's results count only once its last week is before this event's first
  week. A match with an unknown round sees only the event's starting ratings and informs
  nothing in its event.
- Walkovers neither get a price nor move a rating.
- One code path: `run` prices every historical match from the state the rules allow, and
  `rating_state(..., stop=...)` returns that same state for a fixture to be priced live; the
  parity test checks they agree.

Rating: overall and per-surface (Hard, Clay, Grass; Carpet and unknown count as Hard),
blended (1 - blend) * overall + blend * surface. K shrinks with experience
(k * 250 / (n + 5) ** 0.4, n = that rating's matches so far). A player's first match uses
the newcomer rating (every player starts there, so its value cancels out: Elo depends only
on differences). The match count travels with every rating, so the pricing function can
refuse thin histories (fail closed) instead of trusting a newcomer number.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from v5_fatigue_features import event_table, load_repo_matches
from v5_player_registry import USABLE_STATUSES, normalize_tml_id

SURFACES = ("Hard", "Clay", "Grass")
REGISTRY_TML = Path("context_registry") / "players" / "alias_tennismylife.csv"
TOUR_CODE = {"MEN": "M", "WTA": "W"}
LIVE_SNAPSHOT_WEEKS = 4      # events ending this close to the newest week keep a snapshot for live pricing


@dataclass(frozen=True)
class EloParams:
    k: float = 1.0                 # scale on 250 / (n + 5) ** 0.4
    blend: float = 0.5             # weight of the surface rating
    newcomer: float = 1500.0       # first-match rating
    shape: float = 0.4

    def k_for(self, n: float) -> float:
        return self.k * 250.0 / (n + 5.0) ** self.shape


# Chosen on 2025 log loss (docs/experiments/2026-10-17-baseline-elo.md); production uses these.
PRODUCTION_PARAMS = EloParams(k=0.6, blend=0.2)


def surface_of(value) -> str:
    s = "" if pd.isna(value) else str(value).strip().title()
    return s if s in SURFACES else "Hard"


def player_keys(matches: pd.DataFrame, root: str | Path = ".") -> pd.DataFrame:
    """Adds winner_key / loser_key: our player_id where the registry has a usable link,
    else "tml:<tour>:<id>"."""
    path = Path(root) / REGISTRY_TML
    alias = pd.read_csv(path, dtype=str, keep_default_na=False) if path.exists() else pd.DataFrame(
        columns=["tour", "tml_id", "player_id", "status"])
    alias = alias[alias["status"].isin(USABLE_STATUSES) & (alias["player_id"] != "")]
    link = {(t, normalize_tml_id(i)): p for t, i, p in zip(alias["tour"], alias["tml_id"], alias["player_id"])}
    out = matches.copy()
    for side in ("winner", "loser"):
        code = out["tour"].map(TOUR_CODE)
        ids = out[f"{side}_id"].map(normalize_tml_id)
        out[f"{side}_key"] = [link.get((c, i)) or f"tml:{c}:{i}" for c, i in zip(code, ids)]
    return out


def load_matches(root: str | Path = ".") -> pd.DataFrame:
    return player_keys(load_repo_matches(str(root)), root)


def probability(ra: np.ndarray, rb: np.ndarray, surface: str, params: EloParams) -> float:
    """P(a beats b) from two rating vectors [overall, Hard, Clay, Grass, n_overall, n_Hard, n_Clay, n_Grass]."""
    i = 1 + SURFACES.index(surface)
    a = (1 - params.blend) * ra[0] + params.blend * ra[i]
    b = (1 - params.blend) * rb[0] + params.blend * rb[i]
    return 1.0 / (1.0 + 10.0 ** ((b - a) / 400.0))


def _fresh(params: EloParams) -> np.ndarray:
    return np.array([params.newcomer] * 4 + [0.0] * 4)


def _update(rw: np.ndarray, rl: np.ndarray, p_w: float, surface: str, params: EloParams) -> tuple[np.ndarray, np.ndarray]:
    i = 1 + SURFACES.index(surface)
    dw, dl = np.zeros(8), np.zeros(8)
    for d, r, sign in ((dw, rw, 1.0), (dl, rl, -1.0)):
        d[0] = sign * params.k_for(r[4]) * (1 - p_w)
        d[i] = sign * params.k_for(r[4 + i]) * (1 - p_w)
        d[4] = d[4 + i] = 1.0
    return dw, dl


def _events(matches: pd.DataFrame) -> tuple[list, dict]:
    ev = event_table(matches)
    order = sorted(ev.index, key=lambda e: (ev.at[e, "first_week"], e[0], e[1]))
    return order, ev[["first_week", "last_week"]].to_dict("index")


def run(matches: pd.DataFrame, params: EloParams = EloParams(), stop: tuple | None = None, live: bool = False):
    """Price every match (walkovers skipped) from the state the ordering rules allow.

    Returns a DataFrame (one row per priced match: key, tour, tid, date, winner_key,
    loser_key, surface, p_winner, n_winner, n_loser). With `stop=((tour, tid), stage, rank)`
    returns instead (ratings, event_local): the committed ratings and the event's own
    updates from rounds strictly before (stage, rank) - the state a fixture in that event
    and round is priced from (`rating_state`). With `live=True` returns a LiveElo: the state
    after every result in the history, for fixtures not played yet."""
    order, weeks = _events(matches)
    recent = max((w["last_week"] for w in weeks.values()), default=0) - LIVE_SNAPSHOT_WEEKS
    snapshots: dict[tuple, tuple] = {}
    by_event = {e: g for e, g in matches.groupby(["tour", "tid"], sort=False)}
    ratings: dict[str, np.ndarray] = {}
    pending: list[tuple[float, dict]] = []      # (last_week, deltas) of events not yet visible
    rows = []

    def get(store, key):
        return store[key] if key in store else ratings.get(key, _fresh(params))

    for e in order:
        first = weeks[e]["first_week"]
        still = []
        for last, deltas in sorted(pending, key=lambda x: x[0]):
            if last < first:
                for key, d in deltas.items():
                    ratings[key] = ratings.get(key, _fresh(params)) + d
            else:
                still.append((last, deltas))
        pending = still
        g = by_event[e]
        g = g[~g["walkover"].astype(bool)]
        local: dict[str, np.ndarray] = {}
        start: dict[str, np.ndarray] = {}
        unknown_deltas: dict[str, np.ndarray] = {}
        known = g[g["rank"].notna()]
        groups = sorted(known.groupby(["stage", "rank"], sort=False), key=lambda kv: kv[0])
        for (stage, rank), grp in groups:
            if stop is not None and e == stop[0] and (stage, rank) >= (stop[1], stop[2]):
                return ratings, local
            updates = []
            for m in grp.itertuples():
                w, l = m.winner_key, m.loser_key
                for k in (w, l):
                    start.setdefault(k, get({}, k).copy())
                rw, rl = get(local, w), get(local, l)
                s = surface_of(m.surface)
                p = probability(rw, rl, s, params)
                rows.append((m.key, m.tour, m.tid, m.date, w, l, s, p, rw[4], rl[4]))
                updates.append((w, l, rw, rl, p, s))
            for w, l, rw, rl, p, s in updates:                 # same round: concurrent
                dw, dl = _update(rw, rl, p, s, params)
                local[w] = get(local, w) + dw
                local[l] = get(local, l) + dl
        if stop is not None and e == stop[0]:
            return ratings, local
        for m in g[g["rank"].isna()].itertuples():               # unknown round: event start only
            w, l = m.winner_key, m.loser_key
            rw, rl = ratings.get(w, _fresh(params)), ratings.get(l, _fresh(params))
            s = surface_of(m.surface)
            p = probability(rw, rl, s, params)
            rows.append((m.key, m.tour, m.tid, m.date, w, l, s, p, rw[4], rl[4]))
            dw, dl = _update(rw, rl, p, s, params)
            unknown_deltas[w] = unknown_deltas.get(w, np.zeros(8)) + dw
            unknown_deltas[l] = unknown_deltas.get(l, np.zeros(8)) + dl
        deltas = {k: v - start[k] for k, v in local.items()}
        for k, d in unknown_deltas.items():
            deltas[k] = deltas.get(k, np.zeros(8)) + d
        pending.append((weeks[e]["last_week"], deltas))
        if live and weeks[e]["last_week"] >= recent:
            snapshots[e] = (dict(ratings), dict(local))      # arrays are replaced, never changed
    if live:
        return LiveElo(ratings, pending, snapshots, params)
    if stop is not None:
        raise KeyError(f"event {stop[0]} not in the history")
    return pd.DataFrame(rows, columns=["key", "tour", "tid", "date", "winner_key", "loser_key", "surface",
                                       "p_winner", "n_winner", "n_loser"])


class LiveElo:
    """The ratings a fixture not yet played is priced from, by the same rules as `run`.

    - Its event already has results in the history (a later round): the ratings committed
      when the event began plus the event's own results so far. Each player plays once per
      round, so the two players' ratings are the ones the history would use for that round.
    - Its event has none yet: every event whose last week is before the fixture's week.
    Built once per run (`run(matches, params, live=True)`), then a pure lookup."""

    def __init__(self, committed: dict, pending: list, snapshots: dict, params: EloParams):
        self.committed, self.pending, self.snapshots, self.params = committed, pending, snapshots, params

    def state(self, event: tuple | None = None, week: float | None = None):
        if event is not None and event in self.snapshots:
            ratings, local = self.snapshots[event]
            return lambda key: local[key] if key in local else ratings.get(key)
        if week is None:
            raise ValueError("an event with no results needs the fixture's tennis week")
        ratings = dict(self.committed)
        for last, deltas in self.pending:
            if last < week:
                for key, d in deltas.items():
                    ratings[key] = ratings.get(key, _fresh(self.params)) + d
        return ratings.get


def rating_state(matches: pd.DataFrame, event: tuple, stage: int, rank: float, params: EloParams = EloParams()):
    """The ratings a fixture in `event` at (stage, rank) is priced from (same loop as `run`)."""
    ratings, local = run(matches, params, stop=(event, stage, rank))
    return lambda key: local[key] if key in local else ratings.get(key)


def fixture_probability(state, key_a: str, key_b: str, surface: str, params: EloParams = EloParams()) -> dict:
    """P(a beats b) for a fixture, with each player's match count. Fails closed: a player with
    no rating raises (the pricing function decides how much history is enough)."""
    ra, rb = state(key_a), state(key_b)
    missing = [k for k, r in ((key_a, ra), (key_b, rb)) if r is None]
    if missing:
        raise KeyError(f"no rating for {missing}")
    s = surface_of(surface)
    return {"p": probability(ra, rb, s, params), "n_a": int(ra[4]), "n_b": int(rb[4]), "surface": s}
