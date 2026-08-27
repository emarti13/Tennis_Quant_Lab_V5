
from __future__ import annotations

import json
import os
from pathlib import Path

from oddspapi_client import OddsPapiClient


def main():
    client = OddsPapiClient()

    print("[0] Account/quota check (unmetered)...")
    account = client.account()
    print(json.dumps(account, indent=2)[:5000])

    tennis_sport_id = int(
        os.getenv("ODDSPAPI_TENNIS_SPORT_ID", "5")
    )

    print(f"\n[1] Fetching tournaments for sportId={tennis_sport_id}...")
    tournaments = client.tournaments(tennis_sport_id)

    Path("oddspapi_tournaments_probe.json").write_text(
        json.dumps(tournaments, indent=2),
        encoding="utf-8",
    )

    candidates = []
    for t in tournaments if isinstance(tournaments, list) else []:
        future = int(t.get("futureFixtures") or 0)
        upcoming = int(t.get("upcomingFixtures") or 0)
        live = int(t.get("liveFixtures") or 0)
        if future + upcoming + live > 0:
            candidates.append(t)

    print(f"Found {len(candidates)} active/future tournament candidates.")

    if not candidates:
        print(
            "No active tournament candidates found. Check the tennis sport ID "
            "returned by /v4/sports before making another billable request."
        )
        return

    # Limit to first 25 active tournaments to keep payload manageable while
    # still using only one odds-by-tournaments request.
    ids = [x["tournamentId"] for x in candidates[:25]]
    print(f"\n[2] Pulling odds for tournament IDs: {ids}")

    odds = client.odds_by_tournaments(ids)
    Path("oddspapi_odds_probe.json").write_text(
        json.dumps(odds, indent=2),
        encoding="utf-8",
    )

    print("Saved:")
    print("  oddspapi_tournaments_probe.json")
    print("  oddspapi_odds_probe.json")
    print("\nSend the odds probe file back for final V5 market parser wiring.")


if __name__ == "__main__":
    main()
