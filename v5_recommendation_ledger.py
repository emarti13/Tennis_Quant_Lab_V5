from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from v5_production_artifacts import stable_market_key


OFFICIAL_COLUMNS = [
    "fixture_id", "market_group", "selection", "line", "market_key",
    "official_signal", "official_price_american", "official_price_decimal",
    "official_model_probability", "official_expected_value", "official_edge",
    "official_at_utc", "start_time_utc", "model_version",
    "selected_model_candidate", "score_model_version", "selected_score_candidate",
    "result_status", "settled_result", "profit_units",
]


def _utc(value):
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _empty_official() -> pd.DataFrame:
    return pd.DataFrame(columns=OFFICIAL_COLUMNS)


def _audit_append(audit: pd.DataFrame | None, row: dict) -> pd.DataFrame:
    base = pd.DataFrame() if audit is None else audit.copy()
    return pd.concat([base, pd.DataFrame([row])], ignore_index=True, sort=False)


def _observation_market_key(row) -> str:
    value = row.get("market_key")
    if value is not None and str(value).strip():
        return str(value).strip()
    return stable_market_key(row.get("fixture_id"), row.get("market_group"), row.get("selection"), row.get("line"))


def _official_record(row, signal: str, market_key: str) -> dict:
    return {
        "fixture_id": row.get("fixture_id"),
        "market_group": row.get("market_group"),
        "selection": row.get("selection"),
        "line": row.get("line"),
        "market_key": market_key,
        "official_signal": signal,
        "official_price_american": row.get("best_american_odds"),
        "official_price_decimal": row.get("best_decimal_odds"),
        "official_model_probability": row.get("model_probability"),
        "official_expected_value": row.get("expected_value"),
        "official_edge": row.get("edge_vs_consensus"),
        "official_at_utc": row.get("snapshot_utc"),
        "start_time_utc": row.get("start_time_utc"),
        "model_version": row.get("model_version"),
        "selected_model_candidate": row.get("selected_model_candidate"),
        "score_model_version": row.get("score_model_version"),
        "selected_score_candidate": row.get("selected_score_candidate"),
        "result_status": "OPEN",
        "settled_result": "",
        "profit_units": pd.NA,
    }


def update_official_recommendations(
    existing: pd.DataFrame | None,
    observations: pd.DataFrame | None,
    audit: pd.DataFrame | None = None,
    *,
    now_utc=None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    ledger = _empty_official() if existing is None or existing.empty else existing.copy()
    audit_out = pd.DataFrame() if audit is None else audit.copy()
    if observations is None or observations.empty:
        return ledger.reset_index(drop=True), audit_out.reset_index(drop=True)

    if "market_key" not in ledger.columns:
        ledger["market_key"] = ledger.apply(
            lambda r: stable_market_key(r.get("fixture_id"), r.get("market_group"), r.get("selection"), r.get("line")),
            axis=1,
        )

    for _, obs in observations.iterrows():
        signal = str(obs.get("signal", "")).upper().strip()
        market_key = _observation_market_key(obs)
        snapshot = obs.get("snapshot_utc")
        start = obs.get("start_time_utc")
        event_base = {
            "market_key": market_key,
            "fixture_id": obs.get("fixture_id"),
            "signal": signal,
            "snapshot_utc": snapshot,
            "best_american_odds": obs.get("best_american_odds"),
            "model_probability": obs.get("model_probability"),
        }

        if snapshot is None:
            snapshot = now_utc or datetime.now(timezone.utc).isoformat()
        try:
            after_start = start is not None and _utc(snapshot) >= _utc(start)
        except Exception:
            after_start = True
        if after_start:
            audit_out = _audit_append(audit_out, {**event_base, "event": "BLOCKED_POST_START"})
            continue

        if signal not in {"BET", "LEAN"}:
            audit_out = _audit_append(audit_out, {**event_base, "event": "NON_ACTIONABLE"})
            continue

        matches = ledger.index[ledger["market_key"].astype(str) == market_key].tolist()
        if not matches:
            record = _official_record(obs, signal, market_key)
            ledger = pd.concat([ledger, pd.DataFrame([record])], ignore_index=True, sort=False)
            audit_out = _audit_append(audit_out, {**event_base, "event": f"OFFICIAL_{signal}_CREATED"})
            continue

        idx = matches[0]
        current_signal = str(ledger.at[idx, "official_signal"]).upper().strip()
        if current_signal == "LEAN" and signal == "BET" and str(ledger.at[idx, "result_status"]).upper() == "OPEN":
            record = _official_record(obs, "BET", market_key)
            for key, value in record.items():
                ledger.at[idx, key] = value
            audit_out = _audit_append(audit_out, {**event_base, "event": "LEAN_SUPERSEDED_BY_BET"})
        else:
            audit_out = _audit_append(audit_out, {**event_base, "event": "DUPLICATE_ACTIONABLE_IGNORED"})

    for col in OFFICIAL_COLUMNS:
        if col not in ledger.columns:
            ledger[col] = pd.NA
    return ledger[OFFICIAL_COLUMNS].reset_index(drop=True), audit_out.reset_index(drop=True)
