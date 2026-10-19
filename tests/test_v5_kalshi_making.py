"""Kalshi making: quote and fill rules, replay/paper parity, the paper run's stop and logs."""
from __future__ import annotations

import importlib.util
import random
import re
from pathlib import Path

import pandas as pd

from v5_kalshi_making import LIMIT, SIZE, STOP_BEFORE, MarketBook, fill, kalshi_mid, pnl, quotes

ROOT = Path(__file__).resolve().parents[1]


def _script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


T0 = pd.Timestamp("2026-09-01T10:00:00Z")


def _t(seconds):
    return T0 + pd.Timedelta(seconds=seconds)


def test_mid_needs_a_two_sided_book_no_wider_than_20_cents():
    assert round(kalshi_mid(0.40, 0.44), 9) == 0.42
    assert kalshi_mid(None, 0.44) is None and kalshi_mid(0.44, 0.44) is None and kalshi_mid(0.30, 0.51) is None


def test_quotes_round_outward_and_never_cross_the_book():
    assert quotes(0.425, 0.03, 0.40, 0.45) == (0.39, 0.46)
    assert quotes(0.50, 0.05, 0.40, 0.42) == (0.41, 0.55)      # bid capped one cent under the best ask


def test_fills_only_through_our_price_or_at_it_when_we_are_first():
    assert fill(0.47, 50, "yes", 0.39, 0.46, 0.40, 0.47, 0) == ("sell", 0.46, 50)   # went through us
    assert fill(0.46, 50, "yes", 0.39, 0.46, 0.40, 0.47, 0) == ("sell", 0.46, 50)   # at us, we were best
    assert fill(0.46, 50, "yes", 0.39, 0.46, 0.40, 0.46, 0) is None                 # at us, others first
    assert fill(0.38, 500, "no", 0.39, 0.46, 0.40, 0.47, 0) == ("buy", 0.39, SIZE)  # at most SIZE
    assert fill(0.38, 500, "no", 0.39, 0.46, 0.40, 0.47, LIMIT - 20) == ("buy", 0.39, 20)
    assert fill(0.38, 500, "no", 0.39, 0.46, 0.40, 0.47, LIMIT) is None


def test_pnl_marks_and_charges_the_maker_fee():
    fills = [("buy", 0.40, 100), ("sell", 0.50, 50)]
    profit, vol, pos = pnl(fills, 0.45, False)
    assert (round(profit, 6), vol, pos) == (7.5, 150, 50)
    assert round(pnl(fills, 0.45, True)[0], 6) == round(7.5 - 0.0175 * (100 * 0.24 + 50 * 0.25), 6)


def test_replay_and_market_book_give_the_same_fills():
    """One code path: the offline replay and the paper run's MarketBook agree trade by trade."""
    sim, rng = _script("simulate_kalshi_making"), random.Random(7)
    compared = 0
    for _ in range(150):
        mid, candles, trades = rng.uniform(0.1, 0.9), [], []
        for i in range(rng.randint(1, 40)):
            mid = min(max(mid + rng.gauss(0, 0.02), 0.03), 0.97)
            w = rng.choice([0.01, 0.02, 0.04, 0.25])
            candles.append((_t(60 * i), rng.choice([round(mid - w / 2, 2), None]), round(mid + w / 2, 2)))
            for _ in range(rng.randint(0, 4)):
                trades.append((_t(60 * i + rng.randint(0, 59)), round(mid + rng.gauss(0, 0.04), 2),
                               float(rng.choice([5, 80, 400])), rng.choice(["yes", "no"])))
        start = _t(60 * rng.randint(5, 45))
        for h in (0.03, 0.05):
            want = sim.replay({"candles": candles, "trades": trades}, None, start, h, 0.0)
            book = MarketBook(start, [h])
            events = sorted([(c[0], 0, c) for c in candles] + [(t[0], 1, t) for t in sorted(trades)], key=lambda e: e[:2])
            for _, kind, e in events:
                book.snapshot(*e) if kind == 0 else book.trade(*e)
            assert book.fills[h] == want
            compared += len(want)
    assert compared > 100


def test_market_book_fails_closed():
    b = MarketBook(_t(600), [0.03], max_age=pd.Timedelta(seconds=60))
    assert b.trade(_t(5), 0.5, 10, "yes")[0] == "no_book"
    b.snapshot(_t(10), 0.40, 0.45)
    assert b.trade(_t(100), 0.6, 10, "yes")[0] == "stale_book"
    assert b.trade(_t(20), 0.6, 10, "yes")[0] == "evaluated"
    assert b.trade(_t(600) - STOP_BEFORE + pd.Timedelta(seconds=1), 0.6, 10, "yes")[0] == "after_stop"


