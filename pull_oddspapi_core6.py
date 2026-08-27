
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from oddspapi_client import OddsPapiClient

CORE_BOOKS = [
    "pinnacle",
    "bookmaker.eu",
    "betrivers",
    "draftkings",
    "kalshi",
    "novig.us",
]

OUTDIR = Path("oddspapi_snapshots")
OUTDIR.mkdir(exist_ok=True)

def as_list(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("data","items","sports","tournaments","results"):
            if isinstance(payload.get(key), list):
                return payload[key]
    return []

def find_tennis_id(client):
    sports = client.sports()
    for s in as_list(sports):
        text = " ".join(str(s.get(k,"")) for k in ("sportName","name","slug","key")).lower()
        if "tennis" in text and "table" not in text:
            return s.get("sportId") or s.get("id") or s.get("sport_id")
    raise RuntimeError("Could not identify tennis sport ID.")

def active_tournament_ids(client, sport_id):
    tournaments = client.tournaments(sport_id)
    rows = as_list(tournaments)
    ids=[]
    for tr in rows:
        counts = [
            tr.get("futureFixtures"),
            tr.get("upcomingFixtures"),
            tr.get("liveFixtures"),
        ]
        vals=[]
        for v in counts:
            try: vals.append(int(v or 0))
            except Exception: vals.append(0)
        if sum(vals)>0 or all(v is None for v in counts):
            tid = tr.get("tournamentId") or tr.get("id") or tr.get("tournament_id")
            if tid is not None:
                ids.append(tid)
    return ids

def main():
    client = OddsPapiClient()
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    day = now.strftime("%Y-%m-%d")

    print("[1] Discovering tennis...")
    sport_id = find_tennis_id(client)
    print(f"    Tennis sportId={sport_id}")

    print("[2] Discovering active tournaments...")
    tournament_ids = active_tournament_ids(client, sport_id)
    print(f"    Active/future tournament IDs: {len(tournament_ids)}")

    # Keep payload bounded while still covering the slate.
    # If OddsPapi supports more than 100 tournament IDs safely, we can raise this later.
    tournament_ids = tournament_ids[:100]

    manifest = {
        "captured_at_utc": now.isoformat(),
        "sport_id": sport_id,
        "tournament_ids": tournament_ids,
        "books": {},
    }

    print("[3] Pulling Core 6...")
    for book in CORE_BOOKS:
        print(f"    {book}...")
        try:
            payload = client.odds_by_tournaments(tournament_ids, bookmaker=book)
            path = OUTDIR / f"{day}_{book.replace('.','_')}_{stamp}.json"
            path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
            manifest["books"][book] = {"status":"SUCCESS","file":str(path)}
        except Exception as exc:
            manifest["books"][book] = {"status":"FAILED","error":str(exc)}
            print(f"      FAILED: {exc}")

    manifest_path = OUTDIR / f"{day}_manifest_{stamp}.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    print(f"[4] COMPLETE: {manifest_path}")

if __name__=="__main__":
    main()
