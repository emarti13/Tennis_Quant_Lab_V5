"""Live-score logger: rows only for matches in play, quotes matched to the right player, finished matches dropped."""
from __future__ import annotations

import pandas as pd

import scripts.log_kalshi_live as ll


class FakeKalshi:
    calls = 0

    def __init__(self):
        self.details = {"status": "live", "match_status": "1st_set", "competitor1_id": "c-B", "competitor2_id": "c-A",
                        "competitor1_overall_score": 0, "competitor2_overall_score": 1,
                        "competitor1_current_round_score": 15, "competitor2_current_round_score": 40,
                        "competitor1_round_scores": [{"score": 4}, {"score": 2}],
                        "competitor2_round_scores": [{"score": 6}, {"score": 3}],
                        "competitor1_statistics": {"points_won": 30, "aces": 2},
                        "competitor2_statistics": {"points_won": 41, "double_faults": 1},
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
    assert r["sets_2"] == 1 and r["round_scores_2"] == "[6, 3]"
    assert r["games_1"] == 2 and r["games_2"] == 3                 # games in the current set
    assert r["points_1"] == 15 and r["points_2"] == 40             # point score in the current game
    assert r["points_won_1"] == 30 and r["aces_1"] == 2 and r["double_faults_2"] == 1


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


def test_prematch_quotes_every_five_minutes_from_the_same_listing(tmp_path, monkeypatch):
    monkeypatch.setattr(ll, "OUT_DIR", tmp_path)
    api, state = FakeKalshi(), {"events": {}}
    info = ll.poll_once(api, state, pd.Timestamp("2026-10-21T09:00:00Z"))            # 3 h before: no live row
    assert info["rows"] == 0 and info["prematch_quotes"] == 2
    q = pd.read_csv(tmp_path / "prematch" / "2026-10-21.csv")
    assert set(q["ticker"]) == {"EV-A", "EV-B"} and q.loc[q.ticker == "EV-A", "bid"].iloc[0] == 0.70
    assert ll.poll_once(api, state, pd.Timestamp("2026-10-21T09:04:00Z"))["prematch_quotes"] == 0
    assert ll.poll_once(api, state, pd.Timestamp("2026-10-21T09:05:00Z"))["prematch_quotes"] == 2


def test_a_new_layout_mid_day_goes_to_a_new_file_and_mixed_files_are_readable(tmp_path):
    old = pd.DataFrame({"a": [1], "b": [2]})
    new = pd.DataFrame({"a": [3], "b": [4], "c": [5]})
    p1 = ll._append(tmp_path, "2026-11-02", old)
    p2 = ll._append(tmp_path, "2026-11-02", new)
    assert p1.name == "2026-11-02.csv" and p2.name == "2026-11-02-v2.csv"
    assert ll._append(tmp_path, "2026-11-02", new) == p2 and len(pd.read_csv(p2)) == 2
    # the 2026-11-01 case: old header, new-layout rows appended without one
    mixed = tmp_path / "mixed.csv"
    mixed.write_text("polled_utc,series\n2026-11-01T01:00:00+00:00,KXATPMATCH\n"
                     + ",".join(["2026-11-01T09:00:00+00:00", "KXWTAMATCH"] + ["7"] * (len(ll.COLS) - 2)) + "\n")
    df = ll.read_log(mixed)
    assert len(df) == 2 and df["series"].tolist() == ["KXATPMATCH", "KXWTAMATCH"] and df["points_won_1"].iloc[1] == 7
