import numpy as np
import pandas as pd

from build_v5_context_matchups import assemble_matchup_dataset, enrich_player_history


def _player_rows():
    rows = []
    matches = [
        # 2023 establishes statistical baselines so the 2024 completed match can become
        # an opponent-adjusted historical court-speed observation for the 2025 target.
        ("mpre", "2023-12-20", "Alpha", "Beta", "Hard", 1),
        ("m0", "2024-12-20", "Alpha", "Beta", "Hard", 1),
        ("m1", "2025-01-10", "Alpha", "Gamma", "Hard", 1),
        ("m2", "2026-01-10", "Gamma", "Alpha", "Hard", 1),
    ]
    for match_id, date, winner, loser, surface, _ in matches:
        year = pd.Timestamp(date).year
        common = {
            "match_id": match_id, "tour": "MEN", "match_date": date, "surface": surface,
            "best_of": 3, "tourney_id": f"{year}-0600", "tourney_name": "Example Open", "match_games": 22,
            "match_sets": 2, "match_duration_minutes": 95,
        }
        stats_w = {"stat_aces":8,"stat_double_faults":2,"stat_service_points":60,"stat_first_serves_in":38,"stat_first_serve_points_won":29,"stat_second_serve_points_won":12,"stat_break_points_saved":4,"stat_break_points_faced":5,"stat_return_points_total":62,"stat_return_points_won":26,"stat_break_points_opportunities":7,"stat_break_points_converted":3}
        stats_l = {"stat_aces":4,"stat_double_faults":4,"stat_service_points":62,"stat_first_serves_in":37,"stat_first_serve_points_won":24,"stat_second_serve_points_won":10,"stat_break_points_saved":4,"stat_break_points_faced":7,"stat_return_points_total":60,"stat_return_points_won":19,"stat_break_points_opportunities":5,"stat_break_points_converted":1}
        rows.append({**common, **stats_w, "player_name":winner,"opponent_name":loser,"player_role":"winner","player_rank":20,"opponent_rank":50})
        rows.append({**common, **stats_l, "player_name":loser,"opponent_name":winner,"player_role":"loser","player_rank":50,"opponent_rank":20})
    return pd.DataFrame(rows)


def _registry():
    return pd.DataFrame([
        {"canonical_event_id":"MEN:0600","canonical_name":"Example Open","aliases":"","tour":"MEN","start_year":2023,"end_year":2024,"city":"New York","country":"USA","continent":"North America","latitude":40.7128,"longitude":-74.0060,"timezone":"America/New_York","altitude_m":10,"surface":"Hard","indoor":False,"source_quality":"test"},
        {"canonical_event_id":"MEN:0600","canonical_name":"Example Open","aliases":"","tour":"MEN","start_year":2025,"end_year":2026,"city":"Madrid","country":"Spain","continent":"Europe","latitude":40.4168,"longitude":-3.7038,"timezone":"Europe/Madrid","altitude_m":657,"surface":"Hard","indoor":False,"source_quality":"test"},
    ])


def _walkforward():
    return pd.DataFrame([
        {"date":"2025-01-10","tour":"MEN","winner":"Alpha","loser":"Gamma","winner_serve_p":.64,"loser_serve_p":.61,"elo_winner_p":.66,"surface":"Hard","level":"A"},
        {"date":"2026-01-10","tour":"MEN","winner":"Gamma","loser":"Alpha","winner_serve_p":.63,"loser_serve_p":.62,"elo_winner_p":.57,"surface":"Hard","level":"A"},
    ])


def test_enrichment_uses_2024_as_history_for_first_2025_match():
    enriched = enrich_player_history(_player_rows())
    alpha_2025 = enriched[(enriched.match_id == "m1") & (enriched.player_name == "Alpha")].iloc[0]
    assert np.isclose(alpha_2025["rolling_ace_rate"], 16/120)
    assert alpha_2025["rest_days"] == 21
    assert np.isclose(alpha_2025["rolling_return_points_won_pct"], 52/124)


def test_enrichment_builds_historical_prior_court_speed_before_target_match():
    enriched = enrich_player_history(_player_rows())
    first_2025 = enriched[enriched.match_id == "m1"]
    assert first_2025["court_speed_historical_sample_size"].iloc[0] == 1
    assert first_2025["court_speed_historical_prior"].notna().all()
    assert first_2025["court_speed_blended"].notna().all()
    assert first_2025["court_speed_current_event_sample_size"].iloc[0] == 0


def test_enrichment_attaches_year_aware_travel_state_when_registry_is_available():
    enriched = enrich_player_history(_player_rows(), tournament_registry=_registry())
    alpha_2025 = enriched[(enriched.match_id == "m1") & (enriched.player_name == "Alpha")].iloc[0]
    assert alpha_2025["venue_city"] == "Madrid"
    assert 5700 < alpha_2025["travel_km_from_previous_event"] < 5900
    assert alpha_2025["continent_change"] == 1
    assert alpha_2025["altitude_change_m"] == 647


def test_assembler_matches_exact_winner_loser_date_and_builds_deterministic_orientation():
    enriched = enrich_player_history(_player_rows())
    out, qc = assemble_matchup_dataset(enriched, _walkforward(), target_years=(2025, 2026))
    assert len(out) == 2
    assert qc["matched_matches"] == 2
    row_2025 = out[out.year == 2025].iloc[0]
    assert row_2025["player_a"] == "Alpha"
    assert row_2025["target_a_win"] == 1
    assert 0 < row_2025["baseline_a_probability"] < 1
    assert np.isfinite(row_2025["x_sr_a"])
    assert np.isfinite(row_2025["x_elo_a"])
    assert any(c.startswith("ctx_") for c in out.columns)
    assert "ctx_rest_days_diff" not in out.columns
    assert "ctx_rest_log1p_diff" in out.columns
    assert "ctx_court_speed_x_serve_dominance_diff" in out.columns


def test_current_match_raw_stats_never_enter_context_feature_namespace():
    enriched = enrich_player_history(_player_rows())
    out, _ = assemble_matchup_dataset(enriched, _walkforward(), target_years=(2025, 2026))
    context_cols = [c for c in out.columns if c.startswith("ctx_")]
    assert context_cols
    forbidden_exact = {
        "ctx_stat_aces", "ctx_stat_service_points", "ctx_stat_return_points_won",
        "ctx_match_games", "ctx_match_sets", "ctx_match_duration_minutes", "ctx_player_role",
    }
    assert not forbidden_exact.intersection(context_cols)
    # Prior-match workload is explicitly allowed because it is known before first serve.
    assert "ctx_previous_match_games_diff" in context_cols


def test_unmatched_walkforward_rows_are_counted_not_guessed():
    enriched = enrich_player_history(_player_rows())
    wf = pd.concat([_walkforward(), pd.DataFrame([{"date":"2026-02-01","tour":"MEN","winner":"Nobody","loser":"Unknown","winner_serve_p":.62,"loser_serve_p":.61,"elo_winner_p":.55,"surface":"Hard","level":"A"}])], ignore_index=True)
    out, qc = assemble_matchup_dataset(enriched, wf, target_years=(2025, 2026))
    assert len(out) == 2
    assert qc["walkforward_unmatched"] == 1
