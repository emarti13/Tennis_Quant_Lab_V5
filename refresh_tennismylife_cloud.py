
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import requests

MANIFEST_URL = "https://stats.tennismylife.org/api/data-files"
CURRENT_YEAR = datetime.now(timezone.utc).year

TARGETS = {
    f"{CURRENT_YEAR}.csv": [f"{CURRENT_YEAR}.csv"],
    f"{CURRENT_YEAR}_atp_quali.csv": [f"{CURRENT_YEAR}_atp_quali.csv"],
    f"{CURRENT_YEAR}_challenger.csv": [f"{CURRENT_YEAR}_challenger.csv"],
    f"{CURRENT_YEAR}_wta.csv": [f"{CURRENT_YEAR}_wta.csv"],
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

ONGOING_FILES = {
    "ongoing_tourneys.csv",
    "challenger_ongoing_tourneys.csv",
    "wta_ongoing_tourneys.csv",
}

REQUIRED_COLUMNS = {
    "tourney_id",
    "tourney_date",
    "surface",
    "winner_name",
    "loser_name",
}

SUMMARY_FILE = "v5_refresh_last.json"
LOG_FILE = "v5_refresh_log.jsonl"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def row_count(path: Path):
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8", errors="replace", newline="") as f:
        return max(sum(1 for _ in f) - 1, 0)


def log(project_dir: Path, event: dict):
    event = {"timestamp_utc": utc_now(), **event}
    with (project_dir / LOG_FILE).open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, default=str) + "\n")


def get_manifest():
    r = requests.get(MANIFEST_URL, timeout=45)
    r.raise_for_status()
    data = r.json()
    files = data.get("files")
    if not isinstance(files, list):
        raise RuntimeError("TennisMyLife manifest did not contain a files list.")
    return files


def manifest_lookup(files):
    lookup = {}
    for item in files:
        if not isinstance(item, dict):
            continue

        name = str(item.get("name", "")).strip()
        url = str(item.get("url", "")).strip()
        if not name or not url:
            continue

        enriched = {"name": name, "url": url, **item}

        norm = name.replace("\\", "/").lower()
        lookup[norm] = enriched
        lookup[norm.split("/")[-1]] = enriched

        urlbase = Path(urlparse(url).path).name.lower()
        if urlbase:
            lookup[urlbase] = enriched

    return lookup


def resolve_targets(lookup):
    resolved = {}
    missing = []

    for local_name, aliases in TARGETS.items():
        found = None
        for alias in aliases:
            key = alias.replace("\\", "/").lower()
            if key in lookup:
                found = lookup[key]
                break
            base = key.split("/")[-1]
            if base in lookup:
                found = lookup[base]
                break

        if found:
            resolved[local_name] = found
        else:
            missing.append(local_name)

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
                for chunk in r.iter_content(1024 * 1024):
                    if chunk:
                        f.write(chunk)

        if temp.stat().st_size == 0:
            raise RuntimeError(f"Zero-byte download: {url}")

        temp.replace(dest)
    finally:
        temp.unlink(missing_ok=True)


def validate_csv(path: Path, prior_rows: int | None, ongoing: bool):
    header = pd.read_csv(path, nrows=0)
    cols = set(header.columns)
    missing_cols = sorted(REQUIRED_COLUMNS - cols)
    rows = row_count(path) or 0
    warnings = []

    if missing_cols:
        warnings.append(f"missing required columns: {missing_cols}")

    if rows == 0 and not ongoing:
        warnings.append("current-season file has zero rows")

    if not ongoing and prior_rows and prior_rows > 100 and rows < prior_rows * 0.85:
        warnings.append(f"suspicious row-count drop >15% ({prior_rows:,} -> {rows:,})")

    hard_fail = bool(missing_cols) or (rows == 0 and not ongoing)

    return {
        "rows": rows,
        "columns": len(cols),
        "missing_required_columns": missing_cols,
        "warnings": warnings,
        "hard_fail": hard_fail,
    }


def run_build(project_dir: Path):
    build = project_dir / "build_v5_states.py"
    if not build.exists():
        raise RuntimeError("build_v5_states.py is missing.")

    proc = subprocess.run(
        [sys.executable, "-u", build.name, "--dir", "."],
        cwd=project_dir,
        capture_output=True,
        text=True,
    )

    print(proc.stdout[-12000:], flush=True)
    if proc.stderr:
        print(proc.stderr[-12000:], file=sys.stderr, flush=True)

    if proc.returncode != 0:
        raise RuntimeError(f"build_v5_states.py failed with exit code {proc.returncode}")

    return {
        "returncode": proc.returncode,
        "stdout_tail": proc.stdout[-12000:],
        "stderr_tail": proc.stderr[-12000:],
    }


def verify_outputs(project_dir: Path):
    required = [
        project_dir / "v5_men_ratings.csv",
        project_dir / "v5_wta_ratings.csv",
    ]

    result = {}
    for p in required:
        if not p.exists():
            raise RuntimeError(f"Missing rating output: {p.name}")
        rows = row_count(p)
        if rows is None or rows == 0:
            raise RuntimeError(f"Rating output is empty: {p.name}")
        result[p.name] = {
            "rows": rows,
            "size_bytes": p.stat().st_size,
            "sha256": sha256(p),
        }
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=".")
    args = ap.parse_args()

    project_dir = Path(args.dir).resolve()
    summary = {
        "started_utc": utc_now(),
        "year": CURRENT_YEAR,
        "status": "RUNNING",
        "files": {},
        "build": None,
        "outputs": {},
    }

    try:
        print("[1/4] Reading TennisMyLife manifest...", flush=True)
        lookup = manifest_lookup(get_manifest())
        resolved, missing = resolve_targets(lookup)

        if missing:
            raise RuntimeError(
                "TennisMyLife manifest is missing required current files: "
                + ", ".join(missing)
            )

        print("[2/4] Downloading current-year and ongoing files...", flush=True)
        hard_failures = []

        for local_name, meta in resolved.items():
            dest = project_dir / local_name
            before = row_count(dest)

            print(f"  {meta['name']} -> {local_name}", flush=True)
            download_atomic(meta["url"], dest)

            check = validate_csv(
                dest,
                prior_rows=before,
                ongoing=(local_name in ONGOING_FILES),
            )

            summary["files"][local_name] = {
                "source_name": meta["name"],
                "prior_rows": before,
                "size_bytes": dest.stat().st_size,
                "sha256": sha256(dest),
                **check,
            }

            print(
                f"    rows: {before if before is not None else 'new'} -> {check['rows']:,}",
                flush=True,
            )

            if check["hard_fail"]:
                hard_failures.append(
                    f"{local_name}: " + "; ".join(check["warnings"])
                )

        if hard_failures:
            raise RuntimeError("Source validation failed: " + " | ".join(hard_failures))

        print("[3/4] Rebuilding V5 player states/ratings...", flush=True)
        summary["build"] = run_build(project_dir)

        print("[4/4] Verifying V5 rating outputs...", flush=True)
        summary["outputs"] = verify_outputs(project_dir)

        summary["status"] = "SUCCESS"
        summary["finished_utc"] = utc_now()

        (project_dir / SUMMARY_FILE).write_text(
            json.dumps(summary, indent=2, default=str),
            encoding="utf-8",
        )
        log(project_dir, {"type": "refresh_success", **summary})

        print("PLAYER REFRESH COMPLETE", flush=True)
        for name, info in summary["outputs"].items():
            print(f"  {name}: {info['rows']:,} rows", flush=True)

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

        print(f"PLAYER REFRESH FAILED: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
