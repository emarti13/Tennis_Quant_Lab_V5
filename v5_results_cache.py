from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


REQUIRED_COLUMNS = {"winner_name", "loser_name", "tourney_date", "score"}
DEFAULT_RESULT_FILES = (
    "2026.csv",
    "2026_atp_quali.csv",
    "2026_challenger.csv",
    "2026_wta.csv",
    "ongoing_tourneys.csv",
    "challenger_ongoing_tourneys.csv",
    "wta_ongoing_tourneys.csv",
)
DEFAULT_CACHE = Path("v5_results_ready/tennismylife_results.csv")
DEFAULT_STATUS = Path("v5_results_ready/results_status.json")


def _read_valid_result_file(path: Path) -> pd.DataFrame | None:
    if not path.exists() or path.stat().st_size == 0:
        return None
    try:
        frame = pd.read_csv(path, low_memory=False)
    except (OSError, pd.errors.EmptyDataError, pd.errors.ParserError):
        return None
    if not REQUIRED_COLUMNS.issubset(frame.columns):
        return None
    if "tourney_name" not in frame.columns:
        frame["tourney_name"] = ""
    frame = frame[frame["winner_name"].notna() & frame["loser_name"].notna()].copy()
    frame["result_file"] = path.name
    return frame


def build_results_cache(
    source_files,
    output_path: str | Path = DEFAULT_CACHE,
    status_path: str | Path = DEFAULT_STATUS,
    *,
    source_success_utc: str | None = None,
) -> dict:
    output = Path(output_path)
    status = Path(status_path)
    frames = []
    used = []
    for value in source_files:
        path = Path(value)
        frame = _read_valid_result_file(path)
        if frame is None:
            continue
        frames.append(frame)
        used.append(path.name)
    if not frames:
        raise RuntimeError("No valid persisted TennisMyLife result files were available to build the cache.")

    combined = pd.concat(frames, ignore_index=True, sort=False)
    keys = [c for c in ["tourney_id", "match_num", "winner_name", "loser_name", "score"] if c in combined.columns]
    if keys:
        combined = combined.drop_duplicates(keys, keep="last")

    output.parent.mkdir(parents=True, exist_ok=True)
    staging = output.with_suffix(output.suffix + ".tmp")
    combined.to_csv(staging, index=False)
    staging.replace(output)

    payload = {
        "stage": "results_cache",
        "state": "READY",
        "built_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_success_utc": source_success_utc,
        "rows": int(len(combined)),
        "source_files": used,
        "path": str(output),
    }
    status.parent.mkdir(parents=True, exist_ok=True)
    status.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def load_results_cache(path: str | Path = DEFAULT_CACHE) -> pd.DataFrame:
    source = Path(path)
    if not source.exists() or source.stat().st_size == 0:
        return pd.DataFrame()
    try:
        frame = pd.read_csv(source, low_memory=False)
    except (OSError, pd.errors.EmptyDataError, pd.errors.ParserError):
        return pd.DataFrame()
    if not REQUIRED_COLUMNS.issubset(frame.columns):
        return pd.DataFrame()
    return frame


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", default=".")
    parser.add_argument("--source-success-utc", default=None)
    args = parser.parse_args()
    base = Path(args.dir)
    files = [base / name for name in DEFAULT_RESULT_FILES]
    payload = build_results_cache(
        files,
        base / DEFAULT_CACHE,
        base / DEFAULT_STATUS,
        source_success_utc=args.source_success_utc,
    )
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
