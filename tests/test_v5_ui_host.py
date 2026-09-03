from __future__ import annotations

import pandas as pd


def test_resolve_selected_match_uses_fixture_id_without_mutating_board():
    from v5_ui_host import resolve_selected_match

    board = pd.DataFrame([
        {"Fixture ID": "fx-1", "Player 1": "A", "Player 2": "B", "P1 V5 %": 0.61},
        {"Fixture ID": "fx-2", "Player 1": "C", "Player 2": "D", "P1 V5 %": 0.55},
    ])
    source = board.copy(deep=True)

    row = resolve_selected_match(board, "fx-2")

    assert row["Player 1"] == "C"
    assert row["P1 V5 %"] == 0.55
    pd.testing.assert_frame_equal(board, source)


def test_page_labels_make_today_default_and_keep_matchup_lab():
    from v5_ui_host import navigation_pages

    pages = navigation_pages()
    assert pages[0] == "Today"
    assert pages[:5] == ["Today", "Match Detail", "All Markets", "Performance", "Model Health"]
    assert "Matchup Lab" in pages


def test_market_snapshot_is_explicit_when_missing():
    from v5_ui_host import market_snapshot

    assert market_snapshot(pd.DataFrame()) == "Unknown"
    feed = pd.DataFrame({"snapshot_utc": [None, "2026-09-03T12:00:00Z"]})
    assert market_snapshot(feed) == "2026-09-03T12:00:00Z"
