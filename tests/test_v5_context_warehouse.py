import pandas as pd

from build_v5_context_warehouse import normalize_results, build_player_match_rows, resolve_history_targets


def _sample_results():
    return pd.DataFrame([
        {
            "tourney_id": "2026-001",
            "tourney_name": "Example Open",
            "surface": "Hard",
            "tourney_date": 20260105,
            "match_num": 1,
            "winner_name": "Alpha, Ann",
            "loser_name": "Beta Bea",
            "score": "6-4 6-3",
            "best_of": 3,
            "round": "R32",
            "winner_rank": 12,
            "loser_rank": 48,
            "w_ace": 8,
            "w_df": 2,
            "w_svpt": 62,
            "w_1stIn": 38,
            "w_1stWon": 30,
            "w_2ndWon": 13,
            "w_bpSaved": 4,
            "w_bpFaced": 5,
            "l_ace": 3,
            "l_df": 5,
            "l_svpt": 68,
            "l_1stIn": 40,
            "l_1stWon": 26,
            "l_2ndWon": 10,
            "l_bpSaved": 6,
            "l_bpFaced": 9,
            "result_file": "2026_wta.csv",
        }
    ])


def test_normalize_results_produces_deterministic_match_id_and_typed_date():
    first = normalize_results(_sample_results())
    second = normalize_results(_sample_results())
    assert len(first) == 1
    assert first.loc[0, "match_id"] == second.loc[0, "match_id"]
    assert first.loc[0, "tour"] == "WTA"
    assert first.loc[0, "surface"] == "Hard"
    assert int(first.loc[0, "best_of"]) == 3
    assert pd.api.types.is_datetime64_any_dtype(first["match_date"])


def test_player_match_rows_have_exactly_two_rows_and_no_target_outcome_in_feature_namespace():
    matches = normalize_results(_sample_results())
    rows = build_player_match_rows(matches)
    assert len(rows) == 2
    assert rows["match_id"].nunique() == 1
    assert set(rows["player_role"]) == {"winner", "loser"}
    assert rows["player_name"].notna().all()
    feature_cols = [c for c in rows.columns if c.startswith("feature_")]
    forbidden = {"feature_winner", "feature_score", "feature_result", "feature_games_won"}
    assert not forbidden.intersection(feature_cols)


def test_player_match_rows_orient_raw_match_stats_to_player():
    rows = build_player_match_rows(normalize_results(_sample_results()))
    winner = rows.loc[rows.player_role == "winner"].iloc[0]
    loser = rows.loc[rows.player_role == "loser"].iloc[0]
    assert winner["stat_aces"] == 8
    assert winner["stat_double_faults"] == 2
    assert winner["stat_service_points"] == 62
    assert winner["stat_first_serves_in"] == 38
    assert winner["stat_first_serve_points_won"] == 30
    assert winner["stat_second_serve_points_won"] == 13
    assert winner["stat_break_points_saved"] == 4
    assert winner["stat_break_points_faced"] == 5
    assert loser["stat_aces"] == 3
    assert loser["stat_double_faults"] == 5
    assert loser["stat_service_points"] == 68


def test_result_file_drives_tour_without_guessing_from_player_names():
    men = _sample_results().copy()
    men["result_file"] = "2026_challenger.csv"
    out = normalize_results(men)
    assert out.loc[0, "tour"] == "MEN"


def test_history_target_resolution_includes_prior_and_current_season_all_tours():
    files = []
    for year in (2025, 2026):
        for suffix in ("", "_atp_quali", "_challenger", "_wta"):
            name = f"{year}{suffix}.csv"
            files.append({"name": name, "url": f"https://example.test/{name}"})
    files.append({"name": "ongoing_tourneys.csv", "url": "https://example.test/ongoing.csv"})
    resolved = resolve_history_targets(files, years=(2025, 2026))
    assert len(resolved) == 8
    assert set(resolved) == {
        "2025.csv", "2025_atp_quali.csv", "2025_challenger.csv", "2025_wta.csv",
        "2026.csv", "2026_atp_quali.csv", "2026_challenger.csv", "2026_wta.csv",
    }
