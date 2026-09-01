import pandas as pd

from v5_travel_features import haversine_km, build_travel_features


def _registry():
    return pd.DataFrame([
        {"canonical_event_id":"ny","canonical_name":"New York Open","aliases":"","tour":"MEN","start_year":2020,"end_year":None,"city":"New York","country":"USA","continent":"North America","latitude":40.7128,"longitude":-74.0060,"timezone":"America/New_York","altitude_m":10,"surface":"Hard","indoor":False,"source_quality":"test"},
        {"canonical_event_id":"madrid","canonical_name":"Madrid Open","aliases":"","tour":"MEN","start_year":2020,"end_year":None,"city":"Madrid","country":"Spain","continent":"Europe","latitude":40.4168,"longitude":-3.7038,"timezone":"Europe/Madrid","altitude_m":657,"surface":"Clay","indoor":False,"source_quality":"test"},
    ])


def _rows():
    return pd.DataFrame([
        {"match_id":"m1","player_name":"A","match_date":"2026-04-20","tourney_name":"New York Open","tour":"MEN","surface":"Hard"},
        {"match_id":"m2","player_name":"A","match_date":"2026-04-27","tourney_name":"Madrid Open","tour":"MEN","surface":"Clay"},
        {"match_id":"m3","player_name":"A","match_date":"2026-04-29","tourney_name":"Madrid Open","tour":"MEN","surface":"Clay"},
    ])


def test_haversine_known_distance_is_reasonable():
    d = haversine_km(40.7128, -74.0060, 40.4168, -3.7038)
    assert 5700 < d < 5900


def test_travel_features_use_previous_competition_location_only():
    out = build_travel_features(_rows(), _registry())
    assert pd.isna(out.iloc[0]["travel_km_from_previous_event"])
    assert 5700 < out.iloc[1]["travel_km_from_previous_event"] < 5900
    assert out.iloc[1]["continent_change"] == 1
    assert out.iloc[1]["altitude_change_m"] == 647
    assert out.iloc[1]["surface_change"] == 1
    assert out.iloc[2]["travel_km_from_previous_event"] == 0
    assert out.iloc[2]["surface_change"] == 0


def test_future_event_cannot_change_earlier_travel_features():
    base = build_travel_features(_rows(), _registry())
    future = pd.concat([_rows(), pd.DataFrame([{"match_id":"m4","player_name":"A","match_date":"2026-06-01","tourney_name":"New York Open","tour":"MEN","surface":"Hard"}])], ignore_index=True)
    extended = build_travel_features(future, _registry())
    cols = ["travel_km_from_previous_event","timezone_change_hours","continent_change","altitude_change_m","surface_change"]
    pd.testing.assert_frame_equal(base[cols], extended.iloc[:3][cols].reset_index(drop=True))
