from pathlib import Path

import pandas as pd


def _ratings():
    return pd.DataFrame([
        {"player":"Alpha","surface":"Clay","surface_points":500,"serve_global":0.05,"return_global":-0.01,"serve_surface":0.06,"return_surface":-0.02,"elo":1600,"surface_elo":1620,"state_confidence":0.9,"rank":10},
        {"player":"Beta","surface":"Clay","surface_points":500,"serve_global":0.01,"return_global":0.00,"serve_surface":0.02,"return_surface":0.00,"elo":1550,"surface_elo":1540,"state_confidence":0.85,"rank":20},
    ])


def test_prepare_fixture_honors_explicit_ui_overrides():
    from v5_interactive_production import _prepare_with_overrides
    rows = pd.DataFrame([{
        "fixture_id":"fx1","tournament":"US Open Men Singles","tour":"Men",
        "player1":"Alpha","player2":"Beta","v5_tour_override":"MEN",
        "v5_surface_override":"Clay","v5_best_of_override":3,
    }])
    prepared = _prepare_with_overrides(rows, {"MEN":_ratings()}, {"MEN":{"baseline":{"Clay":0.60}}})
    assert prepared["tour"] == "MEN"
    assert prepared["surface"] == "Clay"
    assert prepared["surface_source"] == "User override"
    assert prepared["best_of"] == 3


def test_production_board_adapter_preserves_models_and_context():
    from v5_interactive_production import production_board_to_today
    common = {
        "fixture_id":"fx1","tournament":"Test Open","start_time_utc":"2026-09-04T18:00:00Z",
        "tour_v5":"MEN","surface":"Hard","best_of":3,"resolved_player1":"Alpha","resolved_player2":"Beta",
        "full_context_probability_p1":0.64,"expected_margin":3.2,"expected_total":22.4,
        "model_gap":0.035,"model_disagreement":"LOW","selected_model_candidate":"ensemble",
        "selected_score_candidate":"conditioned_mechanistic","context_quality_a":0.91,"context_quality_b":0.86,
        "ctx_serve_dominance_diff":0.08,"ctx_rest_log1p_diff":0.15,"ctx_travel_km_diff":-320.0,
        "ctx_court_speed_x_serve_dominance_diff":0.03,"ctx_state_uncertainty_diff":-0.04,
    }
    production = pd.DataFrame([
        {**common,"market_group":"moneyline","selection":"Alpha","line":None,"best_american_odds":-115,"expected_value":0.19,"signal":"BET"},
        {**common,"market_group":"moneyline","selection":"Beta","line":None,"best_american_odds":105,"expected_value":-0.20,"signal":"PASS"},
    ])
    today = production_board_to_today(production)
    row = today.iloc[0]
    assert row["P1 V5 %"] == 0.64
    assert row["Winner Model"] == "ensemble"
    assert row["Score Model"] == "conditioned_mechanistic"
    assert row["ctx_serve_dominance_diff"] == 0.08
    assert row["ctx_travel_km_diff"] == -320.0
    assert row["P1 ML Signal"] == "BET"
    assert row["P1 ML EV"] == 0.19
    assert row["Matchup Context"] != "Unavailable"
    assert row["Travel Context"] != "Unavailable"


def test_today_host_uses_production_bridge_not_legacy_batch_one_match():
    source = Path("v5_ui_host.py").read_text(encoding="utf-8")
    run_block = source[source.index("def _run_daily_board"):source.index("\ndef _render_today_page")]
    assert "run_interactive_production(" in run_block
    assert '"_batch_one_match"' not in run_block


def test_interactive_production_declares_context_fields_for_match_detail():
    from v5_interactive_production import LIVE_CONTEXT_DISPLAY_FIELDS
    required = {
        "ctx_serve_dominance_diff","ctx_return_dominance_diff","ctx_return_strength_diff",
        "ctx_rest_log1p_diff","ctx_games_7d_diff","ctx_minutes_7d_diff","ctx_matches_7d_diff",
        "ctx_travel_km_diff","ctx_timezone_change_abs_diff",
        "ctx_court_speed_x_serve_dominance_diff","ctx_court_speed_x_return_dominance_diff","ctx_big_server_x_altitude",
        "ctx_state_uncertainty_diff","ctx_context_quality_diff",
    }
    assert required.issubset(set(LIVE_CONTEXT_DISPLAY_FIELDS))
