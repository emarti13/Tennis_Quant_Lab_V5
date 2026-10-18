"""The app's override run and the daily batch share one pricing function (rebuild plan Step 4g)."""
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

import v5_daily_batch
import v5_interactive_production as vip
from v5_fixture_resolution import FixtureResolutionError, ResolvedFixture, ResolvedPlayer
from v5_pricing import Price

NOW = datetime(2026, 9, 1, 6, 0, tzinfo=timezone.utc)


class _Resolver:
    def __init__(self, overrides=None):
        self.overrides = pd.DataFrame(overrides or [], columns=["edition_key", "field", "value"])

    def resolve(self, fid):
        if fid == "unknown":
            raise FixtureResolutionError("TOURNAMENT_UNRESOLVED", "Mystery Open")
        surface = "Hard"
        for r in self.overrides.itertuples():
            if r.field == "surface":
                surface = r.value
        p = ResolvedPlayer("1", "x", "M-1", "auto", None)
        return ResolvedFixture(fid, "ATP|2026-08-31|x|x", "MEN", "ATP", "X", surface, "Outdoor", 3, {}, {}, p, p)


class _Ctx:
    """Prices from the resolver's surface, so an edit changes the price."""
    def __init__(self, overrides=None):
        self.resolver = _Resolver(overrides)

    def with_overrides(self, rows):
        return _Ctx(list(self.resolver.overrides.to_dict("records")) + rows)

    def price(self, fid, **kw):
        r = self.resolver.resolve(fid)
        p1 = 0.70 if r.surface == "Clay" else 0.60
        return Price(fid, "priced", "OK", r.edition_key, "MEN", "ATP", r.surface, r.setting, 3, "main", "after_start",
                     "M-1", "M-2", (50, 40), p1, True)


def _feed():
    base = {"snapshot_utc": "2026-09-01T05:00:00Z", "start_time_utc": "2026-09-01T07:00:00Z", "tournament": "X Open",
            "tour": "ATP", "player1": "Alpha, A", "player2": "Beta, B", "market_group": "moneyline", "line": None,
            "best_decimal_odds": 1.8, "best_american_odds": -125}
    return pd.DataFrame([{**base, "fixture_id": "fx1", "selection": "Alpha, A"},
                         {**base, "fixture_id": "fx1", "selection": "Beta, B"}])


def _editor(**edit):
    return pd.DataFrame([{"Fixture ID": "fx1", "Player 1": "Alpha, A", "Player 2": "Beta, B", **edit}])


def test_override_run_without_edits_reproduces_the_daily_batch():
    board, _, _, _ = v5_daily_batch.build_daily_outputs(_feed(), _Ctx(), now=NOW)
    today, errors, overrides = vip.run_interactive_production(_feed(), _editor(), _Ctx(), now=NOW)
    assert errors == [] and overrides == []
    assert today.iloc[0]["P1 V5 %"] == pytest.approx(float(board["full_context_probability_p1"].iloc[0]))
    assert vip.production_board_to_today(board).equals(today)


def test_an_edit_becomes_an_override_and_changes_the_price():
    today, errors, overrides = vip.run_interactive_production(_feed(), _editor(Surface="Clay"), _Ctx(), now=NOW)
    assert errors == []
    assert [(o["field"], o["value"]) for o in overrides] == [("surface", "Clay")]
    assert today.iloc[0]["P1 V5 %"] == pytest.approx(0.70) and today.iloc[0]["Surface"] == "Clay"


def test_unchanged_fields_write_nothing_and_unresolved_fixtures_report_why():
    rows, errors = vip.edits_to_overrides(_editor(Surface="Hard", **{"Best Of": 3}), _Ctx())
    assert rows == [] and errors == []
    rows, errors = vip.edits_to_overrides(pd.DataFrame([{"Fixture ID": "unknown", "Surface": "Clay"}]), _Ctx())
    assert rows == [] and "TOURNAMENT_UNRESOLVED" in errors[0]["error"]


def test_saved_overrides_keep_the_newest_edit_per_edition_and_field(tmp_path):
    edit = {"edition_key": "ATP|2026-08-31|x|x", "field": "surface", "set_on": "2026-09-01", "note": "test"}
    assert vip.save_overrides([{**edit, "value": "Clay"}], tmp_path) == 1
    assert vip.save_overrides([{**edit, "value": "Grass"}, {**edit, "field": "court_speed", "value": "40"}], tmp_path) == 1
    saved = pd.read_csv(tmp_path / vip.OVERRIDES_PATH, dtype=str)
    assert saved[["field", "value"]].values.tolist() == [["surface", "Grass"]]     # court_speed is not overridable


def test_today_view_shows_why_a_fixture_has_no_price():
    from v5_pricing import board_rows
    thin = Price("fx1", "no_price", "THIN_HISTORY", "ATP|2026-08-31|x|x", "WTA", "WTA", "Hard", "Indoor", 3, "qualifying",
                 "played_before", "W-1", "W-2", (40, 3))
    row = vip.production_board_to_today(board_rows(_feed(), thin, frozen_at="t")).iloc[0]
    assert row["Status"] == "THIN_HISTORY" and row["P1 V5 %"] is None
    assert row["Tour"] == "WTA" and row["Best Of"] == 3 and row["Stage"] == "qualifying" and not row["Official Eligible"]


def test_decision_feed_reads_active_or_canonical_artifacts_without_running_model():
    source = Path("v5_ui_host.py").read_text(encoding="utf-8")
    render_block = source[source.index("def _render_decision_feed_page"):source.index("\ndef _canonical_prepared_board")]
    assert "load_canonical_today_board(" in render_block
    assert "get_active_board(" in render_block
    assert "run_interactive_production(" not in render_block
    assert "build_context_warehouse(" not in render_block
    assert '"_batch_one_match"' not in render_block


def test_today_view_takes_fixture_fields_from_the_forecast_when_the_repriced_rows_lack_them():
    # Repricing joins frozen probabilities to moneyline rows only; a no-price fixture has none.
    repriced = _feed().assign(model_probability=float("nan"))
    forecast = pd.DataFrame([{"fixture_id": "fx1", "price_status": "no_price", "price_reason": "NO_HISTORY",
                              "tour_v5": "MEN", "surface": "Clay", "best_of": 3, "stage": "main"}])
    row = vip.production_board_to_today(repriced, fixtures=forecast).iloc[0]
    assert row["Status"] == "NO_HISTORY" and row["Surface"] == "Clay" and row["Stage"] == "main"
