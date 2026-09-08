from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd


def _norm_text(value) -> str:
    s = "" if value is None else str(value).strip()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower().replace(",", " ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def _norm_line(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    try:
        number = float(value)
    except Exception:
        return str(value).strip().lower()
    if abs(number - round(number)) < 1e-12:
        return str(int(round(number)))
    return format(number, ".12g")


def stable_market_key(fixture_id, market_group, selection, line=None) -> str:
    return "|".join(
        [
            str(fixture_id).strip(),
            _norm_text(market_group).replace(" ", "_"),
            _norm_text(selection),
            _norm_line(line),
        ]
    )


def promote_csv_last_known_good(
    candidate_path: str | Path,
    canonical_path: str | Path,
    *,
    required_columns: Iterable[str] = (),
    require_nonempty: bool = True,
) -> dict:
    candidate = Path(candidate_path)
    canonical = Path(canonical_path)
    if not candidate.exists():
        raise ValueError(f"candidate artifact does not exist: {candidate}")
    try:
        frame = pd.read_csv(candidate, low_memory=False)
    except (pd.errors.EmptyDataError, OSError) as exc:
        raise ValueError(f"candidate artifact is unreadable: {candidate}") from exc
    missing = [c for c in required_columns if c not in frame.columns]
    if missing:
        raise ValueError(f"candidate artifact missing required columns: {missing}")
    if require_nonempty and frame.empty:
        raise ValueError("candidate artifact is empty")

    canonical.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{canonical.name}.", dir=str(canonical.parent))
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        shutil.copyfile(candidate, tmp)
        os.replace(tmp, canonical)
    finally:
        if tmp.exists():
            tmp.unlink()
    return {"rows": int(len(frame)), "columns": list(frame.columns), "path": str(canonical)}


def artifact_status(
    *,
    stage: str,
    state: str,
    source_version=None,
    rows: int = 0,
    fixtures: int = 0,
    freshness=None,
    error=None,
    run_timestamp=None,
) -> dict:
    if run_timestamp is None:
        run_timestamp = datetime.now(timezone.utc).isoformat()
    return {
        "stage": stage,
        "run_timestamp": run_timestamp,
        "source_version": source_version,
        "state": state,
        "rows": int(rows),
        "fixtures": int(fixtures),
        "freshness": freshness,
        "error": error,
    }


def write_status(path: str | Path, payload: dict) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
