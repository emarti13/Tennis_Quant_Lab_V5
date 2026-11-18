"""Registration 2026-11-18 (in-play rules) on a synthetic live log."""
import pandas as pd
import pytest

from scripts import track_inplay_rules as T

REG = pd.Timestamp("2026-11-19T00:00:00Z")


def row(t, status, s1, s2, g1, g2, p1, p2, server, b1, a1, b2, a2):
    return {"t": pd.Timestamp(t), "series": "KXWTAMATCH", "event_ticker": "EV", "match_status": status, "competitor_1": "A",
            "server": server, "sets_1": s1, "sets_2": s2, "games_1": g1, "games_2": g2, "points_1": p1, "points_2": p2,
            "ticker_1": "EV-A", "ticker_2": "EV-B", "bid_1": b1, "ask_1": a1, "bid_2": b2, "ask_2": a2}


def log():
    return pd.DataFrame([
        row("2026-11-20T10:00Z", "not_started", 0, 0, 0, 0, 0, 0, None, 0.59, 0.61, 0.39, 0.41),
        row("2026-11-20T10:05Z", "1st_set", 0, 0, 0, 0, 0, 0, "A", 0.59, 0.61, 0.39, 0.41),
        row("2026-11-20T11:00Z", "2nd_set", 1, 0, 5, 3, 0, 0, "A", 0.95, 0.96, 0.04, 0.05),   # A serves for the match
        row("2026-11-20T11:03Z", "2nd_set", 1, 0, 5, 3, 15, 40, "A", 0.90, 0.92, 0.08, 0.10),
        row("2026-11-20T11:05Z", "2nd_set", 1, 0, 5, 4, 0, 0, "B", 0.85, 0.87, 0.13, 0.15),   # A broken: B serves
        row("2026-11-20T11:30Z", "3rd_set", 1, 1, 0, 0, 0, 0, "A", 0.55, 0.57, 0.43, 0.45),
    ])


def test_serve_out_and_breaker_decisions():
    out = T.event_decisions("EV", log(), {"best_of": "3", "tournament_name": "WTA Test"}, REG)
    by = {d["rule"]: d for d in out}
    assert by["serve_out"]["backed"] == 2 and by["serve_out"]["score"] == "sets 1-0 games 5-3"
    assert by["breaker"]["backed"] == 2 and by["breaker"]["score"] == "sets 1-0 games 5-4"
    assert by["breaker"]["mid_backed_at_set_end"] == pytest.approx(0.44 / (0.56 + 0.44), abs=1e-4)
    assert all(d["scored"] for d in out if d["rule"] in ("serve_out", "breaker"))      # WTA


def test_cost_takes_the_cheaper_route_with_fee():
    r = log().iloc[2]
    price, fee, how = T.buy(r, 2)
    assert price == min(0.05, 1 - 0.95) and fee == T.taker_fee_per_contract(price)


def test_nothing_before_registration_and_one_decision_per_rule():
    early = log().assign(t=lambda d: d["t"] - pd.Timedelta(days=5))
    assert T.event_decisions("EV", early, {"best_of": 3}, REG) == []
    out = T.event_decisions("EV", log(), {"best_of": 3}, REG)
    assert len({d["rule"] for d in out}) == len(out)


def test_serving_for():
    assert T.serving_for(5, 4) and T.serving_for(6, 5) and not T.serving_for(5, 5) and not T.serving_for(4, 5)
