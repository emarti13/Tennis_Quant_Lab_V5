"""Registration 2026-11-21 (order-book wall) on synthetic book rows."""
from types import SimpleNamespace as R

import pandas as pd
import pytest

from scripts import track_wall_rule as W


def row(t, yes, no, by, bn):
    return {"t": pd.Timestamp(t), "yes_levels": yes, "no_levels": no, "best_yes_bid": by, "best_no_bid": bn}


def test_wall_needs_share_ratio_side_and_dollars():
    ok = R(yes_levels="0.45:40;0.44:3000;0.43:50", no_levels="0.53:200;0.52:100", best_yes_bid=0.45, best_no_bid=0.53)
    w = W.wall(ok)
    assert w == {"side": "yes", "wall_price": 0.44, "wall_contracts": 3000.0}
    small = R(yes_levels="0.45:40;0.44:1000;0.43:50", no_levels="0.53:200", best_yes_bid=0.45, best_no_bid=0.53)  # $440
    assert W.wall(small) is None
    balanced = R(yes_levels="0.45:40;0.44:3000;0.43:50", no_levels="0.53:2000;0.52:100", best_yes_bid=0.45, best_no_bid=0.53)
    assert W.wall(balanced) is None                                        # other side not under half
    two = R(yes_levels="0.45:1400;0.44:3000", no_levels="0.53:100", best_yes_bid=0.45, best_no_bid=0.53)
    assert W.wall(two) is None                                             # not 3x the next level


def test_decision_first_wall_an_hour_before_with_the_price_cap_and_close():
    start = pd.Timestamp("2026-11-23T15:00Z")
    g = pd.DataFrame([row("2026-11-23T10:00Z", "0.45:40;0.44:3000", "0.53:200", 0.45, 0.53),     # wall; YES ask 0.47 <= 0.44 + 0.03
                      row("2026-11-23T14:30Z", "0.50:100", "0.48:100", 0.50, 0.48)])            # close: YES mid (0.50 + 0.52) / 2
    d = W.decide(g, start, pd.Timestamp("2026-11-22T00:00Z"))
    assert d["side"] == "yes" and d["price"] == pytest.approx(0.47)
    assert d["p_close"] == pytest.approx(0.51) and d["clv_per_contract"] == pytest.approx(0.51 - 0.47 - d["fee_per_contract"])
    far = pd.DataFrame([row("2026-11-23T10:00Z", "0.45:40;0.40:3000", "0.53:200", 0.45, 0.53)])  # ask 0.47 > 0.40 + 0.03
    assert W.decide(far, start, pd.Timestamp("2026-11-22T00:00Z")) is None
    late = pd.DataFrame([row("2026-11-23T14:30Z", "0.45:40;0.44:3000", "0.53:200", 0.45, 0.53)])  # within the last hour
    assert W.decide(late, start, pd.Timestamp("2026-11-22T00:00Z")) is None
