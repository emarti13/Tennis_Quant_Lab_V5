from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from pathlib import Path

BOARD = Path("v5_daily_ready/latest_board.csv")
OUT = Path("v5_daily_ready/slam_market_range_diagnostic.json")


def num(value):
    try:
        x = float(value)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def is_mens_slam(row):
    tour = str(row.get("tour_v5") or row.get("tour") or "").upper()
    if tour not in {"MEN", "ATP"}:
        return False
    t = str(row.get("tournament") or "").lower()
    return any(name in t for name in ("australian open", "french open", "roland garros", "wimbledon", "us open"))


def main():
    with BOARD.open(encoding="utf-8-sig", newline="") as f:
        rows = [r for r in csv.DictReader(f) if is_mens_slam(r)]

    stats = {}
    for group in ("moneyline", "game_spread", "total_games"):
        g = [r for r in rows if r.get("market_group") == group]
        lines = [num(r.get("line")) for r in g]
        lines = [x for x in lines if x is not None]
        priced = [r for r in g if num(r.get("model_probability")) is not None]
        stats[group] = {
            "rows": len(g),
            "fixtures": len({r.get("fixture_id") for r in g}),
            "priced_rows": len(priced),
            "unpriced_rows": len(g) - len(priced),
            "line_min": min(lines) if lines else None,
            "line_max": max(lines) if lines else None,
            "max_abs_line": max((abs(x) for x in lines), default=None),
            "distinct_lines": sorted(set(lines)),
        }

    result = {
        "mens_slam_rows": len(rows),
        "mens_slam_fixtures": len({r.get("fixture_id") for r in rows}),
        "board_has_best_of_column": bool(rows and "best_of" in rows[0]),
        "market_groups": stats,
    }
    OUT.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
