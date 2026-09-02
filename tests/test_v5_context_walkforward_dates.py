import pandas as pd

from build_v5_context_matchups import _prepare_walkforward


def test_prepare_walkforward_parses_yyyymmdd_integer_dates_as_calendar_dates():
    wf = pd.DataFrame([
        {"date": 20250110, "tour": "MEN", "winner": "Alpha", "loser": "Beta"},
        {"date": 20260111.0, "tour": "MEN", "winner": "Gamma", "loser": "Delta"},
    ])
    out = _prepare_walkforward(wf, (2025, 2026))
    assert out["_date"].dt.strftime("%Y-%m-%d").tolist() == ["2025-01-10", "2026-01-11"]
    assert out["_year"].tolist() == [2025, 2026]


def test_prepare_walkforward_preserves_iso_dates():
    wf = pd.DataFrame([
        {"date": "2025-02-03", "tour": "WTA", "winner": "Alpha", "loser": "Beta"},
    ])
    out = _prepare_walkforward(wf, (2025,))
    assert out.iloc[0]["_date"] == pd.Timestamp("2025-02-03")
