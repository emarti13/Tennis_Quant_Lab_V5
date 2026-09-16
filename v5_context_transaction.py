from __future__ import annotations

from pathlib import Path
import math

import pandas as pd

from v5_tournament_context_registry import load_overrides, upsert_tournament_context


EDITOR_TO_CONTEXT = {
    "Surface": "surface",
    "Environment": "environment",
    "Court Speed": "court_speed_override",
    "CPI": "external_cpi_override",
    "Ace Rate %": "external_ace_rate_pct_override",
    "Rally Length": "external_rally_length_override",
    "Relative Air Density": "external_relative_air_density_override",
    "Altitude m": "external_altitude_m",
    "Ball Type": "external_ball_type",
}


def _same(a, b):
    if pd.isna(a) and pd.isna(b):
        return True
    if isinstance(a, (float, int)) and isinstance(b, (float, int)):
        return math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-9)
    return str(a).strip() == str(b).strip()


def changed_context_values(original: pd.Series, edited: pd.Series):
    changed = {}
    for editor_col, registry_col in EDITOR_TO_CONTEXT.items():
        old = original.get(editor_col)
        new = edited.get(editor_col)
        if not _same(old, new) and not pd.isna(new) and not (isinstance(new, str) and not new.strip()):
            changed[registry_col] = new
    return changed


def _identity_columns(frame):
    for col in ("Fixture ID", "Tournament"):
        if col in frame.columns:
            return col
    raise ValueError("Daily Board has no fixture/tournament identity column")


def commit_successful_adjustments(path, original, edited, *, adjusted_run_succeeded, writer=upsert_tournament_context):
    """Commit changed context only after the adjusted production path succeeds.

    The function intentionally has no pre-run write path. Each write is followed by a
    fresh disk reload and value verification before success is returned.
    """
    if not adjusted_run_succeeded:
        raise RuntimeError("adjusted production run did not succeed; context transaction aborted")
    if original is None or edited is None or original.empty or edited.empty:
        return 0

    key_col = _identity_columns(original)
    if key_col not in edited.columns:
        raise ValueError(f"edited board is missing identity column {key_col}")
    originals = original.set_index(key_col, drop=False)
    edits = edited.set_index(key_col, drop=False)
    committed = 0
    p = Path(path)

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
        if reloaded.empty:
            raise RuntimeError(f"context read-back failed for {tournament}")
        from v5_tournament_context_registry import canonical_tournament_key
        key = canonical_tournament_key(tournament)
        matches = reloaded[reloaded["tournament_key"].astype(str).eq(key)]
        if matches.empty:
            raise RuntimeError(f"context read-back identity failed for {tournament}")
        row = matches.iloc[-1]
        for field, expected in values.items():
            actual = row.get(field)
            if not _same(actual, expected):
                raise RuntimeError(f"context read-back mismatch for {tournament}: {field}")
        committed += 1
    return committed
