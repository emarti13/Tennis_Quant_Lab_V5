from __future__ import annotations

from pathlib import Path
import re
import unicodedata

import pandas as pd

_DECORATION = {"atp","wta","challenger","men","women","singles","qualifying","qualification","usa","austria","france","brazil","mexico","colombia","spain","portugal"}
_TEXT_CONTEXT_COLUMNS = ("Surface", "Surface Source", "Environment", "Ball Type", "Court Conditions Source")
_NUMERIC_CONTEXT_COLUMNS = ("Court Speed", "CPI", "Ace Rate %", "Rally Length", "Relative Air Density", "Altitude m")


def _norm(value) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii").lower()
    return " ".join(re.findall(r"[a-z0-9]+", text))


def _event_core(value) -> str:
    return " ".join(t for t in _norm(value).split() if t not in _DECORATION)


def _tour_mask(schedule: pd.DataFrame, provider_tournament: str, provider_tour: str):
    tours = schedule["Tour"].fillna("").astype(str).str.lower()
    name, tour = _norm(provider_tournament), _norm(provider_tour)
    if "challenger" in name or "challenger" in tour: return tours.str.startswith("challenger")
    if "wta" in name or "wta" in tour:
        return tours.eq("wta 125") if ("125" in name or "125" in tour) else tours.eq("wta tour")
    if "atp" in name or tour in {"men", "atp"}: return tours.str.startswith("atp") | tours.eq("grand slam")
    return pd.Series(True, index=schedule.index)


def resolve_master_schedule_context(provider_tournament, provider_tour, *, year=2026, schedule_path=None):
    found = _resolve_by_name(provider_tournament, provider_tour, year=year, schedule_path=schedule_path)
    if found is not None:
        return found
    # Provider labels often name the city (WTA Sao Paulo) while the schedule uses
    # the event name (SP Open). The tournament authority is the identity source,
    # so retry with its official name rather than guessing.
    official = _authority_name(provider_tournament, provider_tour, year)
    if official and _event_core(official) != _event_core(provider_tournament):
        return _resolve_by_name(official, provider_tour, year=year, schedule_path=schedule_path)
    return None


def _authority_name(provider_tournament, provider_tour, year):
    try:
        from v5_tournament_authority import resolve_authority
        row = resolve_authority(provider_tournament, int(year), tour=provider_tour)
    except Exception:
        return None
    name = (row or {}).get("Tournament Name")
    return str(name) if _has(name) else None


def _resolve_by_name(provider_tournament, provider_tour, *, year=2026, schedule_path=None):
    path = Path(schedule_path or Path(__file__).parent / "context_registry" / "tennis_master_schedule.csv")
    if not path.exists() or path.stat().st_size == 0: return None
    schedule = pd.read_csv(path, low_memory=False)
    if schedule.empty or not {"Year", "Tour", "Tournament"}.issubset(schedule.columns): return None
    candidates = schedule.loc[pd.to_numeric(schedule["Year"], errors="coerce").eq(int(year))].copy()
    candidates = candidates.loc[_tour_mask(candidates, str(provider_tournament), str(provider_tour))].copy()
    if candidates.empty: return None
    target = _event_core(provider_tournament)
    candidates["_core"] = candidates["Tournament"].map(_event_core)
    exact = candidates.loc[candidates["_core"].eq(target)]
    if len(exact) == 1: row = exact.iloc[0]
    else:
        scored, target_tokens = [], set(target.split())
        for idx, candidate in candidates.iterrows():
            core, tokens = candidate["_core"], set(candidate["_core"].split())
            if not target_tokens or not tokens: continue
            overlap = len(target_tokens & tokens) / len(target_tokens | tokens)
            contains = target in core or core in target
            score = overlap + (0.75 if contains else 0.0)
            if score >= 0.60: scored.append((score, idx))
        scored.sort(reverse=True)
        if not scored or (len(scored) > 1 and abs(scored[0][0] - scored[1][0]) < 0.08): return None
        row = candidates.loc[scored[0][1]]
    return {"official_tournament":row.get("Tournament"),"surface":row.get("Surface"),"environment":row.get("Setting"),"altitude_m":row.get("Altitude (m)"),"ball_type":row.get("Ball Characteristics"),"speed_profile":row.get("Speed Profile"),"source":"canonical master schedule"}


def _has(value):
    if value is None: return False
    try:
        if pd.isna(value): return False
    except Exception: pass
    return not (isinstance(value, str) and not value.strip())


def _normalize_context_dtypes(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy(deep=True)
    for col in _TEXT_CONTEXT_COLUMNS:
        if col not in out.columns: out[col] = pd.Series(pd.NA, index=out.index, dtype="object")
        elif out[col].dtype != object: out[col] = out[col].astype("object")
    for col in _NUMERIC_CONTEXT_COLUMNS:
        if col not in out.columns: out[col] = pd.Series(float("nan"), index=out.index, dtype="float64")
        else: out[col] = pd.to_numeric(out[col], errors="coerce")
    return out


def enrich_daily_board_context(frame: pd.DataFrame, *, year=2026, schedule_path=None) -> pd.DataFrame:
    """Attach authoritative schedule identity without replacing dynamic court evidence.

    Surface/environment come from the canonical schedule. Altitude/ball fill only
    missing values. Court speed and the CourtSpeed-derived condition metrics are
    deliberately untouched: those belong to the leak-safe production context path.
    Existing Court Conditions Source provenance is also preserved.
    """
    out = _normalize_context_dtypes(frame)
    if out.empty or "Tournament" not in out.columns: return out
    for idx, row in out.iterrows():
        resolved = resolve_master_schedule_context(row.get("Tournament"), row.get("Tour"), year=year, schedule_path=schedule_path)
        if not resolved: continue
        if _has(resolved["surface"]):
            out.at[idx, "Surface"] = resolved["surface"]
            out.at[idx, "Surface Source"] = resolved["source"]
        if _has(resolved["environment"]): out.at[idx, "Environment"] = resolved["environment"]
        for col, value in {"Altitude m":resolved["altitude_m"], "Ball Type":resolved["ball_type"]}.items():
            if not _has(out.at[idx, col]) and _has(value): out.at[idx, col] = value
        if not _has(out.at[idx, "Court Conditions Source"]):
            out.at[idx, "Court Conditions Source"] = resolved["source"]
    return out