def _market(ticker, bid, ask, vol, event="EV1"):
    return {"ticker": ticker, "event_ticker": event, "title": f"{ticker} wins", "occurrence_datetime": "2026-09-01T13:00:00Z",
            "yes_bid_dollars": f"{bid:.4f}", "yes_ask_dollars": f"{ask:.4f}", "volume_fp": str(vol)}


def _trade(tid, sec, price, count, taker):
    return {"trade_id": tid, "created_time": _t(sec).isoformat(), "yes_price_dollars": str(price),
            "count_fp": str(count), "taker_side": taker}


def test_paper_run_counts_trades_only_until_a_minute_before_the_start_seen_live(tmp_path):
    paper = _script("paper_kalshi_making")
    run = paper.PaperRun(tmp_path, pd.Timedelta(seconds=60))
    milestones = {"EV1": {"id": "M1", "start_date": "2026-09-01T10:05:00Z"}, "EV2": None}
    listing = [_market("A", 0.40, 0.44, 0), _market("B", 0.40, 0.44, 0, event="EV2")]
    run.new_markets(listing, milestones.get, _t(0))
    assert run.on_listing(listing, _t(0)) == []                     # baseline volume: nothing to fetch yet
    run.on_status({"M1": "not_started"}, _t(1))
    assert "EV2" in run.started                                     # no milestone: never quoted
    listing = [_market("A", 0.40, 0.44, 300)]
    assert run.on_listing(listing, _t(100)) == ["A"]
    run.on_status({"M1": "not_started"}, _t(101))                   # horizon: 41 s
    run.on_trades("A", [_trade("t1", 30, 0.48, 100, "yes"), _trade("t2", 60, 0.47, 100, "yes"),
                        _trade("t3", 90, 0.37, 100, "no")])
    assert run.evaluate(_t(102)) == 2                               # t1 fills both widths; t2, t3 wait
    run.on_status({"M1": "live"}, _t(111))                          # started: the stop stays at 41 s
    assert run.evaluate(_t(112)) == 0 and run.pending["A"] == {}
    fills = pd.read_csv(tmp_path / "fills.csv")
    assert list(fills["trade_id"]) == ["t1", "t1"] and set(fills["h"]) == {0.03, 0.05}
    assert set(pd.read_csv(tmp_path / "trades.csv")["trade_id"]) == {"t1"}
    status = pd.read_csv(tmp_path / "status.csv", keep_default_na=False)
    assert dict(zip(status["event_ticker"], status["status"])) == {"EV2": "no_milestone", "EV1": "live"}

    again = paper.PaperRun(tmp_path, pd.Timedelta(seconds=60))     # a restart keeps positions and the stop
    assert again.books["A"].pos == run.books["A"].pos and again.books["A"].stop == _t(41)
    assert again.started == {"EV1", "EV2"}


def test_report_drops_fills_after_the_true_start_and_marks_at_the_last_mid():
    paper = _script("paper_kalshi_making")
    markets = pd.DataFrame([{"ticker": "A", "event_ticker": "EV1"}])
    status = pd.DataFrame([{"event_ticker": "EV1", "last_not_started_utc": _t(600).isoformat()}])
    fills = pd.DataFrame([
        {"ticker": "A", "ts": _t(100), "h": 0.03, "side": "sell", "price": 0.46, "contracts": 100.0},
        {"ticker": "A", "ts": _t(400), "h": 0.03, "side": "buy", "price": 0.30, "contracts": 100.0},  # after the true start
    ])
    snaps = pd.DataFrame([{"ticker": "A", "ts": _t(0), "bid": 0.40, "ask": 0.44},
                          {"ticker": "A", "ts": _t(200), "bid": 0.42, "ask": 0.46}])
    d = paper.settle(markets, status, fills, snaps, {"A": "no"}, {"A": _t(360)})
    r = d[(d["h"] == 0.03) & ~d["maker_fee"]].iloc[0]
    assert r["contracts"] == 100 and round(r["held"], 6) == 46.0 and round(r["marked"], 6) == round(100 * (0.46 - 0.44), 6)
    assert round(r["markout_1m"], 6) == round(100 * (0.46 - 0.42), 6)


def test_paper_run_never_sends_an_order():
    src = (ROOT / "scripts" / "paper_kalshi_making.py").read_text(encoding="utf-8")
    assert not re.search(r"\.(post|put|delete|patch)\(", src)
    assert "/portfolio" not in src and "/orders" not in src
