import pandas as pd

from v5_daily_policy_postprocess import apply_daily_policy


CONFIG = {
    "score_markets": {
        "MEN_BO5": {"enabled": True},
        "MEN_BO3": {"enabled": False},
        "WTA_BO3": {"enabled": False},
    }
}


def test_legacy_mens_slam_row_without_best_of_is_backfilled_as_bo5():
    frame = pd.DataFrame([
        {
            "market_group": "game_spread",
            "signal": "BET",
            "tour_v5": "MEN",
            "tournament": "US Open Men Singles",
        }
    ])

    out = apply_daily_policy(frame, CONFIG)

    assert int(out.loc[0, "best_of"]) == 5
    assert bool(out.loc[0, "production_market_enabled"]) is True
    assert out.loc[0, "signal"] == "BET"


def test_legacy_non_slam_row_without_best_of_is_backfilled_as_bo3():
    frame = pd.DataFrame([
        {
            "market_group": "total_games",
            "signal": "LEAN",
            "tour_v5": "MEN",
            "tournament": "ATP Challenger Como, Italy Men Singles",
            "best_of": float("nan"),
        }
    ])

    out = apply_daily_policy(frame, CONFIG)

    assert int(out.loc[0, "best_of"]) == 3
    assert bool(out.loc[0, "production_market_enabled"]) is False
    assert out.loc[0, "signal"] == "REVIEW"
