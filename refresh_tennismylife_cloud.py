
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

MANIFEST_URL = "https://stats.tennismylife.org/api/data-files"

# Preferred canonical names in the V5 project.
# TennisMyLife has used slightly different names for ongoing Challenger files,
# so aliases are accepted and normalized locally.
TARGETS = {
    "2026.csv": ["2026.csv"],
    "2026_atp_quali.csv": ["2026_atp_quali.csv"],
    "2026_challenger.csv": ["2026_challenger.csv"],
    "2026_wta.csv": ["2026_wta.csv"],
    "ongoing_tourneys.csv": ["ongoing_tourneys.csv"],
    "challenger_ongoing_tourneys.csv": [
        "challenger_ongoing_tourneys.csv",
        "ch_ongoing_tourney.csv",
        "challenger_ongoing_tourney.csv",
    ],
    "wta_ongoing_tourneys.csv": [
        "wta_ongoing_tourneys.csv",
        "wta_ongoing_tourney.csv",
    ],
}

REQUIRED_COLUMNS = {
    "tourney_id",
    "tourney_date",
    "surface",
    "winner_name",
    "loser_name",
}

LOG_FILE = "v5_refresh_log.jsonl"
SUMMARY_FILE = "v5_refresh_last.json"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def log(project_dir: Path, event: dict):
    event = {"timestamp_utc": utc_now(), **event}
    with (project_dir / LOG_FILE).open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, default=str) + "\n")


