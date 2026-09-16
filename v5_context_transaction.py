from __future__ import annotations

from pathlib import Path
import math

import pandas as pd

from v5_tournament_context_registry import canonical_tournament_key, load_overrides, upsert_tournament_context

EDITOR_TO_CONTEXT = {
    "Surface": "surface", "Environment": "environment", "Court Speed": "court_speed_override",
    "CPI": "external_cpi_override", "Ace Rate %": "external_ace_rate_pct_override",
    "Rally Length": "external_rally_length_override", "Relative Air Density": "external_relative_air_density_override",
    "Altitude m": "external_altitude_m", "Ball Type": "external_ball_type",
}


def _missing(value):
    try:
        return bool(pd.isna(value))
    except Exception:
        return value is None


def _same(a, b):
    if _missing(a) and _missing(b):
        return True
    if isinstance(a, (float, int)) and isinstance(b, (float, int)):
        return math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-9)
    return str(a).strip() == str(b).strip()


def changed_context_values(original: pd.Series, edited: pd.Series):
    changed = {}
    for editor_col, registry_col in EDITOR_TO_CONTEXT.items():
        old, new = original.get(editor_col), edited.get(editor_col)
        if not _same(old, new) and not _missing(new) and not (isinstance(new, str) and not new.strip()):
            changed[registry_col] = new
    return changed


def apply_editor_context_overrides(frame: pd.DataFrame, path) -> pd.DataFrame:
    """Overlay only previously committed values onto a future Daily Board editor source."""
    out = frame.copy(deep=True)
    overrides = load_overrides(path)
    if out.empty or overrides.empty or "Tournament" not in out.columns:
        return out
    latest = overrides.drop_duplicates("tournament_key", keep="last").set_index("tournament_key")
    for idx, row in out.iterrows():
        key = canonical_tournament_key(row.get("Tournament"))
        if key not in latest.index:
            continue
        saved = latest.loc[key]
        for editor_col, registry_col in EDITOR_TO_CONTEXT.items():
            value = saved.get(registry_col)
            if not _missing(value) and not (isinstance(value, str) and not value.strip()):
                out.at[idx, editor_col] = value
    return out


def _identity_columns(frame):
    for col in ("Fixture ID", "Tournament"):
        if col in frame.columns:
            return col
    raise ValueError("Daily Board has no fixture/tournament identity column")


def commit_successful_adjustments(path, original, edited, *, adjusted_run_succeeded, writer=upsert_tournament_context):
    if not adjusted_run_succeeded:
        raise RuntimeError("adjusted production run did not succeed; context transaction aborted")
    if original is None or edited is None or original.empty or edited.empty:
        return 0
    key_col = _identity_columns(original)
    if key_col not in edited.columns:
        raise ValueError(f"edited board is missing identity column {key_col}")
    originals, edits = original.set_index(key_col, drop=False), edited.set_index(key_col, drop=False)
    committed, p = 0, Path(path)
    for identity, new_row in edits.iterrows():
        if identity not in originals.index:
            continue
        old_row = originals.loc[identity]
        if isinstance(old_row, pd.DataFrame):
            old_row = old_row.iloc[0]
        values = changed_context_values(old_row, new_row)
        if not values:
            continue
        tournament = str(new_row.get("Tournament") or old_row.get("Tournament") or "").strip()
        if not tournament:
            raise ValueError("cannot persist context without tournament identity")
        writer(p, tournament, values)
        reloaded = load_overrides(p)
        key = canonical_tournament_key(tournament)
        matches = reloaded[reloaded["tournament_key"].astype(str).eq(key)] if not reloaded.empty else pd.DataFrame()
        if matches.empty:
            raise RuntimeError(f"context read-back identity failed for {tournament}")
        saved = matches.iloc[-1]
        for field, expected in values.items():
            if not _same(saved.get(field), expected):
                raise RuntimeError(f"context read-back mismatch for {tournament}: {field}")
        committed += 1
    return committed
