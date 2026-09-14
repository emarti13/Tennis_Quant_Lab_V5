import json

import pandas as pd

from v5_results_reset import filter_since_reset, load_reset_timestamp


def test_load_reset_timestamp_reads_config(tmp_path):
    config = tmp_path / "results_reset.json"
    config.write_text(json.dumps({"reset_at_utc": "2026-09-14T16:26:28Z"}), encoding="utf-8")
    ts = load_reset_timestamp(config)
    assert ts == pd.Timestamp("2026-09-14T16:26:28Z")


def test_filter_since_reset_excludes_old_rows_and_keeps_new_rows():
    frame = pd.DataFrame([
        {"market_key": "old", "frozen_at_utc": "2026-09-14T16:20:00Z"},
        {"market_key": "new", "frozen_at_utc": "2026-09-14T16:30:00Z"},
    ])
    out = filter_since_reset(frame, pd.Timestamp("2026-09-14T16:26:28Z"), timestamp_columns=("frozen_at_utc",))
    assert list(out["market_key"]) == ["new"]


def test_filter_since_reset_uses_first_available_timestamp_column():
    frame = pd.DataFrame([
        {"market_key": "old", "official_at_utc": "2026-09-14T16:20:00Z"},
        {"market_key": "new", "official_at_utc": "2026-09-14T16:30:00Z"},
    ])
    out = filter_since_reset(frame, pd.Timestamp("2026-09-14T16:26:28Z"), timestamp_columns=("official_at_utc", "snapshot_utc"))
    assert list(out["market_key"]) == ["new"]
