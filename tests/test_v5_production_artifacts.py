import json
from pathlib import Path

import pandas as pd
import pytest

from v5_production_artifacts import (
    artifact_status,
    promote_csv_last_known_good,
    stable_market_key,
    write_status,
)


def test_stable_market_key_normalizes_selection_and_line():
    a = stable_market_key("fx1", "game_spread", " Player, One ", -3.0)
    b = stable_market_key("fx1", "GAME_SPREAD", "player one", "-3")
    assert a == b == "fx1|game_spread|player one|-3"


def test_stable_market_key_uses_blank_line_for_moneyline():
    assert stable_market_key("fx1", "moneyline", "Player One", None) == "fx1|moneyline|player one|"


def test_promote_csv_last_known_good_rejects_invalid_candidate_without_overwriting(tmp_path):
    canonical = tmp_path / "canonical.csv"
    candidate = tmp_path / "candidate.csv"
    pd.DataFrame([{"fixture_id": "old", "value": 1}]).to_csv(canonical, index=False)
    pd.DataFrame(columns=["fixture_id", "value"]).to_csv(candidate, index=False)

    with pytest.raises(ValueError):
        promote_csv_last_known_good(
            candidate,
            canonical,
            required_columns=["fixture_id", "value"],
            require_nonempty=True,
        )

    saved = pd.read_csv(canonical)
    assert saved.to_dict("records") == [{"fixture_id": "old", "value": 1}]


def test_promote_csv_last_known_good_replaces_only_after_validation(tmp_path):
    canonical = tmp_path / "canonical.csv"
    candidate = tmp_path / "candidate.csv"
    pd.DataFrame([{"fixture_id": "old", "value": 1}]).to_csv(canonical, index=False)
    pd.DataFrame([{"fixture_id": "new", "value": 2}]).to_csv(candidate, index=False)

    result = promote_csv_last_known_good(
        candidate,
        canonical,
        required_columns=["fixture_id", "value"],
        require_nonempty=True,
    )

    assert result["rows"] == 1
    assert pd.read_csv(canonical).to_dict("records") == [{"fixture_id": "new", "value": 2}]


def test_status_payload_and_writer_have_stable_schema(tmp_path):
    payload = artifact_status(
        stage="repricing",
        state="success",
        source_version="2026-09-08T12:15:00Z",
        rows=12,
        fixtures=3,
        freshness="READY",
        error=None,
        run_timestamp="2026-09-08T12:16:00Z",
    )
    path = tmp_path / "status.json"
    write_status(path, payload)
    saved = json.loads(path.read_text())

    assert saved == {
        "stage": "repricing",
        "run_timestamp": "2026-09-08T12:16:00Z",
        "source_version": "2026-09-08T12:15:00Z",
        "state": "success",
        "rows": 12,
        "fixtures": 3,
        "freshness": "READY",
        "error": None,
    }
