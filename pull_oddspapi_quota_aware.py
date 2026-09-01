from __future__ import annotations
import json, time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from oddspapi_client import OddsPapiClient
from oddspapi_fixture_registry import FixtureRegistry

SPORT_ID = 12
PRIMARY_BOOK = "pinnacle"
SECONDARY_BOOK = "betrivers"
PROTECTED_RESERVE = 50
SECONDARY_MIN_REMAINING = 100
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


def quota_state(account):
    subscriptions = account.get("subscriptions") or []
    current_id = account.get("current_subscription_id")
    current = None
    for sub in subscriptions:
        if current_id and sub.get("subscription_id") == current_id:
            current = sub
            break
    if current is None:
        current = next((s for s in subscriptions if s.get("is_active")), None)
    if current is None:
        raise RuntimeError("No active OddsPapi subscription found in /v4/account response.")
    limit = int(current.get("request_limit") or 0)
    used = int(current.get("request_count") or 0)
    return {
        "limit": limit,
        "used": used,
        "remaining": max(0, limit - used),
        "valid_from": current.get("valid_from"),
        "valid_until": current.get("valid_until"),
    }


def tournament_request_groups(tournament_ids):
    tids = list(tournament_ids)
    return [tids] if tids else []


def books_for_today(now, remaining):
    if remaining <= PROTECTED_RESERVE:
        return []
    books = [PRIMARY_BOOK]
    if now.weekday() == 6 and remaining >= SECONDARY_MIN_REMAINING:
        books.append(SECONDARY_BOOK)
    return books


def main():
    c = OddsPapiClient()
    now = datetime.now(timezone.utc)
    end = now + timedelta(hours=24)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    f0 = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    f1 = end.strftime("%Y-%m-%dT%H:%M:%SZ")

    quota_before = quota_state(c.account())
    books = books_for_today(now, quota_before["remaining"])

    if not books:
        manifest = {
            "captured_at_utc": now.isoformat(),
            "status": "SKIPPED_QUOTA_RESERVE",
            "quota_before": quota_before,
            "protected_reserve": PROTECTED_RESERVE,
            "estimated_billable_calls_today": 0,
        }
        (OUTDIR / f"{stamp}_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(json.dumps(manifest, indent=2))
        return

    fixtures = c.fixtures(SPORT_ID, f0, f1, status_id=0, has_odds=True)
    relevant = [f for f in fixtures if relevant_fixture(f)]

    # Permanent invariant: every relevant OddsPapi fixture ID we ever see is
    # persisted before any downstream pricing/normalization work happens.
    registry_result = FixtureRegistry().upsert(
        relevant,
        observed_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        source="live_daily",
    )

    tids = sorted({f.get("tournamentId") for f in relevant if f.get("tournamentId") is not None})
    groups = tournament_request_groups(tids)

    (OUTDIR / f"{stamp}_fixtures.json").write_text(
        json.dumps(relevant, indent=2, default=str), encoding="utf-8"
    )

    estimated_calls = 1 + len(groups) * len(books)
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
            "billing_rule": "one billable endpoint call = one request regardless of response size",
            "historical_odds": "free but blocked if total quota is exhausted",
            "protected_reserve": PROTECTED_RESERVE,
            "primary_book": PRIMARY_BOOK,
            "secondary_book": SECONDARY_BOOK,
            "secondary_schedule": "Sunday UTC only when remaining quota >= 100",
            "normal_live_cost": 2,
            "weekly_secondary_cost": 3,
        },
        "quota_before": quota_before,
        "fixture_registry": registry_result,
        "fixture_count_relevant": len(relevant),
        "tournament_ids": tids,
        "odds_requests_per_book": len(groups),
        "books_today": books,
        "estimated_billable_calls_today": estimated_calls,
        "books": {}
    }

    for book in books:
        manifest["books"][book] = []
        for i, group in enumerate(groups, 1):
            try:
                payload = c.odds_by_tournaments(group, bookmaker=book)
                fn = OUTDIR / f"{stamp}_{book.replace('.', '_')}_batch{i}.json"
                fn.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
                manifest["books"][book].append({
                    "request": i,
                    "status": "SUCCESS",
                    "file": str(fn),
                    "tournamentIds": group,
                })
            except Exception as e:
                manifest["books"][book].append({
                    "request": i,
                    "status": "FAILED_NO_RETRY",
                    "error": str(e),
                    "tournamentIds": group,
                })
            time.sleep(1.25)

    quota_after = quota_state(c.account())
    manifest["quota_after"] = quota_after
    manifest["billable_calls_observed"] = quota_after["used"] - quota_before["used"]

    (OUTDIR / f"{stamp}_manifest.json").write_text(
        json.dumps(manifest, indent=2, default=str), encoding="utf-8"
    )
    print(json.dumps({
        "relevant_fixtures": len(relevant),
        "registry_rows": registry_result["registry_rows"],
        "registry_inserted": registry_result["inserted"],
        "tournaments": len(tids),
        "books": books,
        "estimated_billable_calls": estimated_calls,
        "billable_calls_observed": manifest["billable_calls_observed"],
        "quota_remaining": quota_after["remaining"],
    }, indent=2))


if __name__ == "__main__":
    main()
