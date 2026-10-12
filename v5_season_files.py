"""Season-year rules for TennisMyLife source files.

One place decides which years are "history" (cached aggregates built by
bootstrap_v5_history.py) and which are "current season" (downloaded on every
refresh by refresh_tennismylife_cloud.py). Everything that reads those files
(build_v5_states.py, v5_results_cache.py, the context warehouse, workflow cache
keys) derives its file names from here, so nothing breaks at the new year.

Stdlib only: workflows import this before installing dependencies.
"""
from __future__ import annotations

from datetime import datetime, timezone

HISTORY_START_YEAR = 2010
HISTORY_CACHE_VERSION = "v4"

# TennisMyLife publishes the new season file once matches are played. For the
# first weeks of January the current-season file may legitimately be absent,
# and last season's December results still need to reach settlement.
NEW_SEASON_GRACE_DAYS = 21

SEASON_KINDS = ("atp_main", "atp_quali", "challenger", "wta")
_SUFFIX = {"atp_main": "", "atp_quali": "_atp_quali", "challenger": "_challenger", "wta": "_wta"}
_TOUR = {"atp_main": "MEN", "atp_quali": "MEN", "challenger": "MEN", "wta": "WTA"}
_LEVEL = {"atp_main": "Main", "atp_quali": "Qualifying", "challenger": "Challenger", "wta": "Main"}


def _now(now: datetime | None) -> datetime:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc)


def current_season_year(now: datetime | None = None) -> int:
    return _now(now).year


def history_end_year(now: datetime | None = None) -> int:
    """Last full season covered by the cached history aggregates."""
    return current_season_year(now) - 1


def in_new_season_grace(now: datetime | None = None) -> bool:
    n = _now(now)
    return n.timetuple().tm_yday <= NEW_SEASON_GRACE_DAYS


def season_file_name(year: int, kind: str) -> str:
    return f"{int(year)}{_SUFFIX[kind]}.csv"


def season_file_names(year: int) -> dict[str, str]:
    return {kind: season_file_name(year, kind) for kind in SEASON_KINDS}


def recent_season_years(now: datetime | None = None) -> tuple[int, ...]:
    """Season years whose per-year files a refresh keeps locally.

    Normally just the current season. During the new-season grace window the
    previous season is kept too, so late-December results still settle.
    """
    year = current_season_year(now)
    return (year - 1, year) if in_new_season_grace(now) else (year,)


def season_sources(tour: str, years) -> list[tuple[str, str]]:
    """(file name, level) pairs for build_v5_states.py, oldest year first."""
    out = []
    for year in sorted(int(y) for y in years):
        for kind in SEASON_KINDS:
            if _TOUR[kind] == tour:
                out.append((season_file_name(year, kind), _LEVEL[kind]))
    return out


def rolling_history_years(span: int = 4, now: datetime | None = None) -> tuple[int, ...]:
    end = current_season_year(now)
    return tuple(range(end - span + 1, end + 1))


def history_cache_key(now: datetime | None = None) -> str:
    return f"v5-tennis-history-{HISTORY_START_YEAR}-{history_end_year(now)}-{HISTORY_CACHE_VERSION}"


if __name__ == "__main__":
    import sys

    if sys.argv[1:] == ["cache-key"]:
        print(history_cache_key())
    else:
        print("usage: python v5_season_files.py cache-key", file=sys.stderr)
        raise SystemExit(2)
