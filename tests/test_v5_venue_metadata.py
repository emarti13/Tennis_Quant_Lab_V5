import pandas as pd

from v5_venue_metadata import choose_geocode_candidate, stable_event_id, build_registry_from_events


class FakeGeocoder:
    def __init__(self, payloads):
        self.payloads = payloads
        self.calls = []

    def search(self, query):
        self.calls.append(query)
        return self.payloads.get(query, [])


def test_stable_event_id_prefers_yearless_source_tournament_code():
    assert stable_event_id("MEN", "2026-0580", "Australian Open") == "MEN:0580"
    assert stable_event_id("WTA", "2025-1020", "City Name") == "WTA:1020"


def test_stable_event_id_falls_back_to_normalized_name():
    assert stable_event_id("MEN", None, "U.S. Open") == "MEN:us-open"


def test_geocoder_accepts_unique_exact_name():
    candidates = [{"name":"Madrid","country":"Spain","country_code":"ES","latitude":40.4,"longitude":-3.7,"timezone":"Europe/Madrid","elevation":657,"population":3200000}]
    chosen, quality = choose_geocode_candidate("Madrid", candidates)
    assert chosen["country_code"] == "ES"
    assert quality == "exact_unique"


def test_geocoder_uses_population_only_when_exact_candidate_is_dominant():
    candidates = [
        {"name":"Paris","country":"France","latitude":48.86,"longitude":2.35,"timezone":"Europe/Paris","elevation":35,"population":2100000},
        {"name":"Paris","country":"United States","latitude":33.66,"longitude":-95.55,"timezone":"America/Chicago","elevation":180,"population":25000},
    ]
    chosen, quality = choose_geocode_candidate("Paris", candidates)
    assert chosen["country"] == "France"
    assert quality == "exact_population_dominant"


def test_geocoder_rejects_unresolved_ambiguity_instead_of_guessing():
    candidates = [
        {"name":"Springfield","country":"United States","latitude":1,"longitude":1,"population":100000},
        {"name":"Springfield","country":"United States","latitude":2,"longitude":2,"population":80000},
    ]
    chosen, quality = choose_geocode_candidate("Springfield", candidates)
    assert chosen is None
    assert quality == "ambiguous"


def test_registry_builder_deduplicates_event_and_preserves_surface():
    events = pd.DataFrame([
        {"tour":"MEN","tourney_id":"2025-0999","tourney_name":"Madrid","surface":"Clay","match_date":"2025-04-01"},
        {"tour":"MEN","tourney_id":"2026-0999","tourney_name":"Madrid","surface":"Clay","match_date":"2026-04-01"},
    ])
    geocoder = FakeGeocoder({"Madrid":[{"name":"Madrid","country":"Spain","country_code":"ES","latitude":40.4,"longitude":-3.7,"timezone":"Europe/Madrid","elevation":657,"population":3200000}]})
    registry, report = build_registry_from_events(events, geocoder=geocoder)
    assert len(registry) == 1
    row = registry.iloc[0]
    assert row["canonical_event_id"] == "MEN:0999"
    assert row["surface"] == "Clay"
    assert row["timezone"] == "Europe/Madrid"
    assert row["altitude_m"] == 657
    assert row["start_year"] == 2025
    assert row["end_year"] == 2026
    assert report["resolved_events"] == 1


def test_registry_builder_keeps_year_specific_rows_when_stable_event_changes_city():
    events = pd.DataFrame([
        {"tour":"MEN","tourney_id":"2025-0600","tourney_name":"Toronto","surface":"Hard","match_date":"2025-08-01"},
        {"tour":"MEN","tourney_id":"2026-0600","tourney_name":"Montreal","surface":"Hard","match_date":"2026-08-01"},
    ])
    geocoder = FakeGeocoder({
        "Toronto":[{"name":"Toronto","country":"Canada","country_code":"CA","latitude":43.65,"longitude":-79.38,"timezone":"America/Toronto","elevation":76,"population":2800000}],
        "Montreal":[{"name":"Montreal","country":"Canada","country_code":"CA","latitude":45.50,"longitude":-73.57,"timezone":"America/Toronto","elevation":36,"population":1760000}],
    })
    registry, report = build_registry_from_events(events, geocoder=geocoder)
    assert len(registry) == 2
    assert set(registry["canonical_event_id"]) == {"MEN:0600"}
    toronto = registry[registry.city == "Toronto"].iloc[0]
    montreal = registry[registry.city == "Montreal"].iloc[0]
    assert toronto["start_year"] == 2025 and toronto["end_year"] == 2025
    assert montreal["start_year"] == 2026 and montreal["end_year"] == 2026
    assert report["resolved_events"] == 2
