"""Registration 2026-11-03 tracker: the rule picks the right snapshot, side and price, and settles."""
from __future__ import annotations

import pandas as pd

import scripts.track_longshot_rule as tr

REG = pd.Timestamp("2026-11-03T15:00:00Z")
START = pd.Timestamp("2026-11-04T12:00:00Z")


def _q(t, bid_ls, ask_ls, bid_f, ask_f, ev="E1", start=START, series="KXATPCHALLENGERMATCH"):
    return [{"polled_utc": pd.Timestamp(t), "series": series, "event_ticker": ev, "ticker": f"{ev}-LS", "start_date": start,
             "bid": bid_ls, "ask": ask_ls},
            {"polled_utc": pd.Timestamp(t), "series": series, "event_ticker": ev, "ticker": f"{ev}-FAV", "start_date": start,
             "bid": bid_f, "ask": ask_f}]


def test_uses_the_latest_snapshot_6h_to_60min_before_and_the_cheaper_side():
    q = pd.DataFrame(_q("2026-11-04T05:00Z", 0.10, 0.12, 0.87, 0.90)        # 7 h before: outside the window
                     + _q("2026-11-04T09:00Z", 0.18, 0.20, 0.79, 0.83)      # 3 h before
                     + _q("2026-11-04T10:55Z", 0.15, 0.17, 0.82, 0.84)      # 65 min before: the one used
                     + _q("2026-11-04T11:30Z", 0.05, 0.06, 0.94, 0.95))     # 30 min before: too late
    d = tr.decisions(q, {}, REG)
    assert len(d) == 1
    r = d.iloc[0]
    assert r["decided_utc"].startswith("2026-11-04T10:55") and r["longshot_ticker"] == "E1-LS"
    assert r["bet"] == "YES on favourite" and r["price"] == 0.84              # 0.84 < 1 - 0.15
    assert abs(r["fee_per_contract"] - 0.0095) < 1e-9          # 94.08 cents for 100 contracts, rounded up to 95


def test_skips_before_registration_wide_spreads_started_matches_and_no_longshot():
    rows = (_q("2026-11-03T09:00Z", 0.15, 0.17, 0.82, 0.84, ev="OLD", start=pd.Timestamp("2026-11-03T12:00Z"))
            + _q("2026-11-04T10:00Z", 0.15, 0.25, 0.75, 0.84, ev="WIDE")
            + _q("2026-11-04T10:00Z", 0.15, 0.17, 0.82, 0.84, ev="LIVE")
            + _q("2026-11-04T10:00Z", 0.35, 0.37, 0.62, 0.64, ev="EVEN"))
    d = tr.decisions(pd.DataFrame(rows), {"LIVE": pd.Timestamp("2026-11-04T09:30Z")}, REG)
    assert d.empty


def test_settles_from_results_and_reuses_known_ones():
    d = tr.decisions(pd.DataFrame(_q("2026-11-04T10:00Z", 0.15, 0.17, 0.82, 0.86)), {}, REG)
    assert d.iloc[0]["bet"] == "NO on long shot" and d.iloc[0]["price"] == 0.85
    calls = []

    def get(path):
        calls.append(path)
        return {"market": {"result": "no"}}
    s = tr.settle(d, pd.DataFrame(), get)
    fee = s.iloc[0]["fee_per_contract"]
    assert s.iloc[0]["pnl_per_contract"] == 1 - 0.85 - fee and calls == ["/markets/E1-LS"]
    s2 = tr.settle(d, s, get)
    assert len(calls) == 1 and s2.iloc[0]["result"] == "no"
    summ = tr.summary(s2)
    assert summ["settled"] == 1 and summ["status"] == "running" and summ["favourite_won"] == 1.0
