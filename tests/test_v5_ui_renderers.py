from __future__ import annotations

import pandas as pd


class _Context:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeSt(_Context):
    def __init__(self):
        self.markdowns = []
        self.infos = []
        self.warnings = []
        self.dataframes = []
        self.metrics = []
        self.captions = []
        self.json_payloads = []

    def markdown(self, value, **kwargs):
        self.markdowns.append(str(value))

    def info(self, value):
        self.infos.append(str(value))

    def warning(self, value):
        self.warnings.append(str(value))

    def caption(self, value):
        self.captions.append(str(value))

    def dataframe(self, value, **kwargs):
        self.dataframes.append(value)

    def metric(self, label, value, **kwargs):
        self.metrics.append((str(label), str(value)))

    def columns(self, n):
        return [self for _ in range(n)]

    def expander(self, *args, **kwargs):
        return self

    def json(self, value):
        self.json_payloads.append(value)

    def text_input(self, *args, **kwargs):
        return ""

    def selectbox(self, *args, **kwargs):
        options = kwargs.get("options")
        if options is None and len(args) > 1:
            options = args[1]
        return options[0] if options else "All"

    def checkbox(self, *args, **kwargs):
        return False


def test_match_detail_renderer_has_deliberate_missing_selection_state():
    from v5_ui_match_detail import render_match_detail

    fake = FakeSt()
    render_match_detail(fake, None, pd.DataFrame())

    assert fake.infos
    assert "select" in fake.infos[0].lower()


def test_performance_renderer_separates_market_and_fixture_headlines():
    from v5_ui_performance import render_performance_page

    fake = FakeSt()
    report = {
        "status": "ok",
        "raw_markets": {"wins": 3, "losses": 2, "pushes": 0, "win_rate": 0.60, "roi": 0.10, "net_units": 0.5},
        "fixture_clusters": {"fixtures": 3, "profitable_fixtures": 1, "profitable_fixture_rate": 1 / 3, "max_markets_on_one_fixture": 3, "mean_markets_per_fixture": 5/3, "net_units": 0.5},
        "moneyline_calibration": {"n": 2, "brier": 0.20, "log_loss": 0.60},
    }
    render_performance_page(fake, report)

    labels = {label for label, _ in fake.metrics}
    assert "Market record" in labels
    assert "Fixture evidence" in labels
    assert "Max plays on one match" in labels  # customer-facing label for correlated markets


def test_model_health_renderer_shows_production_candidates():
    from v5_ui_health import render_model_health_page

    fake = FakeSt()
    health = {
        "overall": "healthy",
        "winner_models": {"MEN": "ensemble", "WTA": "residual"},
        "score_models": {"MEN": "gaussian_contextual", "WTA": "gaussian_contextual"},
        "full_regression": "success",
        "streamlit_smoke": "success",
        "score_validation": "success",
        "artifacts": {},
    }
    render_model_health_page(fake, health)

    combined = " ".join(text for pair in fake.metrics for text in pair)
    assert "ensemble" in combined
    assert "residual" in combined
    assert "gaussian_contextual" in combined


def test_all_markets_renderer_has_empty_state_without_board():
    from v5_ui_all_markets import render_all_markets_page

    fake = FakeSt()
    render_all_markets_page(fake, pd.DataFrame())

    assert fake.infos
    assert "market" in fake.infos[0].lower()
