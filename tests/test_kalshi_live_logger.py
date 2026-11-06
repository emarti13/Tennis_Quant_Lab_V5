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
        self.calls += 1
        if path.startswith("/markets/"):
            return {"market": self.quotes.get(path.split("/")[-1], {})}
        return {"live_data": {"details": self.details}}

    quotes: dict = {}


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
    calls = api.calls
    ll.poll_once(api, state, pd.Timestamp("2026-10-21T11:55:30Z"))                          # 30 s later: not re-checked
    assert api.calls == calls
    ll.poll_once(api, state, pd.Timestamp("2026-10-21T11:56:00Z"))                          # a minute later: re-checked
    assert api.calls == calls + 1


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


def test_live_rows_use_quotes_read_after_the_score(tmp_path, monkeypatch):
    monkeypatch.setattr(ll, "OUT_DIR", tmp_path)
    api, state = FakeKalshi(), {"events": {}}
    api.quotes = {"EV-A": {"yes_bid_dollars": "0.80", "yes_ask_dollars": "0.81"}}       # moved since the listing
    ll.poll_once(api, state, pd.Timestamp("2026-10-21T12:30:00Z"))
    r = pd.read_csv(tmp_path / "2026-10-21.csv").iloc[0]
    assert r["bid_2"] == 0.80 and r["ask_2"] == 0.81            # EV-A is competitor 2: the fresh quote
    assert r["bid_1"] == 0.28                                   # EV-B had no fresh quote: listing kept


class FakeBooks:
    calls = 0
    book = {"yes_dollars": [["0.0100", "500.00"], ["0.4000", "20.00"], ["0.4200", "15.00"]],
            "no_dollars": [["0.5500", "300.00"], ["0.5600", "10.00"]]}

    def open_markets(self, series):
        if series == "KXATPMATCH":
            return [{"ticker": "KXATPMATCH-26NOV06FRIALC-FRI", "event_ticker": "KXATPMATCH-26NOV06FRIALC"}]
        if series == "KXATPGTOTAL":
            return [{"ticker": "KXATPGTOTAL-26NOV06FRIALC-22", "event_ticker": "KXATPGTOTAL-26NOV06FRIALC",
                     "yes_sub_title": "Over 22.5 games", "floor_strike": 22.5, "strike_type": "greater",
                     "yes_bid_dollars": "0.5100", "yes_ask_dollars": "0.5400", "volume_fp": "129.00", "open_interest_fp": "80.00"}]
        return []

    def get(self, path, params=None):
        self.calls += 1
        return {"orderbook_fp": self.book}


def test_book_row_best_first_with_side_totals():
    r = ll.book_row("KXATPMATCH", "T", "KXATPMATCH-26NOV06FRIALC", FakeBooks.book, pd.Timestamp("2026-11-06T12:00Z"))
    assert r["match_suffix"] == "26NOV06FRIALC"
    assert r["best_yes_bid"] == 0.42 and r["best_no_bid"] == 0.56
    assert r["yes_levels"].startswith("0.42:15;0.40:20;0.01:500")
    assert r["yes_total"] == 535 and r["no_total"] == 310


def test_books_once_writes_props_and_only_changed_books(tmp_path, monkeypatch):
    monkeypatch.setattr(ll, "OUT_DIR", tmp_path)
    api, seen = FakeBooks(), {}
    a = ll.books_once(api, seen, pd.Timestamp("2026-11-06T12:00Z"))
    assert a == {"prop_quotes": 1, "book_rows": 2, "book_failures": 0}
    b = ll.books_once(api, seen, pd.Timestamp("2026-11-06T12:05Z"))       # nothing changed: no new book rows
    assert b["book_rows"] == 0 and b["prop_quotes"] == 1
    props = pd.read_csv(tmp_path / "props" / "2026-11-06.csv")
    assert list(props.columns) == ll.PROP_COLS and props["line"].iloc[0] == 22.5
    assert props["match_suffix"].iloc[0] == "26NOV06FRIALC"
    books = pd.read_csv(tmp_path / "orderbook" / "2026-11-06.csv")
    assert len(books) == 2 and set(books["series"]) == {"KXATPMATCH", "KXATPGTOTAL"}
