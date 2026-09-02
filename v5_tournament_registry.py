from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
import re
import unicodedata

import pandas as pd


def normalize_event_name(value: str) -> str:
    text = "" if value is None else str(value)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    tokens = text.split()
    collapsed = []
    initials = []
    for token in tokens:
        if len(token) == 1 and token.isalpha():
            initials.append(token)
            continue
        if initials:
            collapsed.append("".join(initials))
            initials = []
        collapsed.append(token)
    if initials:
        collapsed.append("".join(initials))
    return " ".join(collapsed)


@dataclass(frozen=True)
class TournamentContext:
    canonical_event_id: str | None = None
    canonical_name: str | None = None
    city: str | None = None
    country: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    timezone: str | None = None
    altitude_m: float | None = None
    surface: str | None = None
    indoor: bool | None = None
    source_quality: str = "unresolved"
    matched_alias: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class TournamentRegistry:
    def __init__(self, frame: pd.DataFrame):
        self.frame = frame.copy() if frame is not None else pd.DataFrame()
        self._index: dict[str, list[int]] = {}
        self._event_index: dict[str, list[int]] = {}
        if self.frame.empty:
            return
        for idx, row in self.frame.iterrows():
            event_id = row.get("canonical_event_id")
            if pd.notna(event_id) and str(event_id).strip():
                self._event_index.setdefault(str(event_id).strip(), []).append(idx)
            names = [row.get("canonical_name")]
            alias_value = row.get("aliases")
            aliases = [] if pd.isna(alias_value) else str(alias_value).split("|")
            names.extend(aliases)
            for name in names:
                key = normalize_event_name(name)
                if key:
                    bucket = self._index.setdefault(key, [])
                    if idx not in bucket:
                        bucket.append(idx)

    @classmethod
    def from_csv(cls, path: str | Path = "context_registry/tournaments.csv") -> "TournamentRegistry":
        path = Path(path)
        if not path.exists():
            return cls(pd.DataFrame())
        return cls(pd.read_csv(path))

    def _valid_rows(self, indices: list[int], tour: str, year: int) -> list[pd.Series]:
        requested_tour = str(tour or "").upper().replace("ATP", "MEN")
        valid = []
        for idx in indices:
            row = self.frame.loc[idx]
            row_tour = str(row.get("tour") or "BOTH").upper().replace("ATP", "MEN")
            if row_tour not in ("BOTH", requested_tour):
                continue
            start = pd.to_numeric(pd.Series([row.get("start_year")]), errors="coerce").iloc[0]
            end = pd.to_numeric(pd.Series([row.get("end_year")]), errors="coerce").iloc[0]
            if pd.notna(start) and int(year) < int(start):
                continue
            if pd.notna(end) and int(year) > int(end):
                continue
            valid.append(row)
        return valid

    @staticmethod
    def _row_to_context(row: pd.Series, matched_alias: str | None) -> TournamentContext:
        def _nullable_float(v):
            parsed = pd.to_numeric(pd.Series([v]), errors="coerce").iloc[0]
            return None if pd.isna(parsed) else float(parsed)

        def _nullable_text(v):
            return None if pd.isna(v) or str(v).strip() == "" else str(v).strip()

        indoor = row.get("indoor")
        if pd.isna(indoor):
            indoor_value = None
        elif isinstance(indoor, str):
            indoor_value = indoor.strip().lower() in {"1", "true", "yes", "indoor"}
        else:
            indoor_value = bool(indoor)

        return TournamentContext(
            canonical_event_id=_nullable_text(row.get("canonical_event_id")),
            canonical_name=_nullable_text(row.get("canonical_name")),
            city=_nullable_text(row.get("city")),
            country=_nullable_text(row.get("country")),
            latitude=_nullable_float(row.get("latitude")),
            longitude=_nullable_float(row.get("longitude")),
            timezone=_nullable_text(row.get("timezone")),
            altitude_m=_nullable_float(row.get("altitude_m")),
            surface=_nullable_text(row.get("surface")),
            indoor=indoor_value,
            source_quality=_nullable_text(row.get("source_quality")) or "registry",
            matched_alias=matched_alias,
        )

    def _resolve_indices(self, indices: list[int], tour: str, year: int, matched_alias: str | None) -> TournamentContext:
        valid = self._valid_rows(indices, tour, year)
        if len(valid) != 1:
            return TournamentContext(source_quality="ambiguous" if valid else "unresolved", matched_alias=matched_alias)
        return self._row_to_context(valid[0], matched_alias)

    def resolve(self, name: str, tour: str, year: int) -> TournamentContext:
        key = normalize_event_name(name)
        candidates = self._index.get(key, [])
        if not candidates:
            return TournamentContext(matched_alias=str(name) if name is not None else None)
        return self._resolve_indices(candidates, tour, year, str(name))

    def resolve_event(self, event_id: str, tour: str, year: int) -> TournamentContext:
        """Resolve a stable source event ID with explicit year validity.

        Multiple registry rows may share one stable event ID when a tournament changes or
        alternates venue. Exactly one row must be valid for the requested tour/year; otherwise
        the result remains explicitly ambiguous/unresolved rather than guessed.
        """
        key = str(event_id or "").strip()
        if not key:
            return TournamentContext()
        candidates = self._event_index.get(key, [])
        if not candidates:
            return TournamentContext(matched_alias=key)
        return self._resolve_indices(candidates, tour, year, key)


def coverage_report(matches: pd.DataFrame, registry: TournamentRegistry) -> dict:
    if matches is None or matches.empty:
        return {"rows": 0, "resolved": 0, "resolution_rate": 0.0, "unresolved_events": []}
    resolved = 0
    unresolved: dict[str, int] = {}
    for _, row in matches.iterrows():
        raw_date = row.get("match_date")
        if pd.isna(raw_date):
            raw_date = row.get("tourney_date")
        date = pd.to_datetime(raw_date, errors="coerce")
        year = int(date.year) if pd.notna(date) else 0
        event_id = row.get("canonical_event_id")
        if pd.notna(event_id) and str(event_id).strip():
            result = registry.resolve_event(str(event_id), row.get("tour") or "MEN", year)
        else:
            name = row.get("tourney_name")
            if pd.isna(name) or not str(name).strip():
                name = row.get("tournament") or ""
            result = registry.resolve(name, row.get("tour") or "MEN", year)
        if result.canonical_event_id:
            resolved += 1
        else:
            display_name = str(row.get("tourney_name") or row.get("tournament") or event_id or "")
            unresolved[display_name] = unresolved.get(display_name, 0) + 1
    return {
        "rows": int(len(matches)),
        "resolved": int(resolved),
        "resolution_rate": float(resolved / len(matches)),
        "unresolved_events": [
            {"name": name, "rows": count}
            for name, count in sorted(unresolved.items(), key=lambda x: (-x[1], x[0]))
        ],
    }
