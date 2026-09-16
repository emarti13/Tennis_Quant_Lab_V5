from __future__ import annotations

from pathlib import Path
import re
import unicodedata

import pandas as pd


_DECORATION = {
    "atp", "wta", "challenger", "men", "women", "singles", "qualifying", "qualification",
    "usa", "austria", "france", "brazil", "mexico", "colombia", "spain", "portugal",
}


def _norm(value) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii").lower()
    return " ".join(re.findall(r"[a-z0-9]+", text))


def _event_core(value) -> str:
    return " ".join(t for t in _norm(value).split() if t not in _DECORATION)


def _tour_mask(schedule: pd.DataFrame, provider_tournament: str, provider_tour: str):
    tours = schedule["Tour"].fillna("").astype(str).str.lower()
    name = _norm(provider_tournament)
    tour = _norm(provider_tour)
    if "challenger" in name or "challenger" in tour:
        return tours.str.startswith("challenger")
    if "wta" in name or "wta" in tour:
        if "125" in name or "125" in tour:
            return tours.eq("wta 125")
        return tours.eq("wta tour")
    if "atp" in name or tour in {"men", "atp"}:
        return tours.str.startswith("atp") | tours.eq("grand slam")
    return pd.Series(True, index=schedule.index)


def resolve_master_schedule_context(provider_tournament, provider_tour, *, year=2026, schedule_path=None):
    path = Path(schedule_path or Path(__file__).parent / "context_registry" / "tennis_master_schedule.csv")
    if not path.exists() or path.stat().st_size == 0:
        return None
    schedule = pd.read_csv(path, low_memory=False)
    if schedule.empty or not {"Year", "Tour", "Tournament"}.issubset(schedule.columns):
        return None
    candidates = schedule.loc[pd.to_numeric(schedule["Year"], errors="coerce").eq(int(year))].copy()
    candidates = candidates.loc[_tour_mask(candidates, str(provider_tournament), str(provider_tour))].copy()
    if candidates.empty:
        return None
    target = _event_core(provider_tournament)
    candidates["_core"] = candidates["Tournament"].map(_event_core)
    exact = candidates.loc[candidates["_core"].eq(target)]
    if len(exact) == 1:
        row = exact.iloc[0]
    else:
        # Provider names add tour/country decorations; official event names often add sponsors.
        scored = []
        target_tokens = set(target.split())
        for idx, candidate in candidates.iterrows():
            core = candidate["_core"]
            tokens = set(core.split())
            if not target_tokens or not tokens:
                continue
            overlap = len(target_tokens & tokens) / len(target_tokens | tokens)
            contains = target in core or core in target
            score = overlap + (0.75 if contains else 0.0)
            if score >= 0.60:
                scored.append((score, idx))
        scored.sort(reverse=True)
        if not scored or (len(scored) > 1 and abs(scored[0][0] - scored[1][0]) < 0.08):
            return None
        row = candidates.loc[scored[0][1]]
    return {
        "official_tournament": row.get("Tournament"),
        "surface": row.get("Surface"),
        "environment": row.get("Setting"),
        "altitude_m": row.get("Altitude (m)"),
        "ball_type": row.get("Ball Characteristics"),
        "speed_profile": row.get("Speed Profile"),
        "source": "canonical master schedule",
    }


def enrich_daily_board_context(frame: pd.DataFrame, *, year=2026, schedule_path=None) -> pd.DataFrame:
    out = frame.copy(deep=True)
    if out.empty or "Tournament" not in out.columns:
        return out
    for idx, row in out.iterrows():
        resolved = resolve_master_schedule_context(
            row.get("Tournament"), row.get("Tour"), year=year, schedule_path=schedule_path
        )
        if not resolved:
            continue
        values = {
            "Surface": resolved["surface"], "Environment": resolved["environment"],
            "Altitude m": resolved["altitude_m"], "Ball Type": resolved["ball_type"],
            "Court Conditions Source": resolved["source"],
        }
        for col, value in values.items():
            current = out.at[idx, col] if col in out.columns else None
            if col not in out.columns:
                out[col] = pd.NA
                current = None
            if pd.isna(current) or (isinstance(current, str) and not current.strip()):
                if pd.notna(value) and not (isinstance(value, str) and not value.strip()):
                    out.at[idx, col] = value
    return out
