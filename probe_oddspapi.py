
from __future__ import annotations

import json
from pathlib import Path

from oddspapi_client import OddsPapiClient, OddsPapiError


def as_list(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("data", "items", "sports", "tournaments", "results"):
            if isinstance(payload.get(key), list):
                return payload[key]
    return []


def find_tennis_sport(sports):
    rows = as_list(sports)
    candidates = []
    for s in rows:
        text = " ".join(str(s.get(k, "")) for k in ("name", "sportName", "slug", "key", "category")).lower()
        if "tennis" in text:
            candidates.append(s)
    return candidates


def main():
    client = OddsPapiClient()

    print("[0] Connectivity/account check...")
    try:
        account = client.account()
    except OddsPapiError as exc:
        print(f"STOP: {exc}")
        return 2

    print("      API reached successfully.")
    Path("oddspapi_account_probe.json").write_text(
        json.dumps(account, indent=2, default=str), encoding="utf-8"
    )

    print("[1] Discovering sports...")
    sports = client.sports()
    Path("oddspapi_sports_probe.json").write_text(
        json.dumps(sports, indent=2, default=str), encoding="utf-8"
    )

    tennis = find_tennis_sport(sports)
    if not tennis:
        print("STOP: Could not identify Tennis in /v4/sports response.")
        print("Saved oddspapi_sports_probe.json for inspection.")
        return 3

    print("      Tennis candidates:")
    for x in tennis:
        print("      ", x)

    # Use the first candidate and discover its actual ID/key rather than assuming 5.
    t = tennis[0]
    sport_id = (
        t.get("sportId")
        or t.get("id")
        or t.get("sport_id")
    )
    if sport_id is None:
        print("STOP: Tennis row found but no recognizable sport ID field.")
        return 4

    print(f"[2] Fetching tournaments for discovered tennis sportId={sport_id}...")
    tournaments = client.tournaments(sport_id)
    Path("oddspapi_tournaments_probe.json").write_text(
        json.dumps(tournaments, indent=2, default=str), encoding="utf-8"
    )

    rows = as_list(tournaments)
    active = []
    for tr in rows:
        counts = [
            tr.get("futureFixtures"),
            tr.get("upcomingFixtures"),
            tr.get("liveFixtures"),
        ]
        numeric = []
        for v in counts:
            try:
                numeric.append(int(v or 0))
            except Exception:
                numeric.append(0)

        # If counters are absent, keep the tournament as a candidate.
        if sum(numeric) > 0 or all(v is None for v in counts):
            active.append(tr)

    print(f"      Tournament rows: {len(rows)}")
    print(f"      Active/future candidates: {len(active)}")

    if not active:
        print("STOP: No active/future tournament candidates.")
        print("Saved oddspapi_tournaments_probe.json for inspection.")
        return 5

    ids = []
    for tr in active[:25]:
        tid = tr.get("tournamentId") or tr.get("id") or tr.get("tournament_id")
        if tid is not None:
            ids.append(tid)

    if not ids:
        print("STOP: Could not identify tournament ID fields.")
        return 6

    print(f"[3] Pulling one batched odds response for {len(ids)} tournaments...")
    odds = client.odds_by_tournaments(ids)
    Path("oddspapi_odds_probe.json").write_text(
        json.dumps(odds, indent=2, default=str), encoding="utf-8"
    )

    print("SUCCESS")
    print("Saved:")
    print("  oddspapi_account_probe.json")
    print("  oddspapi_sports_probe.json")
    print("  oddspapi_tournaments_probe.json")
    print("  oddspapi_odds_probe.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
