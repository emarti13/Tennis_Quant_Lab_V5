from __future__ import annotations

from difflib import SequenceMatcher
from pathlib import Path
import re
import unicodedata

import numpy as np
import pandas as pd

DEFAULT_PATH = Path("context_registry/tournament_authority.csv")
REQUIRED = ("Year", "Circuit Tour", "Tournament Name", "Surface", "Setting", "Altitude (m)")
COURT_FIELDS = ("Official_Ball_Model", "General_CPI_Category", "Actual_CPI_Rating", "Tennis_Abstract_Rating")
_GENERIC = {
    "atp", "wta", "challenger", "tour", "men", "women", "singles",
    "qualifying", "qualification", "tennis", "championship", "championships",
    "presented", "by", "the",
}


def _norm(value) -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return ""
    text = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii").lower()
    return " ".join(re.findall(r"[a-z0-9]+", text))


def _core(value) -> str:
    return " ".join(token for token in _norm(value).split() if token not in _GENERIC)


def _tour_family(value) -> str:
    tokens = set(_norm(value).split())
    if "wta" in tokens or "women" in tokens:
        return "WTA"
    if "atp" in tokens or "men" in tokens or "challenger" in tokens:
        return "MEN"
    return ""


def _parse_date(value, year):
    if value is None or pd.isna(value) or not str(value).strip():
        return pd.NaT
    text = str(value).strip()
    if not re.search(r"\b(?:19|20)\d{2}\b", text):
        text = f"{text}-{int(year)}"
    return pd.to_datetime(text, errors="coerce", dayfirst=True)


def load_authority(path=DEFAULT_PATH) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"authoritative tournament table missing: {path}")
    try:
        frame = pd.read_csv(path, low_memory=False)
    except UnicodeDecodeError:
        frame = pd.read_csv(path, low_memory=False, encoding="cp1252")
    missing = [column for column in REQUIRED if column not in frame.columns]
    if missing:
        raise ValueError(f"authoritative tournament table missing columns: {missing}")
    out = frame.copy()
    for column in (
        "Year", "Latitude", "Longitude", "Altitude (m)", "Altitude (ft)",
        "Actual_CPI_Rating", "Tennis_Abstract_Rating",
    ):
        if column in out.columns:
            out[column] = pd.to_numeric(out[column], errors="coerce")
    return _prepare(out)


def _prepare(frame: pd.DataFrame) -> pd.DataFrame:
    prepared = {"_name_key", "_name_core", "_city_key", "_tour_family"}.issubset(frame.columns)
    out = frame if prepared else frame.copy()
    if "_name_key" not in out:
        out["_name_key"] = out["Tournament Name"].map(_norm)
    if "_name_core" not in out:
        out["_name_core"] = out["Tournament Name"].map(_core)
    if "_city_key" not in out:
        out["_city_key"] = out.get("City", pd.Series("", index=out.index)).map(_norm)
    if "_tour_family" not in out:
        out["_tour_family"] = out["Circuit Tour"].map(_tour_family)
    return out


def audit_authority(frame: pd.DataFrame) -> dict:
    return {
        "rows": int(len(frame)),
        "years": {str(int(k)): int(v) for k, v in frame["Year"].dropna().value_counts().sort_index().items()},
        "coverage": {column: float(frame[column].notna().mean()) if column in frame else 0.0 for column in REQUIRED + COURT_FIELDS},
        "duplicate_rows": int(frame.duplicated().sum()),
    }


