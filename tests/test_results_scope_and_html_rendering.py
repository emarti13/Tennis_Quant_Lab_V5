from __future__ import annotations

import pandas as pd


def test_render_today_uses_streamlit_html_for_match_cards():
    from v5_ui_today import render_today_results

    class FakeCol:
        def markdown(self, *args, **kwargs):
            pass

    class FakeSt:
        def __init__(self):
            self.html_messages = []
            self.markdown_messages = []
        def caption(self, *args, **kwargs):
            pass
        def columns(self, n):
            return [FakeCol() for _ in range(n)]
        def markdown(self, body, **kwargs):
            self.markdown_messages.append(body)
        def html(self, body):
            self.html_messages.append(body)
        def info(self, *args, **kwargs):
            pass

    board = pd.DataFrame([{
        "Fixture ID":"fx1","Player 1":"A","Player 2":"B","Tournament":"T",
        "Tour":"MEN","Best Of":3,"P1 V5 %":0.6,"P2 V5 %":0.4,"P1 Fair":-150,"P2 Fair":150,
        "P1 ML":-110,"P1 ML EV":0.08,"P1 ML Signal":"BET","Agreement":0.8,
        "Expected Margin":2.0,"Expected Total":22.0,
    }])
    fake = FakeSt()
    render_today_results(fake, board, pd.DataFrame(), "snapshot")
    assert fake.html_messages, "match cards must use st.html rather than Markdown"
    assert any('class="v5-card"' in x for x in fake.html_messages)
    assert not any('class="v5-card"' in x for x in fake.markdown_messages)


def test_accuracy_metrics_defaults_to_actionable_recommendations_only():
    from results_accuracy_page import accuracy_metrics

    df = pd.DataFrame([
        {"result_status":"SETTLED","settled_result":"WIN","signal":"BET","profit_units":1.0},
        {"result_status":"SETTLED","settled_result":"LOSS","signal":"LEAN","profit_units":-1.0},
        {"result_status":"SETTLED","settled_result":"LOSS","signal":"PASS","profit_units":-1.0},
        {"result_status":"SETTLED","settled_result":"LOSS","signal":"REVIEW","profit_units":-1.0},
    ])
    out = accuracy_metrics(df)
    assert out["decisions"] == 2
    assert out["wins"] == 1
    assert out["losses"] == 1
    assert out["units"] == 0.0
    assert out["win_rate"] == 0.5


def test_accuracy_metrics_can_audit_all_settled_rows_explicitly():
    from results_accuracy_page import accuracy_metrics

    df = pd.DataFrame([
        {"result_status":"SETTLED","settled_result":"WIN","signal":"BET","profit_units":1.0},
        {"result_status":"SETTLED","settled_result":"LOSS","signal":"PASS","profit_units":-1.0},
    ])
    out = accuracy_metrics(df, actionable_only=False)
    assert out["decisions"] == 2


def test_settled_performance_report_separates_actionable_from_all_market_rows():
    from diagnose_v5_settled_performance import settled_performance_report

    frame = pd.DataFrame([
        {"freeze_key":"1","fixture_id":"a","settled_result":"WIN","signal":"BET","profit_units":1.0,"market_group":"moneyline","model_probability":0.6},
        {"freeze_key":"2","fixture_id":"a","settled_result":"LOSS","signal":"PASS","profit_units":-1.0,"market_group":"game_spread","model_probability":0.4},
        {"freeze_key":"3","fixture_id":"b","settled_result":"LOSS","signal":"LEAN","profit_units":-1.0,"market_group":"moneyline","model_probability":0.55},
        {"freeze_key":"4","fixture_id":"c","settled_result":"LOSS","signal":"REVIEW","profit_units":-1.0,"market_group":"total_games","model_probability":0.52},
    ])
    report = settled_performance_report(frame)
    assert report["raw_markets"]["bets"] == 4
    assert report["actionable_markets"]["bets"] == 2
    assert report["actionable_markets"]["wins"] == 1
    assert report["actionable_fixture_clusters"]["fixtures"] == 2


def test_performance_headline_prefers_actionable_results_when_available():
    from v5_ui_performance import headline_metrics

    report = {
        "raw_markets": {"wins": 10, "losses": 90, "pushes": 0, "win_rate": .10, "roi": -.5, "net_units": -50},
        "fixture_clusters": {"fixtures": 20, "profitable_fixtures": 2, "profitable_fixture_rate": .10, "net_units": -50, "max_markets_on_one_fixture": 10},
        "actionable_markets": {"wins": 3, "losses": 2, "pushes": 0, "win_rate": .60, "roi": .08, "net_units": .4},
        "actionable_fixture_clusters": {"fixtures": 4, "profitable_fixtures": 2, "profitable_fixture_rate": .50, "net_units": .4, "max_markets_on_one_fixture": 2},
    }
    out = headline_metrics(report)
    assert out["market_record"] == "3-2-0"
    assert out["market_win_rate"] == .60
    assert out["fixture_record"] == "2 profitable / 4"

# This file intentionally provides regression contracts for the production UI/reporting split.
