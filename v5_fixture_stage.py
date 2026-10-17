"""Stage of a fixture: main draw or qualifying (rebuild plan Step 4, user decision 2026-10-17).

OddsPapi lists qualifying and main-draw matches under the same tournament with no round, so
the stage is inferred, and used as a **label, not a filter**: every fixture is priced;
qualifying ones stay out of official recommendations until the model has been measured on
qualifying results (Kalshi settles some from August 2026; TennisMyLife publishes qualifying
for ATP only).

Rule, per fixture, using only what is known before the match:
1. Kalshi's description of the match, when Kalshi lists it ("Qualification Round 1" vs
   "Round Of 32"), decides.
2. Otherwise by the edition's calendar (master schedule start date and level), measured on
   2026 fixtures:
   - Grand Slams: main draw from the day before the listed start (the Sunday), qualifying
     before that;
   - 1000-level events: the day before, the start day and the day after are mixed
     (qualifying runs early in the first week);
   - every other event: only the start day is mixed;
   - before the mixed days: qualifying; after them: main draw.
3. On a mixed day: qualifying if the players already played in this edition (a later
   qualifying round) - at tour level both of them (one who already played is a qualifier
   meeting a direct entrant in the first round), at Challengers and WTA 125 either of them
   (OddsPapi often misses a qualifier's first qualifying match); else main draw if the
   edition already had matches on an earlier day; else unknown.
Measured on January-August 2026 Challenger and WTA fixtures, with TennisMyLife (main draws
only) as the answer: docs/experiments/2026-10-17-fixture-stage.md.
"""
from __future__ import annotations

import re

import pandas as pd

STAGES = ("main", "qualifying", "unknown")
# (first mixed day, last mixed day) relative to the listed start; None: no mixed days.
MIXED_DAYS = {"Grand Slam": None, "WTA 1000": (-1, 1), "ATP Masters 1000": (-1, 1)}
DEFAULT_MIXED_DAYS = (0, 0)
MAIN_FROM = {"Grand Slam": -1}     # with no mixed days: the first main-draw day
LOWER_TIER_PREFIXES = ("ATP Challenger", "WTA 125")
STAGE_COLUMNS = ["fixture_id", "stage", "stage_source"]
_QUALIFYING = re.compile(r"\bqualif", re.I)
_MAIN = re.compile(r"\b(round of \d+|first round|second round|third round|fourth round|quarterfinal|semifinal|final)\b", re.I)


def kalshi_round(rules_primary: str) -> str | None:
    """'qualifying', 'main' or None from a Kalshi market's rules text."""
    text = str(rules_primary or "")
    if _QUALIFYING.search(text):
        return "qualifying"
    if _MAIN.search(text):
        return "main"
    return None


def edition_levels(schedule: pd.DataFrame) -> dict[str, str]:
    """edition_key -> circuit level (master schedule `circuit_tour`)."""
    return dict(zip(schedule["edition_key"], schedule["circuit_tour"]))


def fixture_stages(fixtures: pd.DataFrame, kalshi: pd.DataFrame | None = None,
                   levels: dict[str, str] | None = None) -> pd.DataFrame:
    """fixtures: fixture_id, edition_key, start_time_utc, participant1_id, participant2_id.
    kalshi: optional fixture_id, rules_primary (one or more markets per fixture).
    levels: edition_key -> circuit level (edition_levels); unknown levels use the default."""
    levels = levels or {}
    f = fixtures[fixtures["edition_key"].astype(str) != ""].copy()
    if f.empty:
        return pd.DataFrame(columns=STAGE_COLUMNS)
    f["start"] = pd.to_datetime(f["start_time_utc"], utc=True, errors="coerce")
    f["edition_start"] = pd.to_datetime(f["edition_key"].str.split("|").str[1], errors="coerce")
    f["day"] = (f["start"].dt.tz_localize(None).dt.normalize() - f["edition_start"]).dt.days
    f = f.sort_values(["start", "fixture_id"])
    by_kalshi = {}
    if kalshi is not None and len(kalshi):
        for fid, g in kalshi[kalshi["fixture_id"].astype(str) != ""].groupby("fixture_id"):
            calls = {kalshi_round(t) for t in g["rules_primary"]} - {None}
            if len(calls) == 1:
                by_kalshi[fid] = calls.pop()
    seen: dict[str, set] = {}
    first_day: dict[str, int] = {}
    rows = []
    for r in f.itertuples():
        players = seen.setdefault(r.edition_key, set())
        p1_played, p2_played = str(r.participant1_id) in players, str(r.participant2_id) in players
        players.update([str(r.participant1_id), str(r.participant2_id)])
        if pd.isna(r.day):
            stage, source = "unknown", "no_start_time"
        else:
            first_day.setdefault(r.edition_key, r.day)
            level = levels.get(r.edition_key, "")
            mixed = MIXED_DAYS.get(level, DEFAULT_MIXED_DAYS)
            lower_tier = str(level).startswith(LOWER_TIER_PREFIXES)
            # Lower tiers: OddsPapi often misses a qualifier's first qualifying match, so one
            # player who already played is enough; tour level: both must have.
            quali_pair = (p1_played or p2_played) if lower_tier else (p1_played and p2_played)
            if r.fixture_id in by_kalshi:
                stage, source = by_kalshi[r.fixture_id], "kalshi"
            elif mixed is None:
                main_from = MAIN_FROM.get(level, 0)
                stage, source = ("main", "after_start") if r.day >= main_from else ("qualifying", "before_start")
            elif r.day < mixed[0]:
                stage, source = "qualifying", "before_start"
            elif r.day > mixed[1]:
                stage, source = "main", "after_start"
            elif quali_pair:
                stage, source = "qualifying", "played_before"
            elif first_day[r.edition_key] < r.day:
                stage, source = "main", "qualifying_started_earlier"
            else:
                stage, source = "unknown", "start_day"
        rows.append({"fixture_id": r.fixture_id, "stage": stage, "stage_source": source})
    return pd.DataFrame(rows, columns=STAGE_COLUMNS)