def resolve_authority(
    tournament,
    year,
    *,
    tour="",
    surface=None,
    match_date=None,
    oddspapi_tournament_id=None,
    table=None,
):
    """Resolve a tournament only against the approved authority table.

    OddsPapi ID is optional identity evidence. Missing IDs never reject an otherwise
    resolvable tournament. No legacy court/schedule source is consulted or used as
    fallback.
    """
    frame = _prepare(load_authority() if table is None else table)
    numeric_year = pd.to_numeric(pd.Series([year]), errors="coerce").iloc[0]
    if pd.isna(numeric_year):
        return None
    candidates = frame[pd.to_numeric(frame["Year"], errors="coerce").eq(numeric_year)].copy()

    family = _tour_family(tour)
    if family:
        filtered = candidates[candidates["_tour_family"].eq(family)]
        if not filtered.empty:
            candidates = filtered
    if surface:
        surface_key = _norm(surface)
        filtered = candidates[candidates["Surface"].map(_norm).eq(surface_key)]
        if not filtered.empty:
            candidates = filtered

    if oddspapi_tournament_id is not None and "OddsPapi Tournament ID" in candidates:
        target_id = str(oddspapi_tournament_id).strip().removesuffix(".0")
        ids = candidates["OddsPapi Tournament ID"].map(
            lambda value: "" if pd.isna(value) else str(value).strip().removesuffix(".0")
        )
        hit = candidates[ids.eq(target_id)]
        if len(hit) == 1:
            return hit.iloc[0].to_dict() | {"authority_match_method": "oddspapi_id"}

    tournament_key = _norm(tournament)
    hit = candidates[candidates["_name_key"].eq(tournament_key)]
    if len(hit) == 1:
        return hit.iloc[0].to_dict() | {"authority_match_method": "exact_name"}

    if match_date is not None:
        event_date = pd.to_datetime(match_date, errors="coerce")
        if pd.notna(event_date):
            in_window = []
            for _, row in candidates.iterrows():
                start = _parse_date(row.get("Date"), row.get("Year"))
                end = _parse_date(row.get("End Date"), row.get("Year"))
                if pd.isna(start):
                    in_window.append(False)
                    continue
                if pd.isna(end):
                    end = start + pd.Timedelta(days=14)
                in_window.append(bool(start - pd.Timedelta(days=2) <= event_date <= end + pd.Timedelta(days=2)))
            window = candidates.loc[pd.Series(in_window, index=candidates.index)]
            if not window.empty:
                candidates = window

    # Providers often identify an event by its city (e.g. Indian Wells). This is
    # still an authority-table match, not external reconciliation.
    city_hit = candidates[candidates["_city_key"].eq(tournament_key)]
    if len(city_hit) == 1:
        return city_hit.iloc[0].to_dict() | {"authority_match_method": "city_alias"}

    target_core = _core(tournament)
    ranked = []
    for idx, row in candidates.iterrows():
        candidate_core = str(row.get("_name_core") or "")
        if not target_core or not candidate_core:
            continue
        left, right = set(target_core.split()), set(candidate_core.split())
        jaccard = len(left & right) / len(left | right) if left and right else 0.0
        sequence = SequenceMatcher(None, target_core, candidate_core).ratio()
        ranked.append((max(jaccard, sequence), idx))
    ranked.sort(reverse=True)
    if not ranked or ranked[0][0] < 0.78:
        return None
    if len(ranked) > 1 and ranked[0][0] - ranked[1][0] < 0.10:
        return None
    return candidates.loc[ranked[0][1]].to_dict() | {
        "authority_match_method": "name_alias",
        "authority_match_score": float(ranked[0][0]),
    }


def court_context(row) -> dict:
    if row is None:
        return {}
    return {
        "surface": row.get("Surface"),
        "environment": row.get("Setting"),
        "altitude_m": row.get("Altitude (m)"),
        "ball_model": row.get("Official_Ball_Model"),
        "cpi_category": row.get("General_CPI_Category"),
        "actual_cpi": row.get("Actual_CPI_Rating"),
        "tennis_abstract_rating": row.get("Tennis_Abstract_Rating"),
        "latitude": row.get("Latitude"),
        "longitude": row.get("Longitude"),
        "timezone": row.get("Time Zone"),
        "oddspapi_tournament_id": row.get("OddsPapi Tournament ID"),
        "oddspapi_season_id": row.get("OddsPapi Season ID"),
        "source": "tournament_authority",
        "authority_match_method": row.get("authority_match_method"),
    }
