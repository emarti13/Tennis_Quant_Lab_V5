"""De-vig on the Box-Cox scale, the cautious edge rule, exchange fees; results joined by ids."""
from __future__ import annotations

import pandas as pd
import pytest

from v5_devig import (
    DEFAULT_LAM, book_lam, cautious_edge, cautious_fair, devig, devig_power, exchange_fair, expected_value, kalshi_ev, kalshi_fee,
)
from v5_market_results import fixture_winners

PRICES = [1.25, 4.2]           # implied 0.8 + 0.238: a 3.8% margin


def test_lam_zero_is_same_share_and_lam_one_is_same_amount():
    p = [1 / 1.25, 1 / 4.2]
    assert devig(PRICES, 0) == pytest.approx([p[0] / sum(p), p[1] / sum(p)])
    margin = sum(p) - 1
    assert devig(PRICES, 1) == pytest.approx([p[0] - margin / 2, p[1] - margin / 2], abs=1e-9)


def test_higher_lam_takes_more_from_the_longshot_and_power_sits_near_one_and_a_half():
    favs = [devig(PRICES, lam)[0] for lam in (0, 0.5, 1, 2, 3)]
    assert favs == sorted(favs)
    assert devig(PRICES, 1.4)[0] < devig_power(PRICES)[0] < devig(PRICES, 1.6)[0]
    for lam in (0, 1, 2.5):
        assert sum(devig(PRICES, lam)) == pytest.approx(1)


def test_even_prices_stay_even_and_bad_input_fails_closed():
    assert devig([1.9, 1.9], 2) == pytest.approx([0.5, 0.5])
    for bad in ([1.0, 3.0], [0.9, 3.0], [2.0], [float("nan"), 2.0]):
        with pytest.raises(ValueError):
            devig(bad, 0)
    with pytest.raises(ValueError):
        devig(PRICES, -1)


def test_cautious_rule_uses_the_least_favourable_benchmark_for_each_side():
    assert cautious_fair(PRICES, 0) == pytest.approx(max(devig(PRICES, 0)[0], devig(PRICES, 1)[0], devig_power(PRICES)[0]))
    assert cautious_fair(PRICES, 1) == pytest.approx(devig(PRICES, 0)[1])        # the longshot: multiplicative is highest
    assert cautious_fair(PRICES, 0, book_lam=3.0) == pytest.approx(devig(PRICES, 3.0)[0])
    assert cautious_edge(0.80, PRICES, 0) == pytest.approx(0.80 - cautious_fair(PRICES, 0))
    with pytest.raises(ValueError):
        cautious_edge(1.2, PRICES, 0)


def test_ev_and_kalshi_fees():
    assert expected_value(0.55, 2.0) == pytest.approx(0.10)
    assert exchange_fair(0.48, 0.50) == pytest.approx(0.49)
    with pytest.raises(ValueError):
        exchange_fair(0.5, 0.5)
    assert kalshi_fee(0.50) == 0.02 and kalshi_fee(0.50, 100) == 1.75 and kalshi_fee(0.90, 10) == 0.07
    assert kalshi_ev(0.60, 0.50, 100) == pytest.approx((60 - 51.75) / 51.75)


def test_winners_join_by_edition_and_both_player_ids_and_skip_ambiguous_pairs():
    fixtures = pd.DataFrame([
        {"fixture_id": "f1", "edition_key": "E1", "player1_id": "M-1", "player2_id": "M-2"},
        {"fixture_id": "f2", "edition_key": "E1", "player1_id": "M-3", "player2_id": "M-4"},   # met twice: ambiguous
        {"fixture_id": "f3", "edition_key": "E2", "player1_id": "M-1", "player2_id": "M-2"},   # no result there
        {"fixture_id": "f4", "edition_key": "", "player1_id": "M-1", "player2_id": "M-2"},     # unresolved edition
    ])
    results = pd.DataFrame([
        {"edition_key": "E1", "winner_id": "M-2", "loser_id": "M-1"},
        {"edition_key": "E1", "winner_id": "M-3", "loser_id": "M-4"},
        {"edition_key": "E1", "winner_id": "M-4", "loser_id": "M-3"},
    ])
    assert fixture_winners(fixtures, results).to_dict("records") == [{"fixture_id": "f1", "winner_side": "p2"}]


def test_every_book_uses_the_measured_default_until_data_separates_them():
    assert DEFAULT_LAM == 1.0 and book_lam("pinnacle") == book_lam("bet365") == 1.0


def test_tml_rows_without_an_id_join_through_their_name_node():
    from v5_market_results import tml_results
    matches = pd.DataFrame([{"tour": "W", "tourney_id": "T1", "date": pd.Timestamp("2026-06-22"),
                             "winner_id": float("nan"), "winner_name": "Tatjana Maria",
                             "loser_id": "238184", "loser_name": "Tereza Valentova"}])
    crosswalk = pd.DataFrame([{"tournament_id": "T1", "first_date": "2026-06-22", "last_date": "2026-06-22",
                               "edition_key": "WTA|e", "status": "confirmed"}])
    alias = pd.DataFrame([{"tour": "W", "tml_id": "name:maria tatjana", "player_id": "W-1", "status": "auto"},
                          {"tour": "W", "tml_id": "238184", "player_id": "W-2", "status": "auto"}])
    assert tml_results(matches, crosswalk, alias).to_dict("records") == [
        {"edition_key": "WTA|e", "winner_id": "W-1", "loser_id": "W-2"}]
