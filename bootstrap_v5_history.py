
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import requests

MANIFEST_URL = "https://stats.tennismylife.org/api/data-files"

HISTORICAL_FILES = [
    "ATP.csv",
    "ATPQualifiers.csv",
    "Challenger.csv",
    "WTA.csv",
]

def manifest():
    r = requests.get(MANIFEST_URL, timeout=60)
    r.raise_for_status()
    data = r.json()
    files = data.get("files")
    if not isinstance(files, list):
        raise RuntimeError("TennisMyLife manifest did not return a files list.")
    return {
        str(x.get("name","")).strip().lower(): x
        for x in files
        if isinstance(x,dict) and x.get("name") and x.get("url")
    }

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
        with requests.get(url, stream=True, timeout=180) as r:
            r.raise_for_status()
            with temp.open("wb") as f:
                for chunk in r.iter_content(1024 * 1024):
                    if chunk:
                        f.write(chunk)
        if temp.stat().st_size == 0:
            raise RuntimeError(f"Downloaded zero bytes for {dest.name}")
        temp.replace(dest)
    finally:
        temp.unlink(missing_ok=True)

def main():
    lookup = manifest()
    cache = Path(".v5_history_cache")
    cache.mkdir(exist_ok=True)

    for name in HISTORICAL_FILES:
        cached = cache / name
        root = Path(name)

        if not cached.exists():
            item = lookup.get(name.lower())
            if not item:
                raise RuntimeError(f"{name} not found in TennisMyLife manifest.")
            print(f"Downloading historical bootstrap: {name}")
            download_atomic(item["url"], cached)
        else:
            print(f"Using cached historical file: {name}")

        # Copy cached file into repo working root for build_v5_states.py.
        # These root copies are ephemeral and are intentionally NOT committed.
        root.write_bytes(cached.read_bytes())
        print(f"Prepared {name}: {root.stat().st_size:,} bytes")

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
