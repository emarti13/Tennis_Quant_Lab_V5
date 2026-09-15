from __future__ import annotations

from difflib import SequenceMatcher
from pathlib import Path
import re

import numpy as np
import pandas as pd

from v5_tournament_registry import normalize_event_name


SCHEDULE_PATH = Path("context_registry/tennis_master_schedule.csv")
_GENERIC_TOKENS = {
    "open", "masters", "master", "championship", "championships", "tennis",
    "presented", "by", "the", "international", "internazionali", "classic",
    "tournament", "cup", "atp", "wta", "tour", "challenger", "grand", "slam",
}
_SPONSOR_TOKENS = {
    "rolex", "bnp", "paribas", "mutua", "citi", "mubadala", "goneset", "gonet",
    "banc", "sabadell", "duty", "free", "totalenergies", "akron", "claro", "evie",
    "wortmann", "cinch", "boss", "plava", "laguna", "generali", "rogers", "itaú", "itau",
    "tiriac", "abn", "amro", "ersteh", "erste", "bank", "swiss", "indoors", "nordic",
}


def _strip_year(value: str) -> str:
    return re.sub(r"\s*\((?:19|20)\d{2}\)\s*$", "", str(value or "")).strip()


def _tour_family(value: str) -> str:
    text = str(value or "").upper()
    if "WTA" in text or "WOMEN" in text:
        return "WTA"
    if "ATP" in text or "MEN" in text:
        return "MEN"
    if "GRAND SLAM" in text:
        return "BOTH"
    return "BOTH"


def _core_name(value: str) -> str:
    normalized = normalize_event_name(_strip_year(value))
    tokens = [t for t in normalized.split() if t not in _GENERIC_TOKENS and t not in _SPONSOR_TOKENS]
    return " ".join(tokens) if tokens else normalized


def speed_profile_family(value: str) -> str:
    text = normalize_event_name(value or "")
    if not text:
        return "unknown"
    if "altitude" in text and any(x in text for x in ("fast", "flight", "flying", "volatile")):
        return "altitude_fast"
    if "altitude" in text:
        return "altitude"
    if "slow court" in text and "fast air" in text:
        return "slow_court_fast_air"
    if "slow" in text and "clay" in text:
        return "slow_clay"
    if "medium slow" in text:
        return "medium_slow"
    if "medium fast" in text:
        return "medium_fast"
    if "fast" in text:
        return "fast"
    if "slow" in text:
        return "slow"
    if "medium" in text:
        return "medium"
    return text.replace(" ", "_")


def load_schedule(path: str | Path = SCHEDULE_PATH) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        return pd.DataFrame()
    return normalize_schedule(pd.read_csv(path, low_memory=False))


