"""Manifest for a research run: input fingerprints, code version, seeds, package versions, so
anyone can rerun one command and get the same numbers."""
from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from importlib import metadata
from pathlib import Path

import pandas as pd


def sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    p = Path(path)
    files = sorted(x for x in p.rglob("*") if x.is_file() and ".git" not in x.parts) if p.is_dir() else [p]
    for f in files:
        h.update(str(f.relative_to(p) if p.is_dir() else f.name).encode())
        with open(f, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    return h.hexdigest()


def manifest(inputs: dict[str, str], seeds: dict, command: str) -> dict:
    def ver(p):
        try:
            return metadata.version(p)
        except metadata.PackageNotFoundError:
            return None
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10).stdout.strip()
        dirty = bool(subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, timeout=10).stdout.strip())
    except (OSError, subprocess.SubprocessError):
        commit, dirty = None, None
    return {"run_utc": pd.Timestamp.now(tz="UTC").isoformat(), "command": command, "git_commit": commit,
            "uncommitted_changes": dirty, "python": platform.python_version(),
            "packages": {p: ver(p) for p in ("pandas", "numpy", "scikit-learn", "lightgbm", "scipy")},
            "seeds": seeds, "inputs": {k: {"path": v, "sha256": sha256(v)} for k, v in inputs.items()}}


def write(path: str | Path, obj: dict) -> None:
    Path(path).write_text(json.dumps(obj, indent=1, default=str) + "\n")
