"""Rules of registration 2026-11-04 (Kalshi blend at the open), on synthetic quotes."""
import json
from pathlib import Path

import pandas as pd
import pytest

from scripts import track_kalshi_blend_rule as T

START = pd.Timestamp("2026-11-10T15:00:00Z")
REG = pd.Timestamp("2026-11-04T18:00:00Z")


def q(rows):
    return pd.DataFrame([{"polled_utc": pd.Timestamp(t), "ticker": tk, "bid": b, "ask": a} for t, tk, b, a in rows])


def test_open_is_first_tight_snapshot_an_hour_before_and_close_is_last_before_live():
    g = q([("2026-11-10T09:00Z", "A", 0.40, 0.60), ("2026-11-10T09:00Z", "B", 0.40, 0.60),     # too wide
           ("2026-11-10T10:00Z", "A", 0.55, 0.58), ("2026-11-10T10:00Z", "B", 0.42, 0.45),     # open
           ("2026-11-10T14:30Z", "A", 0.60, 0.62), ("2026-11-10T14:30Z", "B", 0.38, 0.40),     # close (live at 14:40)
           ("2026-11-10T14:45Z", "A", 0.90, 0.92), ("2026-11-10T14:45Z", "B", 0.08, 0.10)])    # in play: ignored
    s = T.decide("EV", g, START, pd.Timestamp("2026-11-10T14:40Z"), REG)
    assert s["open_t"] == pd.Timestamp("2026-11-10T10:00Z")
    assert s["close_t"] == pd.Timestamp("2026-11-10T14:30Z")
    assert s["close_mid"]["A"] == pytest.approx(0.61)


def test_no_open_within_the_last_hour_and_nothing_before_registration():
    g = q([("2026-11-10T14:30Z", "A", 0.55, 0.58), ("2026-11-10T14:30Z", "B", 0.42, 0.45)])
    assert T.decide("EV", g, START, None, REG) is None
    g2 = q([("2026-11-03T10:00Z", "A", 0.55, 0.58), ("2026-11-03T10:00Z", "B", 0.42, 0.45)])
    assert T.decide("EV", g2, pd.Timestamp("2026-11-03T15:00Z"), None, REG) is None


def test_bet_does_not_depend_on_which_player_is_first():
    w = json.loads((Path(T.__file__).resolve().parents[1] / "research_tests/open_clv/kalshi_blend_weights.json").read_text())["weights"]
    o = pd.DataFrame({"bid": [0.55, 0.40], "ask": [0.58, 0.43]}, index=["A", "B"])
    x = {k: 0.0 for k in w if k != "open"}
    x["layoff"] = 1.0                                   # A returns from a layoff
    ab = T.bet_for(o, "A", "B", x, w)
    ba = T.bet_for(o, "B", "A", {k: -v for k, v in x.items()}, w)
    assert ab["backed_ticker"] == ba["backed_ticker"] and ab["edge"] == pytest.approx(ba["edge"])
    assert ab["p_model_a"] == pytest.approx(1 - ba["p_model_a"], abs=1e-4)
    assert ab["backed_ticker"] == "B"                   # the layoff weight is negative: lean to the opponent


def test_cost_takes_the_cheaper_route_and_the_fee():
    w = {"open": 1.0}
    o = pd.DataFrame({"bid": [0.50, 0.46], "ask": [0.53, 0.49]}, index=["A", "B"])
    b = T.bet_for(o, "A", "B", {}, w)
    side_a = 0.53 if 0.53 <= 1 - 0.46 else 1 - 0.46
    assert b["price"] in (round(side_a, 4), round(min(0.49, 1 - 0.50), 4))
    assert b["fee_per_contract"] == T.taker_fee_per_contract(b["price"])
    assert b["bet"] is False                            # no signal, no 3-point edge


def test_edge_split_adds_up_and_stretch_alone_never_bets():
    w = json.loads((Path(T.__file__).resolve().parents[1] / "research_tests/open_clv/kalshi_blend_weights.json").read_text())["weights"]
    o = pd.DataFrame({"bid": [0.79, 0.19], "ask": [0.81, 0.21]}, index=["A", "B"])
    b = T.bet_for(o, "A", "B", {k: 0.0 for k in w if k != "open"}, w)
    assert b["signal_pts"] == pytest.approx(0.0, abs=1e-9)          # no signals: all of the move is the stretch
    assert 0 < abs(b["stretch_pts"]) < 2.0
    assert b["bet"] is False and b["clears_on_signals_alone"] is False
    x = {k: 0.0 for k in w if k != "open"}
    x["layoff"] = -1.0
    b2 = T.bet_for(o, "A", "B", x, w)
    p_back = b2["model_chance"]
    p_open_back = 0.80 if b2["backed_ticker"] == "A" else 0.20
    assert (b2["stretch_pts"] + b2["signal_pts"]) / 100 == pytest.approx(p_back - p_open_back, abs=1e-4)
