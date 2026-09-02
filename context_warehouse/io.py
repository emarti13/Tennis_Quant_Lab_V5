from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from .schema import MATCH_COLUMNS, PLAYER_MATCH_COLUMNS, SCHEMA_VERSION


def _write_json(path: Path, payload: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
    tmp.replace(path)


def write_warehouse(
    matches: pd.DataFrame,
    player_rows: pd.DataFrame,
    output_dir: str | Path,
    source_manifest: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)

    matches = matches.reindex(columns=MATCH_COLUMNS)
    player_rows = player_rows.reindex(columns=PLAYER_MATCH_COLUMNS)

    matches.to_csv(root / "matches.csv", index=False)
    player_rows.to_csv(root / "player_match_rows.csv", index=False)

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "sources": list(source_manifest),
        "match_rows": int(len(matches)),
        "player_match_rows": int(len(player_rows)),
    }
    _write_json(root / "source_manifest.json", manifest)

    schema_payload = {
        "schema_version": SCHEMA_VERSION,
        "match_columns": MATCH_COLUMNS,
        "player_match_columns": PLAYER_MATCH_COLUMNS,
    }
    _write_json(root / "schema.json", schema_payload)

    parquet = {"matches": False, "player_match_rows": False, "error": None}
    try:
        matches.to_parquet(root / "matches.parquet", index=False)
        player_rows.to_parquet(root / "player_match_rows.parquet", index=False)
        parquet["matches"] = True
        parquet["player_match_rows"] = True
    except (ImportError, ModuleNotFoundError, ValueError) as exc:
        parquet["error"] = str(exc)

    return {
        "schema_version": SCHEMA_VERSION,
        "match_rows": int(len(matches)),
        "player_match_rows": int(len(player_rows)),
        "parquet": parquet,
    }
