from __future__ import annotations

SCHEMA_VERSION = "v5-context-1"

MATCH_COLUMNS = [
    "match_id", "tour", "match_date", "tourney_id", "tourney_name", "match_num",
    "round", "surface", "best_of", "winner_name", "loser_name", "score",
    "winner_games", "loser_games", "total_games", "result_file", "source_quality",
]

PLAYER_MATCH_COLUMNS = [
    "match_id", "tour", "match_date", "tourney_id", "tourney_name", "match_num",
    "round", "surface", "best_of", "player_name", "opponent_name", "player_role",
    "player_rank", "opponent_rank", "result_file", "source_quality",
]

# Columns beginning with feature_ are reserved for information available before first serve.
# Outcome/label fields may exist outside this namespace for supervised training and settlement.
FEATURE_NAMESPACE_PREFIX = "feature_"
FORBIDDEN_PREMATCH_FEATURES = {
    "feature_winner", "feature_score", "feature_result", "feature_games_won",
    "feature_sets_won", "feature_match_outcome",
}
