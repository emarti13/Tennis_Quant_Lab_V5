"""Kalshi store: fixture matching by names, cut at the start, standing bid/ask, append-only."""
from __future__ import annotations

import pandas as pd

from v5_kalshi_history import (
    MARKET_COLUMNS, POINT_COLUMNS, append_kalshi, kalshi_cutoff, market_points, market_record, match_fixture,
)


def _mk(ticker, name, when="2026-10-08T07:00:00Z"):
    return {"ticker": ticker, "event_ticker": "EV", "yes_sub_title": name, "occurrence_datetime": when,
            "open_time": "2026-10-07T04:00:00Z", "close_time": "2026-10-08T14:00:00Z", "result": "no",
            "title": f"{name} wins", "volume_fp": "100"}


REG = pd.DataFrame([
    {"fixture_id": "f1", "start_time_utc": "2026-10-08T07:30:00Z", "true_start_time_utc": "2026-10-08T08:05:00Z",
     "participant1_name": "Norrie, Cameron", "participant2_name": "Svrčina, Dalibor"},
    {"fixture_id": "f2", "start_time_utc": "2026-10-20T07:30:00Z", "true_start_time_utc": "",
     "participant1_name": "Norrie, Cameron", "participant2_name": "Svrčina, Dalibor"},   # a rematch, too far away
])
EVENT = [_mk("EV-NOR", "Cameron Norrie"), _mk("EV-SVR", "Dalibor Svrcina")]


def test_event_matches_one_fixture_by_both_names_within_the_window():
    mapping, method = match_fixture(EVENT, REG)
    assert method == "names" and mapping == {"EV-NOR": ("f1", "p1"), "EV-SVR": ("f1", "p2")}


def test_no_or_two_candidates_fail_closed():
    assert match_fixture([_mk("A", "Someone Else"), _mk("B", "Dalibor Svrcina")], REG) == ({}, "unmatched")
    twice = pd.concat([REG, REG.iloc[[0]].assign(fixture_id="f1b")])
    assert match_fixture(EVENT, twice) == ({}, "ambiguous")


def test_cutoff_prefers_the_fixture_true_start_then_scheduled_then_kalshi():
    f = REG.iloc[0].to_dict()
    assert kalshi_cutoff(EVENT[0], f)[1] == "true_start"
    assert kalshi_cutoff(EVENT[0], {**f, "true_start_time_utc": ""})[1] == "scheduled_start"
    assert kalshi_cutoff(EVENT[0], None) == (pd.Timestamp("2026-10-08T07:00:00Z"), "kalshi_occurrence")


def _candle(t, bid, ask):
    return {"end_period_ts": int(pd.Timestamp(t).timestamp()),
            "yes_bid": {"close_dollars": f"{bid:.4f}"}, "yes_ask": {"close_dollars": f"{ask:.4f}"}}


def test_points_are_cut_at_the_start_and_use_the_quote_standing_before_it():
    cutoff = pd.Timestamp("2026-10-08T08:05:00Z")
    candles = [_candle("2026-10-07T07:00:00Z", 0.40, 0.45), _candle("2026-10-08T07:00:00Z", 0.42, 0.44),
               _candle("2026-10-08T08:05:00Z", 0.10, 0.15),      # the start minute: may hold in-play trades
               _candle("2026-10-08T09:00:00Z", 0.01, 1.00)]
    trades = [{"created_time": "2026-10-07T06:00:00.1Z", "yes_price_dollars": "0.4100", "count_fp": "10"},
              {"created_time": "2026-10-08T07:59:00.5Z", "yes_price_dollars": "0.4300", "count_fp": "5.5"},
              {"created_time": "2026-10-08T08:30:00Z", "yes_price_dollars": "0.0500", "count_fp": "99"}]
    p = market_points(EVENT[0], candles, trades, cutoff, fixture_id="f1", side="p1")
    assert (p["open_trade_price"], p["close_trade_price"]) == (0.41, 0.43)
    assert (p["close_bid"], p["close_ask"]) == (0.42, 0.44)
    assert (p["t24h_bid"], p["t24h_ask"]) == (0.40, 0.45) and p["t1h_bid"] == 0.42
    assert p["pre_start_trades"] == 2 and p["pre_start_contracts"] == 15.5
    assert set(p) == set(POINT_COLUMNS)


def test_store_is_append_only(tmp_path):
    cutoff = pd.Timestamp("2026-10-08T08:05:00Z")
    rec = market_record(EVENT[0], "KXATPMATCH", fixture_id="f1", side="p1", method="names", cutoff=cutoff,
                        cutoff_source="true_start", pulled_utc="x")
    pts = market_points(EVENT[0], [], [], cutoff, fixture_id="f1", side="p1")
    assert append_kalshi([rec], [pts], tmp_path) == 1
    assert append_kalshi([rec], [pts], tmp_path) == 0
    stored = pd.read_csv(tmp_path / "market_history" / "kalshi" / "markets" / "2026-10.csv")
    assert list(stored.columns) == MARKET_COLUMNS and stored.loc[0, "family"] == "ATP"


def test_daily_workflow_collects_kalshi_and_keeps_its_raw_out_of_git():
    from pathlib import Path
    text = Path(".github/workflows/v5_market_history.yml").read_text(encoding="utf-8")
    assert "python scripts/pull_kalshi_history.py" in text
    assert "market_history/kalshi/raw/" in Path(".gitignore").read_text(encoding="utf-8")
    assert not Path("scripts/export_kalshi_training_dataset.py").exists()       # retired: read the old engine
    assert not Path(".github/workflows/v5_market_feed_build.yml").exists()        # retired: artifact no longer exists
