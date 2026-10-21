"""Live-score logger: rows only for matches in play, quotes matched to the right player, finished matches dropped."""
from __future__ import annotations

import pandas as pd

import scripts.log_kalshi_live as ll


class FakeKalshi:
    calls = 0

    def __init__(self):
        self.details = {"status": "live", "match_status": "1st_set", "competitor1_id": "c-B", "competitor2_id": "c-A",
                        "competitor1_overall_score": 0, "competitor2_overall_score": 1,
                        "competitor1_current_round_score": 2, "competitor2_current_round_score": 3,
                        "competitor1_round_scores": [{"score": 4}], "competitor2_round_scores": [{"score": 6}],
                        "server": "c-A", "advantage": ""}

    def open_markets(self, series):
        if series != "KXATPMATCH":
            return []
        return [{"ticker": "EV-A", "event_ticker": "EV", "custom_strike": {"tennis_competitor": "c-A"},
                 "yes_bid_dollars": "0.70", "yes_ask_dollars": "0.72"},
                {"ticker": "EV-B", "event_ticker": "EV", "custom_strike": {"tennis_competitor": "c-B"},
                 "yes_bid_dollars": "0.28", "yes_ask_dollars": "0.30"}]

    def milestone(self, event):
        return {"id": "m1", "type": "tennis_tournament_singles", "start_date": "2026-10-21T12:00:00Z"}

    def get(self, path, params=None):
        return {"live_data": {"details": self.details}}


def test_logs_score_with_each_players_own_quote(tmp_path, monkeypatch):
    monkeypatch.setattr(ll, "OUT_DIR", tmp_path)
    api, state = FakeKalshi(), {"events": {}}
    info = ll.poll_once(api, state, pd.Timestamp("2026-10-21T12:30:00Z"))
    rows = pd.read_csv(tmp_path / "2026-10-21.csv")
    assert info["rows"] == 1
    r = rows.iloc[0]
    assert r["ticker_1"] == "EV-B" and r["bid_1"] == 0.28        # competitor 1 is B: B's market, not file order
    assert r["ticker_2"] == "EV-A" and r["ask_2"] == 0.72
    assert r["sets_2"] == 1 and r["games_1"] == 2 and r["round_scores_2"] == "[6]"


def test_not_started_and_too_early_are_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(ll, "OUT_DIR", tmp_path)
    api, state = FakeKalshi(), {"events": {}}
    assert ll.poll_once(api, state, pd.Timestamp("2026-10-21T11:00:00Z"))["rows"] == 0     # an hour before the start
    api.details = {"status": "not_started", "match_status": None}
    assert ll.poll_once(api, state, pd.Timestamp("2026-10-21T11:55:00Z"))["rows"] == 0     # in the window, not started


def test_a_finished_match_is_logged_once_then_dropped(tmp_path, monkeypatch):
    monkeypatch.setattr(ll, "OUT_DIR", tmp_path)
    api, state = FakeKalshi(), {"events": {}}
    api.details = {**api.details, "status": "closed", "match_status": "ended"}
    assert ll.poll_once(api, state, pd.Timestamp("2026-10-21T14:00:00Z"))["rows"] == 1
    assert state["events"]["EV"]["finished"] is True
    assert ll.poll_once(api, state, pd.Timestamp("2026-10-21T14:01:00Z"))["rows"] == 0
