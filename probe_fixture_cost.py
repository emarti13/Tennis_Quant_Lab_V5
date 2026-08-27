
from __future__ import annotations

import json
import math
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from oddspapi_client import OddsPapiClient

SPORT_ID = 12
CORE_BOOKS = [
    "pinnacle",
    "bookmaker.eu",
    "betrivers",
    "draftkings",
    "kalshi",
    "novig.us",
]

def main():
    client = OddsPapiClient()

    now = datetime.now(timezone.utc)
    end = now + timedelta(hours=24)

    from_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    to_iso = end.strftime("%Y-%m-%dT%H:%M:%SZ")

    print("[1] Pulling pre-game tennis fixtures with odds for next 24 hours...")
    print(f"    Window: {from_iso} -> {to_iso}")

    fixtures = client.fixtures(
        sport_id=SPORT_ID,
        date_from=from_iso,
        date_to=to_iso,
        status_id=0,
        has_odds=True,
    )

    if not isinstance(fixtures, list):
        raise RuntimeError(f"Unexpected fixtures payload type: {type(fixtures).__name__}")

    Path("oddspapi_fixtures_24h.json").write_text(
        json.dumps(fixtures, indent=2, default=str),
        encoding="utf-8"
    )

    tids = []
    tournament_names = {}
    for fx in fixtures:
        tid = fx.get("tournamentId")
        if tid is None:
            continue
        tids.append(tid)
        tournament_names[tid] = fx.get("tournamentName") or fx.get("tournamentSlug") or str(tid)

    unique_ids = sorted(set(tids))
    matches_per_tournament = Counter(tids)

    batches = math.ceil(len(unique_ids) / 5) if unique_ids else 0
    core6_odds_calls = batches * len(CORE_BOOKS)

    rows = []
    for tid in unique_ids:
        rows.append({
            "tournamentId": tid,
            "tournamentName": tournament_names.get(tid),
            "fixtures_24h": matches_per_tournament[tid],
        })

    report = {
        "captured_at_utc": now.isoformat(),
        "window_from_utc": from_iso,
        "window_to_utc": to_iso,
        "sport_id": SPORT_ID,
        "fixture_count_24h": len(fixtures),
        "unique_tournament_count_24h": len(unique_ids),
        "max_tournaments_per_odds_request": 5,
        "tournament_batches_required_per_book": batches,
        "core_books": CORE_BOOKS,
        "core_book_count": len(CORE_BOOKS),
        "fixture_discovery_calls": 1,
        "core6_odds_calls_if_all_tournaments": core6_odds_calls,
        "total_calls_for_one_full_snapshot": 1 + core6_odds_calls,
        "estimated_30_day_calls_at_one_full_snapshot_per_day": (1 + core6_odds_calls) * 30,
        "tournaments": rows,
    }

    Path("oddspapi_fixture_cost_report.json").write_text(
        json.dumps(report, indent=2, default=str),
        encoding="utf-8"
    )

    print(f"[2] Fixtures in next 24h: {len(fixtures)}")
    print(f"[3] Unique tournaments: {len(unique_ids)}")
    print(f"[4] Odds batches/book at max 5 IDs: {batches}")
    print(f"[5] Core 6 odds calls for one full snapshot: {core6_odds_calls}")
    print(f"[6] Total calls including fixture discovery: {1 + core6_odds_calls}")
    print(f"[7] 30-day estimate at this exact slate size: {(1 + core6_odds_calls) * 30}")
    print("")
    print("TOURNAMENTS:")
    for row in rows:
        print(f"    {row['tournamentId']}: {row['tournamentName']} ({row['fixtures_24h']} fixtures)")
    print("")
    print("SUCCESS")
    print("Saved oddspapi_fixtures_24h.json")
    print("Saved oddspapi_fixture_cost_report.json")

if __name__ == "__main__":
    main()