def normalize_schedule(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    df = frame.copy()
    rename = {
        "Year": "schedule_year", "Circuit Tour": "schedule_circuit_tour",
        "Tournament Name": "schedule_tournament_name", "City Venue": "schedule_city_venue",
        "Surface": "schedule_surface", "Setting": "schedule_setting",
        "Altitude (m)": "schedule_altitude_m", "Altitude (ft)": "schedule_altitude_ft",
        "Speed Profile": "schedule_speed_profile", "Ball Characteristics": "schedule_ball_characteristics",
    }
    df = df.rename(columns=rename)
    for col in rename.values():
        if col not in df.columns:
            df[col] = np.nan
    df["schedule_year"] = pd.to_numeric(df["schedule_year"], errors="coerce").astype("Int64")
    df["schedule_altitude_m"] = pd.to_numeric(df["schedule_altitude_m"], errors="coerce")
    df["schedule_altitude_ft"] = pd.to_numeric(df["schedule_altitude_ft"], errors="coerce")
    df["schedule_name_normalized"] = df["schedule_tournament_name"].map(lambda x: normalize_event_name(_strip_year(x)))
    df["schedule_name_core"] = df["schedule_tournament_name"].map(_core_name)
    df["schedule_city_normalized"] = df["schedule_city_venue"].map(normalize_event_name)
    df["schedule_tour_family"] = df["schedule_circuit_tour"].map(_tour_family)
    df["schedule_setting"] = df["schedule_setting"].map(lambda x: str(x).strip().title() if pd.notna(x) else np.nan)
    df["schedule_speed_profile_family"] = df["schedule_speed_profile"].map(speed_profile_family)
    return df.reset_index(drop=True)


def _event_year(row: pd.Series) -> int | None:
    for key in ("match_date", "tourney_date", "start_time_utc"):
        value = row.get(key)
        if pd.isna(value):
            continue
        text = str(value).strip()
        if re.fullmatch(r"\d{8}(?:\.0+)?", text):
            dt = pd.to_datetime(text.split(".")[0], format="%Y%m%d", errors="coerce")
        else:
            dt = pd.to_datetime(value, errors="coerce", utc=True)
        if pd.notna(dt):
            return int(dt.year)
    year = pd.to_numeric(pd.Series([row.get("year")]), errors="coerce").iloc[0]
    return int(year) if pd.notna(year) else None


def _similarity(event_name: str, schedule_row: pd.Series, city: str = "") -> tuple[float, str]:
    name = normalize_event_name(event_name or "")
    core = _core_name(event_name)
    sched_name = str(schedule_row.get("schedule_name_normalized") or "")
    sched_core = str(schedule_row.get("schedule_name_core") or "")
    if name and name == sched_name:
        return 1.0, "exact"
    if core and core == sched_core:
        return 0.96, "alias"
    seq = SequenceMatcher(None, name, sched_name).ratio() if name and sched_name else 0.0
    core_seq = SequenceMatcher(None, core, sched_core).ratio() if core and sched_core else 0.0
    a = set(core.split()); b = set(sched_core.split())
    jac = len(a & b) / len(a | b) if a and b else 0.0
    score = 0.45 * max(seq, core_seq) + 0.45 * jac
    city_norm = normalize_event_name(city or "")
    sched_city = str(schedule_row.get("schedule_city_normalized") or "")
    if city_norm and sched_city and (city_norm == sched_city or city_norm in sched_city or sched_city in city_norm):
        score += 0.10
    return min(score, 0.99), "fuzzy_high"


def match_schedule_event(event: pd.Series | dict, schedule: pd.DataFrame) -> dict:
    row = pd.Series(event)
    sched = normalize_schedule(schedule) if "schedule_name_normalized" not in schedule.columns else schedule.copy()
    year = _event_year(row)
    tour = _tour_family(row.get("tour") or row.get("circuit_tour") or row.get("level"))
    surface = normalize_event_name(row.get("surface") or "")
    candidates = sched.copy()
    if year is not None:
        candidates = candidates[candidates["schedule_year"].astype("Int64") == int(year)]
    if tour in {"MEN", "WTA"}:
        candidates = candidates[candidates["schedule_tour_family"].isin([tour, "BOTH"])]
    if surface:
        same_surface = candidates["schedule_surface"].map(normalize_event_name) == surface
        candidates = candidates[same_surface]
    candidate_count = int(len(candidates))
    empty = {
        "schedule_tournament_name": np.nan, "schedule_city_venue": np.nan,
        "schedule_surface": np.nan, "schedule_setting": np.nan, "schedule_altitude_m": np.nan,
        "schedule_altitude_ft": np.nan, "schedule_speed_profile": np.nan,
        "schedule_speed_profile_family": np.nan, "schedule_ball_characteristics": np.nan,
        "schedule_circuit_tour": np.nan, "schedule_match_method": "unmatched",
        "schedule_match_score": np.nan, "schedule_match_candidate_count": candidate_count,
    }
    if candidates.empty:
        return empty
    event_name = row.get("tourney_name") or row.get("tournament") or row.get("event_name") or ""
    city = row.get("city") or row.get("venue_city") or row.get("location") or ""
    ranked = []
    for idx, cand in candidates.iterrows():
        score, method = _similarity(str(event_name), cand, str(city))
        ranked.append((score, method, idx))
    ranked.sort(reverse=True, key=lambda x: x[0])
    top_score, top_method, top_idx = ranked[0]
    second = ranked[1][0] if len(ranked) > 1 else -1.0

    # Exact normalized-name identity is deterministic. Alias/core-name identity is
    # not: generic city/event labels can collapse multiple legitimate schedule
    # rows to the same core (for example, "Indian Wells"). Fail closed whenever
    # another candidate is close enough that the alias does not uniquely identify
    # the tournament.
    ambiguous_gap = second >= 0 and top_score - second < 0.08
    if top_method != "exact" and (top_score < 0.72 or ambiguous_gap):
        empty["schedule_match_method"] = "ambiguous" if top_score >= 0.55 else "unmatched"
        empty["schedule_match_score"] = float(top_score)
        return empty

    chosen = candidates.loc[top_idx]
    return {
        "schedule_tournament_name": chosen.get("schedule_tournament_name"),
        "schedule_city_venue": chosen.get("schedule_city_venue"),
        "schedule_surface": chosen.get("schedule_surface"),
        "schedule_setting": chosen.get("schedule_setting"),
        "schedule_altitude_m": chosen.get("schedule_altitude_m"),
        "schedule_altitude_ft": chosen.get("schedule_altitude_ft"),
        "schedule_speed_profile": chosen.get("schedule_speed_profile"),
        "schedule_speed_profile_family": chosen.get("schedule_speed_profile_family"),
        "schedule_ball_characteristics": chosen.get("schedule_ball_characteristics"),
        "schedule_circuit_tour": chosen.get("schedule_circuit_tour"),
        "schedule_match_method": top_method,
        "schedule_match_score": float(top_score),
        "schedule_match_candidate_count": candidate_count,
    }


def enrich_events_with_schedule(events: pd.DataFrame, schedule: pd.DataFrame | None = None) -> pd.DataFrame:
    if events is None or events.empty:
        return events.copy() if events is not None else pd.DataFrame()
    sched = load_schedule() if schedule is None else normalize_schedule(schedule)
    out = events.copy()
    matched = [match_schedule_event(row, sched) for _, row in out.iterrows()]
    features = pd.DataFrame(matched, index=out.index)
    for col in features.columns:
        out[col] = features[col]
    return out


def schedule_coverage_report(events: pd.DataFrame) -> dict:
    if events is None or events.empty or "schedule_match_method" not in events.columns:
        return {"rows": 0, "resolved": 0, "ambiguous": 0, "unmatched": 0, "resolution_rate": 0.0}
    method = events["schedule_match_method"].fillna("unmatched").astype(str)
    resolved_mask = method.isin(["exact", "alias", "fuzzy_high"])
    return {
        "rows": int(len(events)),
        "resolved": int(resolved_mask.sum()),
        "ambiguous": int((method == "ambiguous").sum()),
        "unmatched": int((method == "unmatched").sum()),
        "resolution_rate": float(resolved_mask.mean()) if len(events) else 0.0,
    }