def sha256(path: Path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def get_manifest():
    r = requests.get(MANIFEST_URL, timeout=45)
    r.raise_for_status()
    payload = r.json()
    files = payload.get("files")
    if not isinstance(files, list):
        raise RuntimeError("TennisMyLife manifest response did not contain a 'files' list.")
    return files


def manifest_lookup(files):
    lookup = {}
    for f in files:
        if not isinstance(f, dict):
            continue
        name = str(f.get("name", "")).strip()
        url = str(f.get("url", "")).strip()
        if name and url:
            lookup[name.lower()] = {"name": name, "url": url, **f}
    return lookup


def resolve_targets(lookup):
    resolved = {}
    missing = []
    for local_name, aliases in TARGETS.items():
        match = None
        for alias in aliases:
            if alias.lower() in lookup:
                match = lookup[alias.lower()]
                break
        if match:
            resolved[local_name] = match
        else:
            missing.append({"local_name": local_name, "aliases": aliases})
    return resolved, missing


def download_atomic(url: str, dest: Path):
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=dest.name + ".",
        suffix=".download",
        dir=str(dest.parent),
    )
    os.close(fd)
    temp = Path(temp_name)
    try:
        with requests.get(url, stream=True, timeout=120) as r:
            r.raise_for_status()
            with temp.open("wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)
        if temp.stat().st_size == 0:
            raise RuntimeError(f"Downloaded zero-byte file from {url}")
        temp.replace(dest)
    finally:
        if temp.exists():
            temp.unlink(missing_ok=True)


def validate_csv(path: Path, prior_rows: int | None = None):
    # Header validation
    header = pd.read_csv(path, nrows=0, encoding_errors="replace")
    cols = set(header.columns)
    missing_cols = REQUIRED_COLUMNS - cols

    # Count rows without loading all data into memory.
    row_count = 0
    with path.open("r", encoding="utf-8", errors="replace", newline="") as f:
        reader = csv.reader(f)
        next(reader, None)
        for _ in reader:
            row_count += 1

    warnings = []

    if missing_cols:
        # Some ongoing files may be extremely sparse/temporary, but these columns
        # are required by V5's normal ingestion path.
        warnings.append(f"missing required columns: {sorted(missing_cols)}")

    if row_count == 0:
        warnings.append("file has zero data rows")

    # Finished year files should not normally shrink substantially.
    if prior_rows and prior_rows > 100 and row_count < prior_rows * 0.85:
        warnings.append(
            f"row count dropped >15% ({prior_rows:,} -> {row_count:,})"
        )

    return {
        "rows": row_count,
        "columns": len(cols),
        "missing_required_columns": sorted(missing_cols),
        "warnings": warnings,
    }


def prior_row_count(path: Path):
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8", errors="replace", newline="") as f:
            return max(sum(1 for _ in f) - 1, 0)
    except Exception:
        return None


def run_build(project_dir: Path):
    py = sys.executable
    cmd = [py, "-u", "build_v5_states.py", "--dir", "."]
    proc = subprocess.run(
        cmd,
        cwd=project_dir,
        capture_output=True,
        text=True,
    )
    return {
        "returncode": proc.returncode,
        "stdout": proc.stdout[-12000:],
        "stderr": proc.stderr[-12000:],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=".", help="V5 project folder")
    ap.add_argument("--skip-build", action="store_true")
    ap.add_argument("--allow-partial", action="store_true")
    args = ap.parse_args()

    project_dir = Path(args.dir).resolve()
    project_dir.mkdir(parents=True, exist_ok=True)

    summary = {
        "started_utc": utc_now(),
        "status": "RUNNING",
        "files": {},
        "missing_manifest_targets": [],
        "build": None,
    }

    try:
        print("V5 DAILY DATA REFRESH", flush=True)
        print(f"Project: {project_dir}", flush=True)

        print("[1/4] Reading TennisMyLife manifest...", flush=True)
        files = get_manifest()
        lookup = manifest_lookup(files)
        resolved, missing = resolve_targets(lookup)
        summary["missing_manifest_targets"] = missing

        if missing and not args.allow_partial:
            raise RuntimeError(
                "Expected TennisMyLife files were missing from the manifest: "
                + ", ".join(x["local_name"] for x in missing)
            )

        print(f"      Manifest contains {len(files)} files.", flush=True)
        print(f"      Resolved {len(resolved)}/{len(TARGETS)} V5 targets.", flush=True)

        print("[2/4] Downloading current files atomically...", flush=True)
        for local_name, meta in resolved.items():
            dest = project_dir / local_name
            old_rows = prior_row_count(dest)
            print(f"      {meta['name']} -> {local_name}", flush=True)

            download_atomic(meta["url"], dest)
            check = validate_csv(dest, old_rows)

            summary["files"][local_name] = {
                "source_name": meta["name"],
                "source_url": meta["url"],
                "size_bytes": dest.stat().st_size,
                "sha256": sha256(dest),
                **check,
            }

            if check["warnings"]:
                print(
                    f"      WARNING {local_name}: "
                    + "; ".join(check["warnings"]),
                    flush=True,
                )

        hard_warnings = [
            (name, f["warnings"])
            for name, f in summary["files"].items()
            if f["missing_required_columns"] or f["rows"] == 0
        ]

        print("[3/4] Validating refresh...", flush=True)
        if hard_warnings and not args.allow_partial:
            raise RuntimeError(
                "Downloaded data failed validation: "
                + " | ".join(f"{n}: {w}" for n, w in hard_warnings)
            )

        if not args.skip_build:
            print("[4/4] Rebuilding V5 states...", flush=True)
            build = run_build(project_dir)
            summary["build"] = build
            if build["returncode"] != 0:
                raise RuntimeError(
                    "build_v5_states.py failed.\n"
                    + build["stderr"][-4000:]
                )
            print(build["stdout"][-3000:], flush=True)
        else:
            print("[4/4] Build skipped by command-line option.", flush=True)

        summary["status"] = "SUCCESS"
        summary["finished_utc"] = utc_now()
        (project_dir / SUMMARY_FILE).write_text(
            json.dumps(summary, indent=2, default=str),
            encoding="utf-8",
        )
        log(project_dir, {"type": "refresh_success", **summary})
        print("REFRESH COMPLETE", flush=True)
        return 0

    except Exception as exc:
        summary["status"] = "FAILED"
        summary["error"] = str(exc)
        summary["finished_utc"] = utc_now()
        (project_dir / SUMMARY_FILE).write_text(
            json.dumps(summary, indent=2, default=str),
            encoding="utf-8",
        )
        log(project_dir, {"type": "refresh_failure", **summary})
        print(f"REFRESH FAILED: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
