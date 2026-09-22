from __future__ import annotations

import re
import unicodedata

import numpy as np
import pandas as pd

_ALLOWED_CONTEXT_FAMILIES = (
    "serve_return_geometry",
    "rest_layoff",
    "workload",
    "trajectory",
    "uncertainty_quality",
    "rank",
)


def _family(name: str) -> str:
    key = str(name or "").lower()
    if any(token in key for token in ("travel", "timezone", "continent", "altitude_change")):
        return "travel"
    if any(token in key for token in ("court_speed", "weather", "heat", "humidity", "wind", "big_server_x_altitude")):
        return "environment"
    if any(token in key for token in ("layoff", "rest_", "comeback")):
        return "rest_layoff"
    if any(token in key for token in (
        "matches_3d", "games_3d", "matches_7d", "games_7d", "minutes_7d",
        "matches_14d", "games_14d", "matches_30d", "games_30d",
        "previous_match", "consecutive_play", "workload",
    )):
        return "workload"
    if any(token in key for token in (
        "serve_first", "serve_second", "ace_rate", "double_fault", "return_strength",
        "serve_dominance", "return_dominance", "serve_dependence", "weak_second",
    )):
        return "serve_return_geometry"
    if "trajectory" in key:
        return "trajectory"
    if any(token in key for token in ("uncertainty", "context_quality")):
        return "uncertainty_quality"
    if "rank" in key:
        return "rank"
    return "other"


def non_court_context_columns(frame: pd.DataFrame) -> list[str]:
    """Whitelisted clean-control inputs.

    Travel/environment are intentionally excluded so retired court, altitude,
    weather, or venue-derived values cannot enter the challenger indirectly.
    """
    return sorted(
        column
        for column in frame.columns
        if column.startswith("ctx_") and _family(column) in _ALLOWED_CONTEXT_FAMILIES
    )


def _num(series, default: float = 0.0) -> pd.Series:
    out = pd.to_numeric(series, errors="coerce").astype(float)
    return out.fillna(default)


def _slug(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")


def fit_ball_categories(frame: pd.DataFrame, *, fit_year: int = 2025, min_rows: int = 100) -> list[str]:
    fit = frame[pd.to_numeric(frame["year"], errors="coerce").eq(int(fit_year))]
    if "authority_ball_model" not in fit.columns:
        return []
    values = fit["authority_ball_model"].dropna().astype(str).str.strip()
    values = values[values.ne("")]
    counts = values.value_counts()
    return sorted(counts[counts.ge(int(min_rows))].index.tolist())


def add_authority_features(frame: pd.DataFrame, *, ball_categories: list[str] | None = None) -> pd.DataFrame:
    """Add only new-authority court interactions.

    Tournament-level properties are interacted with signed player geometry so the
    symmetric model remains orientation-safe. Missing authority values are neutral
    zero rather than values borrowed from any retired source.
    """
    out = frame.copy()
    serve = _num(out.get("ctx_serve_dominance_diff", pd.Series(0.0, index=out.index)))
    ret = _num(out.get("ctx_return_dominance_diff", pd.Series(0.0, index=out.index)))
    dependence = _num(out.get("ctx_serve_dependence_diff", pd.Series(0.0, index=out.index)))

    altitude_raw = pd.to_numeric(out.get("authority_altitude_m", pd.Series(np.nan, index=out.index)), errors="coerce")
    altitude_km = (altitude_raw / 1000.0).where(altitude_raw.notna(), 0.0)
    out["ctx_auth_altitude_x_serve_dom"] = serve * altitude_km
    out["ctx_auth_altitude_x_serve_dep"] = dependence * altitude_km

    setting = out.get("authority_setting", pd.Series("", index=out.index)).fillna("").astype(str).str.strip().str.lower()
    indoor = setting.eq("indoor").astype(float)
    out["ctx_auth_indoor_x_serve_dom"] = serve * indoor
    out["ctx_auth_indoor_x_serve_dep"] = dependence * indoor

    cpi_raw = pd.to_numeric(out.get("authority_cpi", pd.Series(np.nan, index=out.index)), errors="coerce")
    cpi = ((cpi_raw - 35.0) / 10.0).where(cpi_raw.notna(), 0.0)
    out["ctx_auth_cpi_x_serve_dom"] = serve * cpi
    out["ctx_auth_cpi_x_return_dom"] = ret * cpi

    ta_raw = pd.to_numeric(out.get("authority_ta", pd.Series(np.nan, index=out.index)), errors="coerce")
    ta = (ta_raw - 1.0).where(ta_raw.notna(), 0.0)
    out["ctx_auth_ta_x_serve_dom"] = serve * ta
    out["ctx_auth_ta_x_return_dom"] = ret * ta

    balls = out.get("authority_ball_model", pd.Series("", index=out.index)).fillna("").astype(str).str.strip()
    for category in ball_categories or []:
        mask = balls.eq(str(category)).astype(float)
        out[f"ctx_auth_ball_{_slug(category)}_x_serve_dep"] = dependence * mask
    return out


def authority_feature_groups(frame: pd.DataFrame) -> dict[str, list[str]]:
    groups = {
        "altitude": [c for c in frame.columns if c.startswith("ctx_auth_altitude_")],
        "setting": [c for c in frame.columns if c.startswith("ctx_auth_indoor_")],
        "cpi_ta": [c for c in frame.columns if c.startswith("ctx_auth_cpi_") or c.startswith("ctx_auth_ta_")],
        "ball": [c for c in frame.columns if c.startswith("ctx_auth_ball_")],
    }
    groups["combined"] = sorted({column for columns in groups.values() for column in columns})
    return {name: sorted(columns) for name, columns in groups.items()}
