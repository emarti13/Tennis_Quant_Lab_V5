"""List the files in docs/Research and whether docs/Research/DIGEST.md covers each one.

A file counts as covered when its exact name appears in backticks in the digest. Exit code
is 0 either way (new uploads are normal); this is a to-do list, not a check that fails CI.

Run: python scripts/research_digest_status.py
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "docs" / "Research"
SKIP = {"DIGEST.md"}


def status() -> list[tuple[str, bool]]:
    digest = (FOLDER / "DIGEST.md").read_text(encoding="utf-8") if (FOLDER / "DIGEST.md").exists() else ""
    files = sorted(p.name for p in FOLDER.iterdir() if p.is_file() and p.name not in SKIP)
    return [(name, f"`{name}`" in digest) for name in files]


def main() -> None:
    rows = status()
    todo = [n for n, ok in rows if not ok]
    for name, ok in rows:
        print(f"{'covered' if ok else 'NEW    '}  {name}")
    print(f"\n{len(rows) - len(todo)} covered, {len(todo)} not yet in DIGEST.md")


if __name__ == "__main__":
    main()
