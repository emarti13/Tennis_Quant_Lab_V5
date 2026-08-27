
from __future__ import annotations

import json
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from oddspapi_client import OddsPapiClient

SPORT_ID = 12
ALWAYS_BOOKS = ["pinnacle", "betrivers"]
ROTATING_BOOKS = ["draftkings", "bookmaker.eu", "kalshi", "novig.us"]

OUTDIR = Path("oddspapi_daily")
OUTDIR.mkdir(exist_ok=True)

def text_for(fx):
    return " | ".join(
        str(fx.get(k, ""))
        for k in (
            "categoryName",
            "categorySlug",
            "tournamentName",
            "tournamentSlug",
            "participant1Name",
            "participant2Name",
        )
    ).lower()

def relevant_fixture(fx):
    text = text_for(fx)
    p1=(fx.get("participant1Name") or "").lower()
    p2=(fx.get("participant2Name") or "").lower()

    # Singles only.
    if "doubles" in text or "mixed doubles" in text or " / " in p1 or " / " in p2:
        return False

    # Explicitly exclude below-scope / non-real-match products.
    for term in ("itf", "utr", "simulated reality", "srl", "junior", "juniors", "exhibition"):
        if term in text:
            return False

    # MEN: Challenger and above, including qualifiers.
    men_ok = (
        "challenger" in text
        or "atp " in text
        or "atp-" in text
    )

    # WOMEN: WTA 125 and above, including qualifiers.
    women_ok = (
        "wta 125" in text
        or "wta125" in text
        or "wta " in text
        or "wta-" in text
    )

    # Grand Slams can be labelled without ATP/WTA in tournament names.
    slam_ok = any(
        x in text for x in (
            "us open",
            "australian open",
            "roland garros",
            "french open",
            "wimbledon",
        )
    )

    return men_ok or women_ok or slam_ok

def chunks(items, n=5):
    for i in range(0, len(items), n):
        yield items[i:i+n]

def rotating_book_for_date(now_utc):
    # Deterministic 4-day cycle. GitHub reruns on the same UTC date use the same book.
    idx = now_utc.date().toordinal() % len(ROTATING_BOOKS)
    return ROTATING_BOOKS[idx]

def main():
    client = OddsPapiClient()
    now = datetime.now(timezone.utc)
    end = now + timedelta(hours=24)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")

    from_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    to_iso = end.strftime("%Y-%m-%dT%H:%M:%SZ")

    print("[1] Fixture discovery")
    fixtures = client.fixtures(SPORT_ID, from_iso, to_iso, status_id=0, has_odds=True)
    if not isinstance(fixtures, list):
        raise RuntimeError(f"Unexpected fixtures response: {type(fixtures).__name__}")

    relevant = [f for f in fixtures if relevant_fixture(f)]
    tids = sorted({f.get("tournamentId") for f in relevant if f.get("tournamentId") is not None})
    batches = list(chunks(tids, 5))

    rotate = rotating_book_for_date(now)
    books = ALWAYS_BOOKS + [rotate]

    estimated_calls = 1 + len(batches) * len(books)

    print(f"    all tennis fixtures: {len(fixtures)}")
    print(f"    relevant fixtures: {len(relevant)}")
    print(f"    relevant tournaments: {len(tids)}")
    print(f"    batches/book: {len(batches)}")
    print(f"    books today: {books}")
    print(f"    API calls today: {estimated_calls}")

    manifest = {
        "captured_at_utc": now.isoformat(),
        "window_from_utc": from_iso,
        "window_to_utc": to_iso,
        "scope": {
            "men": "Challenger and above, including qualifying",
            "women": "WTA 125 and above, including qualifying",
            "excluded": "ITF, UTR, SRL, exhibitions, juniors, doubles, lower levels",
        },
        "fixture_count_all_tennis": len(fixtures),
        "fixture_count_relevant": len(relevant),
        "tournament_ids": tids,
        "batches_per_book": len(batches),
        "books_today": books,
        "rotating_book_today": rotate,
        "estimated_api_calls_today": estimated_calls,
        "books": {},
    }

    Path(OUTDIR / f"{stamp}_fixtures.json").write_text(
        json.dumps(relevant, indent=2, default=str), encoding="utf-8"
    )

    print("[2] Odds pulls")
    for book in books:
        manifest["books"][book] = []
        for i, batch in enumerate(batches, start=1):
            print(f"    {book}: batch {i}/{len(batches)} {batch}")
            try:
                payload = client.odds_by_tournaments(batch, bookmaker=book)
                fn = OUTDIR / f"{stamp}_{book.replace('.','_')}_batch{i}.json"
                fn.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
                manifest["books"][book].append({
                    "batch": i, "tournamentIds": batch, "status": "SUCCESS", "file": str(fn)
                })
            except Exception as exc:
                manifest["books"][book].append({
                    "batch": i, "tournamentIds": batch, "status": "FAILED", "error": str(exc)
                })
                print(f"      FAILED: {exc}")
            time.sleep(1.25)

    Path(OUTDIR / f"{stamp}_manifest.json").write_text(
        json.dumps(manifest, indent=2, default=str), encoding="utf-8"
    )

    print("[3] COMPLETE")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
