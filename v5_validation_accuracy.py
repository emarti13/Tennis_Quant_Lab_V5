from __future__ import annotations

import pandas as pd

# Frozen research/validation results from the latest approved walk-forward analyses.
# These are deliberately separate from live post-reset Results Accuracy metrics.
_MATCH_WINNER = [
    {"Tour": "ATP", "Accuracy": 0.7489, "Scope": "walk-forward validation"},
    {"Tour": "WTA", "Accuracy": 0.8038, "Scope": "walk-forward validation"},
]

_SPREAD = [
    {"Tour": "ATP", "Wins": 768, "Losses": 908, "Pushes": 26, "Accuracy": 0.4582},
    {"Tour": "WTA", "Wins": 155, "Losses": 88, "Pushes": 2, "Accuracy": 0.6379},
]

_TOTAL = [
    {"Tour": "ATP", "Wins": 621, "Losses": 748, "Pushes": 21, "Accuracy": 0.4536},
    {"Tour": "WTA", "Wins": 123, "Losses": 119, "Pushes": 3, "Accuracy": 0.5083},
]


def validation_accuracy_tables():
    """Return immutable app-facing validation summaries.

    Spread/total rows use one balanced closing consensus observation per match
    (median across books), preventing bookmaker/line-weighted duplication.
    """
    return {
        "match_winner": pd.DataFrame(_MATCH_WINNER),
        "spread": pd.DataFrame(_SPREAD),
        "total": pd.DataFrame(_TOTAL),
    }
