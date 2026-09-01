from __future__ import annotations
import json, time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from oddspapi_client import OddsPapiClient

SPORT_ID = 12
PRIMARY_BOOK = "pinnacle"
SECONDARY_BOOK = "betrivers"
SECONDARY_EVERY_N_DAYS = 3
OUTDIR = Path("oddspapi_daily")
OUTDIR.mkdir(exist_ok=True)


def text_for(fx):
    return " | ".join(str(fx.get(k, "")) for k in (
        "categoryName", "categorySlug", "tournamentName", "tournamentSlug",
        "participant1Name", "participant2Name"
    )).lower()


def relevant_fixture(fx):
    t = text_for(fx)
    p1 = (fx.get("participant1Name") or "").lower()
    p2 = (fx.get("participant2Name") or "").lower()
    if "doubles" in t or "mixed doubles" in t or " / " in p1 or " / " in p2:
        return False
    if any(x in t for x in ("itf", "utr", "simulated reality", "srl", "junior", "juniors", "exhibition")):
        return False
    men = "challenger" in t or "atp " in t or "atp-" in t
    women = "wta 125" in t or "wta125" in t or "wta " in t or "wta-" in t
    slam = any(x in t for x in ("us open", "australian open", "roland garros", "french open", "wimbledon"))
    return men or women or slam


def chunks(x, n=5):
    for i in range(0, len(x), n):
        yield x[i:i+n]


def books_for_today(now):
    # Free-tier budget target: one primary book every day, a second book every
    # third UTC day. With four tournament batches this averages ~6.3 API calls/day
    # (1 fixtures call + 4 primary calls + 4 secondary calls every third day).
    books = [PRIMARY_BOOK]
    if now.date().toordinal() % SECONDARY_EVERY_N_DAYS == 0:
        books.append(SECONDARY_BOOK)
    return books


def main():
    c = OddsPapiClient()
    now = datetime.now(timezone.utc)
    end = now + timedelta(hours=24)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    f0 = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    f1 = end.strftime("%Y-%m-%dT%H:%M:%SZ")

    fixtures = c.fixtures(SPORT_ID, f0, f1, status_id=0, has_odds=True)
    relevant = [f for f in fixtures if relevant_fixture(f)]
    tids = sorted({f.get("tournamentId") for f in relevant if f.get("tournamentId") is not None})
    batches = list(chunks(tids, 5))
    books = books_for_today(now)

    (OUTDIR / f"{stamp}_fixtures.json").write_text(
        json.dumps(relevant, indent=2, default=str), encoding="utf-8"
    )

    estimated_calls = 1 + len(batches) * len(books)
    manifest = {
        "captured_at_utc": now.isoformat(),
        "window_from_utc": f0,
        "window_to_utc": f1,
        "scope": {
            "men": "Challenger and above, including qualifying",
            "women": "WTA 125 and above, including qualifying",
            "excluded": "ITF, UTR, SRL, exhibitions, juniors, doubles, lower levels",
        },
        "quota_policy": {
            "plan_cap": 250,
            "primary_book": PRIMARY_BOOK,
            "secondary_book": SECONDARY_BOOK,
            "secondary_every_n_days": SECONDARY_EVERY_N_DAYS,
            "target_average_calls_per_day_with_4_batches": 6.33,
        },
        "fixture_count_relevant": len(relevant),
        "tournament_ids": tids,
        "batches_per_book": len(batches),
        "books_today": books,
        "estimated_api_calls_today": estimated_calls,
        "books": {}
    }

    for book in books:
        manifest["books"][book] = []
        for i, batch in enumerate(batches, 1):
            try:
                payload = c.odds_by_tournaments(batch, bookmaker=book)
                fn = OUTDIR / f"{stamp}_{book.replace('.', '_')}_batch{i}.json"
                fn.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
                manifest["books"][book].append({
                    "batch": i,
                    "status": "SUCCESS",
                    "file": str(fn),
                    "tournamentIds": batch,
                })
            except Exception as e:
                manifest["books"][book].append({
                    "batch": i,
                    "status": "FAILED",
                    "error": str(e),
                    "tournamentIds": batch,
                })
            time.sleep(1.25)

    (OUTDIR / f"{stamp}_manifest.json").write_text(
        json.dumps(manifest, indent=2, default=str), encoding="utf-8"
    )
    print(json.dumps({
        "relevant_fixtures": len(relevant),
        "tournaments": len(tids),
        "books": books,
        "estimated_api_calls": estimated_calls,
    }, indent=2))


if __name__ == "__main__":
    main()
