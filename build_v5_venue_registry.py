from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from v5_venue_metadata import build_registry_from_events


def build_venue_registry(base_dir: str | Path = ".", geocoder=None) -> dict[str, object]:
    base = Path(base_dir)
    warehouse_path = base / "context_warehouse" / "matches.parquet"
    if not warehouse_path.exists():
        raise FileNotFoundError("context_warehouse/matches.parquet missing; build the context warehouse first")

    matches = pd.read_parquet(warehouse_path)
    if matches.empty:
        raise RuntimeError("context warehouse contains no matches; refusing to create an empty venue registry")

    registry, report = build_registry_from_events(matches, geocoder=geocoder)
    out_dir = base / "context_registry"
    out_dir.mkdir(parents=True, exist_ok=True)

    registry_path = out_dir / "tournaments.csv"
    report_path = out_dir / "venue_registry_report.json"
    registry.to_csv(registry_path, index=False)
    report_path.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")

    result = {
        "registry_rows": int(len(registry)),
        "events": int(report.get("events", 0)),
        "resolved_events": int(report.get("resolved_events", 0)),
        "unresolved_events": int(report.get("unresolved_events", 0)),
        "registry_path": str(registry_path),
        "report_path": str(report_path),
    }
    return result


def main() -> int:
    result = build_venue_registry(".")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
