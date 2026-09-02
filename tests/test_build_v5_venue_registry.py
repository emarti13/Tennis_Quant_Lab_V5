import json
from pathlib import Path

import pandas as pd

from build_v5_venue_registry import build_venue_registry


class FakeGeocoder:
    def search(self, query):
        payloads = {
            "Madrid": [{"name":"Madrid","country":"Spain","country_code":"ES","latitude":40.4,"longitude":-3.7,"timezone":"Europe/Madrid","elevation":657,"population":3200000}],
        }
        return payloads.get(query, [])


def test_build_venue_registry_reads_warehouse_and_persists_registry_and_report(tmp_path: Path):
    warehouse = tmp_path / "context_warehouse"
    warehouse.mkdir()
    pd.DataFrame([
        {"match_id":"m1","tour":"MEN","match_date":"2025-04-01","tourney_id":"2025-0999","tourney_name":"Madrid","surface":"Clay"},
        {"match_id":"m2","tour":"MEN","match_date":"2026-04-01","tourney_id":"2026-0999","tourney_name":"Madrid","surface":"Clay"},
    ]).to_parquet(warehouse / "matches.parquet", index=False)

    result = build_venue_registry(tmp_path, geocoder=FakeGeocoder())

    registry_path = tmp_path / "context_registry" / "tournaments.csv"
    report_path = tmp_path / "context_registry" / "venue_registry_report.json"
    assert registry_path.exists()
    assert report_path.exists()
    registry = pd.read_csv(registry_path)
    assert len(registry) == 1
    assert registry.iloc[0]["canonical_event_id"] == "MEN:0999"
    assert registry.iloc[0]["city"] == "Madrid"
    assert registry.iloc[0]["altitude_m"] == 657
    report = json.loads(report_path.read_text())
    assert report["resolved_events"] == 1
    assert result["registry_rows"] == 1
