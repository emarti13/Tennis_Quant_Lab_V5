
from __future__ import annotations

import json
import math
import time
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

OUTDIR = Path("oddspapi_relevant_slate")
OUTDIR.mkdir(exist_ok=True)

def _text(fx):
    return " | ".join(
        str(fx.get(k, ""))
        for k in (
            "categoryName",
            "tournamentName",
            "tournamentSlug",
            "leagueName",
            "competitionName",
            "participant1Name",
            "participant2Name",
        )
    ).lower()

def is_doubles(fx):
    text = _text(fx)
    p1 = (fx.get("participant1Name") or "").lower()
    p2 = (fx.get("participant2Name") or "").lower()

    doubles_terms = (
        "doubles",
        "double ",
        "mixed doubles",
    )
    if any(term in text for term in doubles_terms):
        return True

    # Common team-name formatting for tennis doubles.
    if " / " in p1 or " / " in p2:
        return True

    return False

def is_below_required_level(fx):
    text = _text(fx)

    blocked_terms = (
        "itf",
        "utr",
        "srl",
        "simulated reality",
        "exhibition",
        "junior",
        "juniors",
        "boys",
        "girls",
    )
    return any(term in text for term in blocked_terms)

def is_required_level(fx):
    """
    User scope:
      MEN: Challenger and above, including qualifiers.
      WOMEN: WTA 125 and above, including qualifiers.
      Exclude ITF and everything below those levels.
    """

    text = _text(fx)

    if is_doubles(fx) or is_below_required_level(fx):
        return False

    # Men's required levels:
    # ATP main tour, ATP qualifying, ATP Challenger, Challenger qualifying,
    # and Grand Slam men's main/qualifying.
    men_terms = (
        "atp ",
        "atp-",
        "atp challenger",
        "challenger",
    )

    # Women's required levels:
    # WTA main tour, WTA 125, WTA qualifying, and Grand Slam women's main/qualifying.
    women_terms = (
        "wta ",
        "wta-",
        "wta 125",
        "wta125",
    )

    slam_terms = (
        "us open",
        "australian open",
        "roland garros",
        "french open",
        "wimbledon",
    )

    return (
        any(term in text for term in men_terms)
        or any(term in text for term in women_terms)
        or any(term in text for term in slam_terms)
    )

def chunks(items, n=5):
    for i in range(0, len(items), n):
        yield items[i:i+n]

def main():
    client = OddsPapiClient()
    now = datetime.now(timezone.utc)
    end = now + timedelta(hours=24)

    from_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    to_iso = end.strftime("%Y-%m-%dT%H:%M:%SZ")

    print("[1] Pulling next-24h tennis fixtures...")
    fixtures = client.fixtures(
        SPORT_ID,
        from_iso,
        to_iso,
        status_id=0,
        has_odds=True
    )

    if not isinstance(fixtures, list):
        raise RuntimeError(
            f"Unexpected fixtures payload type: {type(fixtures).__name__}"
        )

    relevant = [fx for fx in fixtures if is_required_level(fx)]

    tids = [
        fx.get("tournamentId")
        for fx in relevant
        if fx.get("tournamentId") is not None
    ]
    unique_ids = sorted(set(tids))
    counts = Counter(tids)

    tournament_names = {}
    for fx in relevant:
        tid = fx.get("tournamentId")
        if tid is not None:
            tournament_names[tid] = (
                fx.get("tournamentName")
                or fx.get("competitionName")
                or str(tid)
            )

    batch_list = list(chunks(unique_ids, 5))
    odds_calls = len(batch_list) * len(CORE_BOOKS)
    total_calls = 1 + odds_calls

    report = {
        "captured_at_utc": now.isoformat(),
        "window_from_utc": from_iso,
        "window_to_utc": to_iso,
        "scope": {
            "men": "ATP Challenger and above, including qualifying",
            "women": "WTA 125 and above, including qualifying",
            "excluded": "ITF, UTR, SRL, exhibitions, juniors, doubles, and lower levels",
        },
        "all_tennis_fixture_count": len(fixtures),
        "relevant_fixture_count": len(relevant),
        "relevant_unique_tournament_count": len(unique_ids),
        "tournament_batches_per_book": len(batch_list),
        "core_books": CORE_BOOKS,
        "fixture_discovery_calls": 1,
        "odds_calls": odds_calls,
        "total_calls_for_full_core6_snapshot": total_calls,
        "estimated_30_day_calls_at_this_slate_size": total_calls * 30,
        "tournaments": [
            {
                "tournamentId": tid,
                "tournamentName": tournament_names.get(tid),
                "fixtures_24h": counts[tid],
            }
            for tid in unique_ids
        ],
    }

    Path("oddspapi_relevant_fixture_report.json").write_text(
        json.dumps(report, indent=2, default=str),
        encoding="utf-8"
    )
    Path("oddspapi_relevant_fixtures_24h.json").write_text(
        json.dumps(relevant, indent=2, default=str),
        encoding="utf-8"
    )

    print(f"    All tennis fixtures: {len(fixtures)}")
    print(f"    Required-level singles fixtures: {len(relevant)}")
    print(f"    Relevant tournaments: {len(unique_ids)}")
    print(f"    Batches/book: {len(batch_list)}")
    print(f"    Full Core 6 snapshot calls incl fixtures: {total_calls}")

    # Protect the free tier during testing.
    if total_calls > 8:
        print("[2] Snapshot cost is above the current free-tier test threshold.")
        print("    Skipping six-book odds pull and preserving quota.")
        return 0

    print("[2] Pulling Core 6...")
    manifest = {"report": report, "books": {}}

    for book in CORE_BOOKS:
        manifest["books"][book] = []
        for idx, batch in enumerate(batch_list, start=1):
            print(f"    {book} batch {idx}/{len(batch_list)}: {batch}")
            try:
                payload = client.odds_by_tournaments(
                    batch,
                    bookmaker=book
                )
                fn = OUTDIR / f"{book.replace('.','_')}_batch{idx}.json"
                fn.write_text(
                    json.dumps(payload, indent=2, default=str),
                    encoding="utf-8"
                )
                manifest["books"][book].append({
                    "batch": idx,
                    "tournamentIds": batch,
                    "status": "SUCCESS",
                    "file": str(fn),
                })
            except Exception as exc:
                manifest["books"][book].append({
                    "batch": idx,
                    "tournamentIds": batch,
                    "status": "FAILED",
                    "error": str(exc),
                })
            time.sleep(1.25)

    Path("oddspapi_relevant_core6_manifest.json").write_text(
        json.dumps(manifest, indent=2, default=str),
        encoding="utf-8"
    )

    print("SUCCESS")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
