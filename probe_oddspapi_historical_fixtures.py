from __future__ import annotations
import json
from pathlib import Path
from oddspapi_client import OddsPapiClient
from pull_oddspapi_quota_aware import relevant_fixture, quota_state

OUT = Path("oddspapi_history/historical_fixture_probe.json")


def main():
    client = OddsPapiClient()
    before = quota_state(client.account())
    fixtures = client.fixtures(
        12,
        "2026-08-24T00:00:00Z",
        "2026-09-01T00:00:00Z",
        status_id=2,
        has_odds=None,
    )
    relevant = [f for f in fixtures if relevant_fixture(f)]
    after = quota_state(client.account())
    payload = {
        "window_from": "2026-08-24T00:00:00Z",
        "window_to": "2026-09-01T00:00:00Z",
        "raw_finished_fixtures": len(fixtures),
        "relevant_tennis_fixtures": len(relevant),
        "sample": relevant[:10],
        "quota_before": before,
        "quota_after": after,
        "billable_calls_observed": after["used"] - before["used"],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    if not relevant:
        raise SystemExit("Probe returned zero relevant finished tennis fixtures; refusing full-year rerun.")


if __name__ == "__main__":
    main()
