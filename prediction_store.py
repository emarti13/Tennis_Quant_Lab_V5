
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

SCHEMA = """
CREATE TABLE IF NOT EXISTS predictions (
    prediction_id TEXT PRIMARY KEY,
    created_at_utc TEXT NOT NULL,
    model_version TEXT NOT NULL,
    fixture_id TEXT,
    source_fixture_id TEXT,
    tour TEXT,
    tournament TEXT,
    surface TEXT,
    start_time_utc TEXT,
    player1 TEXT NOT NULL,
    player2 TEXT NOT NULL,
    market_type TEXT NOT NULL,
    selection TEXT NOT NULL,
    line REAL,
    model_probability REAL NOT NULL,
    model_fair_odds INTEGER,
    bookmaker TEXT,
    book_odds INTEGER,
    book_implied_probability REAL,
    no_vig_probability REAL,
    probability_edge REAL,
    expected_roi REAL,
    agreement TEXT,
    state_confidence REAL,
    signal TEXT,
    odds_snapshot_utc TEXT,
    result_status TEXT DEFAULT 'OPEN',
    settled_result TEXT,
    profit_units REAL,
    closing_odds INTEGER,
    closing_implied_probability REAL,
    clv_probability REAL,
    metadata_json TEXT
);

CREATE INDEX IF NOT EXISTS ix_predictions_fixture
ON predictions(fixture_id);

CREATE INDEX IF NOT EXISTS ix_predictions_created
ON predictions(created_at_utc);

CREATE INDEX IF NOT EXISTS ix_predictions_signal
ON predictions(signal);

CREATE TABLE IF NOT EXISTS market_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    captured_at_utc TEXT NOT NULL,
    source TEXT NOT NULL,
    fixture_id TEXT,
    bookmaker TEXT,
    market_type TEXT,
    selection TEXT,
    line REAL,
    odds_american INTEGER,
    odds_decimal REAL,
    payload_json TEXT
);
"""


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class PredictionStore:
    def __init__(self, db_path="v5_predictions.sqlite3"):
        self.db_path = Path(db_path)
        self._init()

    def _connect(self):
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        return con

    def _init(self):
        with self._connect() as con:
            con.executescript(SCHEMA)

    def log_prediction(self, **row):
        defaults = {
            "prediction_id": str(uuid.uuid4()),
            "created_at_utc": utc_now(),
            "model_version": "V5",
            "metadata_json": "{}",
        }
        data = {**defaults, **row}
        if not isinstance(data.get("metadata_json"), str):
            data["metadata_json"] = json.dumps(data["metadata_json"], default=str)

        cols = list(data.keys())
        marks = ",".join("?" for _ in cols)
        sql = f"INSERT INTO predictions ({','.join(cols)}) VALUES ({marks})"

        with self._connect() as con:
            con.execute(sql, [data[c] for c in cols])

        return data["prediction_id"]

    def log_snapshot(self, **row):
        data = {
            "snapshot_id": str(uuid.uuid4()),
            "captured_at_utc": utc_now(),
            **row,
        }
        if not isinstance(data.get("payload_json"), str):
            data["payload_json"] = json.dumps(data.get("payload_json"), default=str)

        cols = list(data.keys())
        marks = ",".join("?" for _ in cols)
        sql = f"INSERT INTO market_snapshots ({','.join(cols)}) VALUES ({marks})"

        with self._connect() as con:
            con.execute(sql, [data[c] for c in cols])

        return data["snapshot_id"]

    def predictions_df(self):
        with self._connect() as con:
            return pd.read_sql_query(
                "SELECT * FROM predictions ORDER BY created_at_utc DESC",
                con,
            )

    def open_predictions(self):
        with self._connect() as con:
            return pd.read_sql_query(
                "SELECT * FROM predictions WHERE result_status='OPEN' "
                "ORDER BY start_time_utc",
                con,
            )

    def settle(
        self,
        prediction_id,
        won: bool,
        push: bool = False,
        closing_odds=None,
        closing_implied_probability=None,
    ):
        with self._connect() as con:
            row = con.execute(
                "SELECT book_odds, model_probability FROM predictions "
                "WHERE prediction_id=?",
                (prediction_id,),
            ).fetchone()

            if row is None:
                raise KeyError(prediction_id)

            if push:
                profit = 0.0
                settled = "PUSH"
            elif won:
                odds = row["book_odds"]
                if odds is None:
                    profit = None
                elif odds > 0:
                    profit = odds / 100.0
                else:
                    profit = 100.0 / abs(odds)
                settled = "WIN"
            else:
                profit = -1.0
                settled = "LOSS"

            clv = None
            if closing_implied_probability is not None:
                clv = (
                    float(row["model_probability"])
                    - float(closing_implied_probability)
                )

            con.execute(
                """
                UPDATE predictions
                SET result_status='SETTLED',
                    settled_result=?,
                    profit_units=?,
                    closing_odds=?,
                    closing_implied_probability=?,
                    clv_probability=?
                WHERE prediction_id=?
                """,
                (
                    settled,
                    profit,
                    closing_odds,
                    closing_implied_probability,
                    clv,
                    prediction_id,
                ),
            )
