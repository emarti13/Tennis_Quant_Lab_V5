"""Daily: rebuild the tournament crosswalks and player tables, then raise flags.

Usage:  python scripts/refresh_identity.py [--as-of YYYY-MM-DD]

For each recent season with a master schedule sheet, runs
scripts/reconcile_master_schedule.py, then scripts/build_player_registry.py. Stored rows
marked confirmed, user or rejected are never changed. Writes
context_registry/identity_status.json with the flags a person should act on (decision D6:
"the system must raise flags when an update is needed"):

- SCHEDULE_MISSING: no master_schedule_<year>.csv for the current season, or for next
  season within 30 days of New Year.
- UPCOMING_UNMATCHED: OddsPapi tournaments starting in the next 14 days that match no
  edition (a missing or misdated sheet row; their fixtures get no price).
- MAPPING_ORPHANED: stored mappings that point at editions no longer in the sheet.
- REVIEW_OPEN: tournament or player questions waiting for a decision.
Exit code is 0 even with flags; flags are for a person, not a failed run.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from v5_season_files import current_season_year, recent_season_years  # noqa: E402

MS = BASE / "context_registry" / "master_schedule"
PLAYERS = BASE / "context_registry" / "players"
STATUS = BASE / "context_registry" / "identity_status.json"
UPCOMING_DAYS = 14


def _run(*args: str) -> None:
    print("+", " ".join(args), flush=True)
    subprocess.run([sys.executable, *args], cwd=BASE, check=True)


def _read(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False) if path.exists() else pd.DataFrame()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--as-of", default=None)
    args = ap.parse_args()
    now = datetime.now(timezone.utc)
    as_of = args.as_of or now.date().isoformat()
    flags = []

    season = current_season_year(now)
    years = [y for y in recent_season_years(now) if (MS / f"master_schedule_{y}.csv").exists()]
    if not (MS / f"master_schedule_{season}.csv").exists():
        flags.append({"flag": "SCHEDULE_MISSING", "detail": f"no master_schedule_{season}.csv: fixtures in {season} get no price"})
    if (date(season + 1, 1, 1) - now.date()).days <= 30 and not (MS / f"master_schedule_{season + 1}.csv").exists():
        flags.append({"flag": "SCHEDULE_MISSING", "detail": f"master_schedule_{season + 1}.csv is needed by January 1"})

    for year in years:
        _run("scripts/reconcile_master_schedule.py", "--sheet", f"context_registry/master_schedule/master_schedule_{year}.csv",
             "--year", str(year), "--as-of", as_of)
    if years:
        _run("scripts/build_player_registry.py", "--year", str(max(years)), "--as-of", as_of)

    # Upcoming OddsPapi tournaments that match no edition.
    for year in years:
        om = _read(MS / "reconciliation" / str(year) / "oddspapi_matches.csv")
        if om.empty:
            continue
        first = pd.to_datetime(om["first_date"], errors="coerce").dt.date
        soon = om[(om["status"] != "matched") & (first >= now.date() - timedelta(days=2))
                  & (first <= now.date() + timedelta(days=UPCOMING_DAYS))]
        for r in soon.itertuples():
            flags.append({"flag": "UPCOMING_UNMATCHED", "detail": f"{r.source_name} from {r.first_date}: {r.status}",
                          "candidates": r.candidates})

    xw = pd.concat([_read(MS / "crosswalk_oddspapi.csv"), _read(MS / "crosswalk_tennismylife.csv")], ignore_index=True)
    editions = set()
    for year in years:
        ms = _read(MS / "reconciliation" / str(year) / "master_schedule.csv")
        editions |= set(ms.get("edition_key", []))
    if not xw.empty:
        orphan = xw[(xw["edition_key"] != "") & ~xw["edition_key"].isin(editions)]
        for r in orphan.itertuples():
            flags.append({"flag": "MAPPING_ORPHANED", "detail": f"{r.source} {r.source_id} -> {r.edition_key}"})
        held = xw[xw["status"] == "review"]
        for r in held.itertuples():
            flags.append({"flag": "REVIEW_OPEN", "detail": f"tournament {r.source} {r.source_id} {r.source_name}: {r.note}"})
    review = _read(PLAYERS / "review.csv")
    open_p = int(review["kind"].isin(["tennismylife_ids", "oddspapi_participant"]).sum()) if not review.empty else 0
    if open_p:
        flags.append({"flag": "REVIEW_OPEN", "detail": f"{open_p} player questions"})

    odds = _read(PLAYERS / "alias_oddspapi.csv")
    payload = {
        "generated_utc": now.isoformat(timespec="seconds"), "as_of": as_of, "season": season,
        "schedule_years": years,
        "tournament_mappings": xw["status"].value_counts().to_dict() if not xw.empty else {},
        "oddspapi_players": odds["status"].value_counts().to_dict() if not odds.empty else {},
        "flags": flags,
    }
    STATUS.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"identity status: {len(flags)} flag(s)")
    for f in flags:
        print(f"  {f['flag']}: {f['detail']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
