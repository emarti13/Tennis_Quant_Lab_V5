from __future__ import annotations

from pathlib import Path
import os
import re
import tempfile

import numpy as np
import pandas as pd


CONTEXT_FIELDS = (
    "surface",
    "environment",
    "court_speed_override",
    "external_cpi_override",
    "external_ace_rate_pct_override",
    "external_rally_length_override",
    "external_relative_air_density_override",
    "external_altitude_m",
    "external_ball_type",
)

TEXT_CONTEXT_FIELDS = {"surface", "environment", "external_ball_type"}

_DECORATION = {"atp", "wta", "men", "women", "singles", "challenger", "qualification", "qualifying", "qualifier"}


def canonical_tournament_key(name) -> str:
    text = re.sub(r"[^a-z0-9]+", " ", str(name or "").lower()).strip()
    tokens = [token for token in text.split() if token not in _DECORATION]
    return " ".join(sorted(tokens))


def load_overrides(path) -> pd.DataFrame:
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        return pd.DataFrame(columns=("tournament_key", "tournament") + CONTEXT_FIELDS)
    out = pd.read_csv(p, low_memory=False)
    if "tournament_key" not in out.columns:
        out["tournament_key"] = out.get("tournament", pd.Series(dtype=object)).map(canonical_tournament_key)
    return out


def _present(value) -> bool:
    if value is None:
        return False
    try:
        if pd.isna(value):
            return False
    except Exception:
        pass
    return not (isinstance(value, str) and not value.strip())


def _atomic_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    os.close(fd)
    try:
        frame.to_csv(temp_name, index=False)
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def upsert_tournament_context(path, tournament, values) -> pd.DataFrame:
    p = Path(path)
    frame = load_overrides(p)
    key = canonical_tournament_key(tournament)
    if not key:
        raise ValueError("tournament identity is required")
    mask = frame["tournament_key"].astype(str).eq(key) if not frame.empty else pd.Series(dtype=bool)
    if mask.any():
        idx = frame.index[mask][0]
    else:
        idx = len(frame)
        frame.loc[idx, "tournament_key"] = key
    frame.loc[idx, "tournament"] = str(tournament)
    for field, value in dict(values or {}).items():
        if field in CONTEXT_FIELDS and _present(value):
            frame.loc[idx, field] = value
    _atomic_csv(frame, p)
    return frame


def apply_overrides(frame: pd.DataFrame, overrides: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy(deep=True)
    if out.empty or overrides is None or overrides.empty or "tournament" not in out.columns:
        return out
    latest = overrides.drop_duplicates("tournament_key", keep="last").set_index("tournament_key")
    keys = out["tournament"].map(canonical_tournament_key)
    for field in CONTEXT_FIELDS:
        if field not in latest.columns:
            continue
        if field in TEXT_CONTEXT_FIELDS:
            if field not in out.columns:
                out[field] = pd.Series(pd.NA, index=out.index, dtype="string")
            else:
                out[field] = out[field].astype("string")
        elif field not in out.columns:
            out[field] = np.nan
        mapped = keys.map(latest[field])
        use = mapped.map(_present)
        if not use.any():
            continue
        if field in TEXT_CONTEXT_FIELDS:
            out.loc[use, field] = mapped.loc[use].astype("string")
        else:
            out.loc[use, field] = pd.to_numeric(mapped.loc[use], errors="coerce")
    return out
