from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from context_warehouse.io import write_warehouse
from context_warehouse.normalize import build_player_match_rows, canonicalize_matches


def parse_input_spec(value: str) -> tuple[str, str, Path]:
    parts = value.split(":", 2)
    if len(parts) != 3 or not all(parts[:2]) or not parts[2]:
        raise argparse.ArgumentTypeError(
            "--input must use TOUR:LEVEL:PATH, for example MEN:ATP:ATP.csv"
        )
    tour, level, path = parts
    return tour.upper(), level.upper(), Path(path)


def load_source(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(
            path,
            low_memory=False,
            encoding="utf-8-sig",
            encoding_errors="replace",
        )
    except (IndexError, UnicodeError):
        return pd.read_csv(
            path,
            engine="python",
            encoding="utf-8-sig",
            encoding_errors="replace",
        )


def build_from_inputs(
    input_specs: list[tuple[str, str, Path]], output_dir: Path
) -> dict:
    canonical_frames = []
    manifest = []

    for tour, level, path in input_specs:
        if not path.exists():
            raise FileNotFoundError(f"Input file not found: {path}")
        raw = load_source(path)
        canonical = canonicalize_matches(
            raw,
            tour=tour,
            level=level,
            source_name=path.name,
        )
        canonical_frames.append(canonical)
        manifest.append(
            {
                "source_name": path.name,
                "source_path": str(path),
                "tour": tour,
                "level": level,
                "input_rows": int(len(raw)),
                "canonical_rows": int(len(canonical)),
            }
        )

    if canonical_frames:
        matches = pd.concat(canonical_frames, ignore_index=True)
        matches = matches.drop_duplicates(subset=["match_id"], keep="last").reset_index(drop=True)
    else:
        matches = canonicalize_matches(
            pd.DataFrame(), tour="", level="", source_name=""
        )

    player_rows = build_player_match_rows(matches)
    summary = write_warehouse(matches, player_rows, output_dir, manifest)
    summary["sources"] = len(manifest)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the Stage 1 canonical tennis context warehouse."
    )
    parser.add_argument(
        "--input",
        action="append",
        type=parse_input_spec,
        required=True,
        help="Source in TOUR:LEVEL:PATH form; repeat for multiple files.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("context_warehouse_output"),
    )
    args = parser.parse_args(argv)

    summary = build_from_inputs(args.input, args.output_dir)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
