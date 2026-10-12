
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import requests

from v5_season_files import HISTORY_START_YEAR, history_end_year

MANIFEST_URL = "https://stats.tennismylife.org/api/data-files"
START_YEAR = HISTORY_START_YEAR
END_YEAR = history_end_year()
COVERAGE_FILE = "coverage.json"

OUTPUTS = {
    "ATP.csv": "atp_main",
    "ATPQualifiers.csv": "atp_quali",
    "Challenger.csv": "challenger",
    "WTA.csv": "wta",
}


def fetch_manifest():
    r = requests.get(MANIFEST_URL, timeout=60)
    r.raise_for_status()
    data = r.json()
    files = data.get("files")
    if not isinstance(files, list):
        raise RuntimeError("TennisMyLife manifest did not return a files list.")
    return files


def basename_for(item):
    name = str(item.get("name", "")).replace("\\", "/").strip()
    if name:
        return name.split("/")[-1].lower()
    url = str(item.get("url", "")).strip()
    return Path(urlparse(url).path).name.lower()


def classify(item):
    b = basename_for(item)

    m = re.fullmatch(r"(\d{4})\.csv", b)
    if m:
        return int(m.group(1)), "atp_main"

    m = re.fullmatch(r"(\d{4})_atp_quali\.csv", b)
    if m:
        return int(m.group(1)), "atp_quali"

    m = re.fullmatch(r"(\d{4})_challenger\.csv", b)
    if m:
        return int(m.group(1)), "challenger"

    m = re.fullmatch(r"(\d{4})_wta\.csv", b)
    if m:
        return int(m.group(1)), "wta"

    return None, None


def download_csv(url: str, dest: Path):
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix="tml.", suffix=".csv", dir=str(dest.parent))
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        with requests.get(url, stream=True, timeout=180) as r:
            r.raise_for_status()
            with tmp.open("wb") as f:
                for chunk in r.iter_content(1024 * 1024):
                    if chunk:
                        f.write(chunk)
        if tmp.stat().st_size == 0:
            raise RuntimeError(f"Zero-byte TennisMyLife download: {url}")
        tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)


def build_aggregate(items, output_path: Path, label: str):
    pieces = []
    temp_dir = output_path.parent / "_yearly_tmp"
    temp_dir.mkdir(exist_ok=True)

    for year, item in sorted(items, key=lambda x: x[0]):
        url = item.get("url")
        if not url:
            raise RuntimeError(f"{label} {year} has no URL in manifest.")

        local = temp_dir / f"{label}_{year}.csv"
        print(f"  downloading {label} {year}: {basename_for(item)}", flush=True)
        download_csv(str(url), local)

        frame = pd.read_csv(local, low_memory=False)
        pieces.append(frame)
        local.unlink(missing_ok=True)

    if not pieces:
        raise RuntimeError(f"No yearly source files found for {label}.")

    combined = pd.concat(pieces, ignore_index=True, sort=False)

    dedupe_cols = [
        c for c in ("tourney_id", "match_num", "winner_name", "loser_name")
        if c in combined.columns
    ]
    if dedupe_cols:
        combined = combined.drop_duplicates(dedupe_cols, keep="last")

    combined.to_csv(output_path, index=False)
    print(
        f"  built {output_path.name}: {len(combined):,} rows "
        f"({output_path.stat().st_size / 1024 / 1024:.1f} MB)",
        flush=True,
    )

    try:
        temp_dir.rmdir()
    except OSError:
        pass


def copy_chunked(src: Path, dst: Path):
    with src.open("rb") as fi, dst.open("wb") as fo:
        while True:
            chunk = fi.read(1024 * 1024)
            if not chunk:
                break
            fo.write(chunk)


def read_coverage(cache: Path) -> dict:
    try:
        payload = json.loads((cache / COVERAGE_FILE).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def cache_is_current(cache: Path) -> bool:
    """True only if all aggregates exist and cover START_YEAR..END_YEAR.

    A cache built last year (or before coverage was recorded) is rebuilt, so
    the season that just ended moves from the refresh files into history
    instead of silently disappearing at the new year.
    """
    if not all((cache / name).exists() and (cache / name).stat().st_size > 0 for name in OUTPUTS):
        return False
    coverage = read_coverage(cache)
    return coverage.get("start_year") == START_YEAR and coverage.get("end_year") == END_YEAR


def main():
    cache = Path(".v5_history_cache")
    cache.mkdir(exist_ok=True)

    if cache_is_current(cache):
        print(
            f"Historical V5 cache already covers {START_YEAR}-{END_YEAR} for all four aggregates.",
            flush=True,
        )
    else:
        print(
            f"Building historical aggregates from TennisMyLife yearly files "
            f"({START_YEAR}-{END_YEAR})...",
            flush=True,
        )
        manifest = fetch_manifest()
        groups = {kind: [] for kind in OUTPUTS.values()}

        for item in manifest:
            if not isinstance(item, dict):
                continue
            year, kind = classify(item)
            if kind and year is not None and START_YEAR <= year <= END_YEAR:
                groups[kind].append((year, item))

        for kind, vals in groups.items():
            years = sorted(y for y, _ in vals)
            print(f"{kind}: {years}", flush=True)
            if not years:
                raise RuntimeError(f"No TennisMyLife yearly files discovered for {kind}.")
            if years[-1] != END_YEAR:
                raise RuntimeError(
                    f"TennisMyLife has no {END_YEAR} file for {kind} yet; "
                    "refusing to build history that skips a season."
                )

        for output_name, kind in OUTPUTS.items():
            build_aggregate(groups[kind], cache / output_name, kind)

        (cache / COVERAGE_FILE).write_text(
            json.dumps({"start_year": START_YEAR, "end_year": END_YEAR}, indent=2) + "\n",
            encoding="utf-8",
        )

    for name in OUTPUTS:
        src = cache / name
        if not src.exists() or src.stat().st_size == 0:
            raise RuntimeError(f"Historical cache output missing: {name}")
        dst = Path(name)
        copy_chunked(src, dst)
        print(f"Prepared {name}: {dst.stat().st_size / 1024 / 1024:.1f} MB", flush=True)

    print("Historical bootstrap complete.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
