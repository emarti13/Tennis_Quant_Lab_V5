"""Paper trader: trades are scored against the quote standing before them, never after the cutoff."""
from __future__ import annotations

import pandas as pd

import scripts.paper_trade_kalshi as pt


class FakeKalshi:
    def __init__(self):
        self.book, self.volume, self.tape, self.calls = (0.50, 0.60), 0.0, [], 0
        self.status = "not_started"

    def milestone(self, event):
        return {"id": "m1", "type": "tennis_tournament_singles", "start_date": "2026-10-20T12:00:00Z"}

    def live_status(self, milestone):
        return self.status

    def open_markets(self, series):
        return [{"ticker": "T-A", "event_ticker": "T", "yes_sub_title": "A", "occurrence_datetime": "2026-10-20T15:00:00Z",
                 "yes_bid_dollars": str(self.book[0]), "yes_ask_dollars": str(self.book[1]), "volume_fp": str(self.volume)}]

    def trades(self, ticker, min_ts):
        return [t for t in self.tape if pd.Timestamp(t["created_time"]).timestamp() >= min_ts]


def trade(ts, price, count, taker, tid):
    return {"created_time": ts, "yes_price_dollars": str(price), "count_fp": str(count), "taker_side": taker, "trade_id": tid}


def test_fills_use_the_standing_quote_and_stop_at_the_cutoff(tmp_path, monkeypatch):
    monkeypatch.setattr(pt, "PAPER_DIR", tmp_path)
    api, state = FakeKalshi(), {"markets": {}}
    pt.poll_once(api, state, pd.Timestamp("2026-10-20T10:00:00Z"))          # mid 0.55: 3c quotes 0.52/0.58
    api.tape = [trade("2026-10-20T10:00:30Z", 0.59, 40, "yes", "1"),        # buyer through our 0.58 sell
                trade("2026-10-20T10:00:40Z", 0.53, 10, "no", "2"),         # seller above our 0.52 buy: no fill at 3c
                trade("2026-10-20T11:59:30Z", 0.40, 50, "no", "3")]         # after the cutoff: ignored
    api.volume, api.book = 100.0, (0.30, 0.40)                                # the book moved; old quotes still apply
    info = pt.poll_once(api, state, pd.Timestamp("2026-10-20T10:01:00Z"))
    fills = pd.read_csv(tmp_path / "fills_2026-10.csv")
    assert info["trades_checked"] == 2
    three = fills[fills["h"] == 0.03]
    assert list(three["side"]) == ["sell"] and three["price"].iloc[0] == 0.58 and three["contracts"].iloc[0] == 40
    assert fills[fills["h"] == 0.05].empty                                   # 5c quotes 0.50/0.60: nothing crossed
    assert state["markets"]["T-A"]["pos"]["0.03"] == -40


def test_a_trade_is_never_counted_twice(tmp_path, monkeypatch):
    monkeypatch.setattr(pt, "PAPER_DIR", tmp_path)
    api, state = FakeKalshi(), {"markets": {}}
    pt.poll_once(api, state, pd.Timestamp("2026-10-20T10:00:00Z"))
    api.tape, api.volume = [trade("2026-10-20T10:00:30Z", 0.59, 40, "yes", "1")], 40.0
    pt.poll_once(api, state, pd.Timestamp("2026-10-20T10:01:00Z"))
    api.volume = 41.0                                                        # volume moves again, same tape
    pt.poll_once(api, state, pd.Timestamp("2026-10-20T10:02:00Z"))
    assert len(pd.read_csv(tmp_path / "fills_2026-10.csv")) == 1


def test_a_failed_trade_fetch_keeps_the_market_for_the_next_poll(tmp_path, monkeypatch):
    monkeypatch.setattr(pt, "PAPER_DIR", tmp_path)
    api, state = FakeKalshi(), {"markets": {}}
    pt.poll_once(api, state, pd.Timestamp("2026-10-20T10:00:00Z"))
    api.tape, api.volume = [trade("2026-10-20T10:00:30Z", 0.59, 40, "yes", "1")], 40.0
    real = api.trades
    api.trades = lambda *a: (_ for _ in ()).throw(RuntimeError("rate limited"))
    info = pt.poll_once(api, state, pd.Timestamp("2026-10-20T10:01:00Z"))
    assert info["markets_retry_next_poll"] == 1 and state["markets"]["T-A"]["last_trade_ts"] is None
    api.trades = real
    pt.poll_once(api, state, pd.Timestamp("2026-10-20T10:02:00Z"))
    assert len(pd.read_csv(tmp_path / "fills_2026-10.csv")) == 1               # scored once, after the retry


def test_once_the_match_is_live_nothing_after_the_previous_poll_counts(tmp_path, monkeypatch):
    monkeypatch.setattr(pt, "PAPER_DIR", tmp_path)
    api, state = FakeKalshi(), {"markets": {}}
    pt.poll_once(api, state, pd.Timestamp("2026-10-20T10:30:00Z"))           # 1.5 h before: status checked
    api.tape, api.volume, api.status = [trade("2026-10-20T10:30:30Z", 0.59, 40, "yes", "1")], 40.0, "live/1st_set"
    pt.poll_once(api, state, pd.Timestamp("2026-10-20T10:31:00Z"))           # an early start: the trade may be in play
    assert not (tmp_path / "fills_2026-10.csv").exists()
    assert state["events"]["T"]["stop_at"] == "2026-10-20T10:30:00+00:00"
    snaps = pd.read_csv(tmp_path / "snapshots_2026-10.csv")
    assert list(snaps["polled_utc"]) == ["2026-10-20T10:30:00+00:00"]            # no quote after the start is known


def test_an_event_with_no_known_start_is_not_quoted(tmp_path, monkeypatch):
    monkeypatch.setattr(pt, "PAPER_DIR", tmp_path)
    api, state = FakeKalshi(), {"markets": {}}
    api.milestone = lambda event: None
    pt.poll_once(api, state, pd.Timestamp("2026-10-20T10:00:00Z"))
    assert not (tmp_path / "snapshots_2026-10.csv").exists()


def test_a_trade_after_a_gap_between_runs_is_not_scored(tmp_path, monkeypatch):
    monkeypatch.setattr(pt, "PAPER_DIR", tmp_path)
    api, state = FakeKalshi(), {"markets": {}}
    pt.poll_once(api, state, pd.Timestamp("2026-10-20T08:00:00Z"))
    api.tape, api.volume = [trade("2026-10-20T08:20:00Z", 0.59, 40, "yes", "1")], 40.0   # 20 minutes later
    info = pt.poll_once(api, state, pd.Timestamp("2026-10-20T08:21:00Z"))
    assert info["trades_checked"] == 1 and not (tmp_path / "fills_2026-10.csv").exists()
