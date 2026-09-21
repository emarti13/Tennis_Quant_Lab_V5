from __future__ import annotations

import pandas as pd

from v5_production_artifacts import stable_market_key

OFFICIAL_COLUMNS = [
    "fixture_id", "tournament", "tour", "player1", "player2", "resolved_player1", "resolved_player2",
    "market_group", "selection", "line", "market_key", "official_signal", "signal",
    "official_price_american", "official_price_decimal", "best_american_odds", "best_decimal_odds",
    "official_model_probability", "model_probability", "official_expected_value", "expected_value",
    "official_edge", "edge_vs_consensus", "consensus_no_vig_prob", "official_at_utc", "snapshot_utc",
    "start_time_utc", "model_version", "selected_model_candidate", "score_model_version",
    "selected_score_candidate", "result_status", "settled_result", "profit_units", "settled_at_utc",
    "result_source", "result_tourney_date", "result_tournament", "result_winner", "result_loser",
    "result_score", "winner_games", "loser_games", "settlement_note",
]


def _utc(value):
    ts = pd.Timestamp(value)
    if pd.isna(ts):
        raise ValueError("missing timestamp")
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def _present(value, fallback=None):
    try:
        if value is None or pd.isna(value):
            return fallback
    except (TypeError, ValueError):
        pass
    if isinstance(value, str) and not value.strip():
        return fallback
    return value


def _empty_official():
    return pd.DataFrame(columns=OFFICIAL_COLUMNS)


def _audit_append(audit, row):
    base = pd.DataFrame() if audit is None else audit.copy()
    return pd.concat([base, pd.DataFrame([row])], ignore_index=True, sort=False)


def _observation_market_key(row):
    value = _present(row.get("market_key"))
    return str(value).strip() if value is not None else stable_market_key(row.get("fixture_id"), row.get("market_group"), row.get("selection"), row.get("line"))


def _official_record(row, signal, market_key):
    player1, player2 = row.get("player1"), row.get("player2")
    return {
        "fixture_id": row.get("fixture_id"), "tournament": row.get("tournament"), "tour": row.get("tour"),
        "player1": player1, "player2": player2, "resolved_player1": _present(row.get("resolved_player1"), player1),
        "resolved_player2": _present(row.get("resolved_player2"), player2), "market_group": row.get("market_group"),
        "selection": row.get("selection"), "line": row.get("line"), "market_key": market_key,
        "official_signal": signal, "signal": signal, "official_price_american": row.get("best_american_odds"),
        "official_price_decimal": row.get("best_decimal_odds"), "best_american_odds": row.get("best_american_odds"),
        "best_decimal_odds": row.get("best_decimal_odds"), "official_model_probability": row.get("model_probability"),
        "model_probability": row.get("model_probability"), "official_expected_value": row.get("expected_value"),
        "expected_value": row.get("expected_value"), "official_edge": row.get("edge_vs_consensus"),
        "edge_vs_consensus": row.get("edge_vs_consensus"), "consensus_no_vig_prob": row.get("consensus_no_vig_prob"),
        "official_at_utc": row.get("snapshot_utc"), "snapshot_utc": row.get("snapshot_utc"),
        "start_time_utc": row.get("start_time_utc"), "model_version": row.get("model_version"),
        "selected_model_candidate": row.get("selected_model_candidate"), "score_model_version": row.get("score_model_version"),
        "selected_score_candidate": row.get("selected_score_candidate"), "result_status": "OPEN", "settled_result": "",
        "profit_units": pd.NA, "settled_at_utc": pd.NA, "result_source": pd.NA, "result_tourney_date": pd.NA,
        "result_tournament": pd.NA, "result_winner": pd.NA, "result_loser": pd.NA, "result_score": pd.NA,
        "winner_games": pd.NA, "loser_games": pd.NA, "settlement_note": pd.NA,
    }


def update_official_recommendations(existing, observations, audit=None, *, now_utc=None):
    ledger = _empty_official() if existing is None or existing.empty else existing.copy()
    audit_out = pd.DataFrame() if audit is None else audit.copy()
    for col in OFFICIAL_COLUMNS:
        if col not in ledger.columns:
            ledger[col] = pd.NA
    if observations is None or observations.empty:
        return ledger[OFFICIAL_COLUMNS].reset_index(drop=True), audit_out.reset_index(drop=True)
    if "market_key" not in ledger.columns:
        ledger["market_key"] = ledger.apply(lambda r: stable_market_key(r.get("fixture_id"), r.get("market_group"), r.get("selection"), r.get("line")), axis=1)

    for _, obs in observations.iterrows():
        signal = str(_present(obs.get("signal"), "")).upper().strip()
        if signal not in {"BET", "LEAN"}:
            continue
        market_key = _observation_market_key(obs)
        fixture_id = str(_present(obs.get("fixture_id"), "")).strip()
        snapshot, start = _present(obs.get("snapshot_utc")), _present(obs.get("start_time_utc"))
        event = {"market_key": market_key, "fixture_id": obs.get("fixture_id"), "signal": signal, "snapshot_utc": snapshot,
                 "best_american_odds": obs.get("best_american_odds"), "model_probability": obs.get("model_probability")}
        if not fixture_id:
            audit_out = _audit_append(audit_out, {**event, "event": "BLOCKED_MISSING_FIXTURE"}); continue
        if start is None:
            audit_out = _audit_append(audit_out, {**event, "event": "BLOCKED_MISSING_START"}); continue
        if snapshot is None:
            audit_out = _audit_append(audit_out, {**event, "event": "BLOCKED_MISSING_SNAPSHOT"}); continue
        try:
            if _utc(snapshot) >= _utc(start):
                audit_out = _audit_append(audit_out, {**event, "event": "BLOCKED_POST_START"}); continue
        except Exception:
            audit_out = _audit_append(audit_out, {**event, "event": "BLOCKED_INVALID_TIME"}); continue

        market_group = str(_present(obs.get("market_group"), "")).strip()
        fixture_mask = ledger["fixture_id"].fillna("").astype(str).str.strip().eq(fixture_id)
        group_mask = ledger["market_group"].fillna("").astype(str).str.strip().eq(market_group)
        matches = ledger.index[fixture_mask & group_mask].tolist()
        if not matches:
            ledger = pd.concat([ledger, pd.DataFrame([_official_record(obs, signal, market_key)])], ignore_index=True, sort=False)
            audit_out = _audit_append(audit_out, {**event, "event": f"OFFICIAL_{signal}_CREATED"})
            continue
        idx = matches[0]
        current_signal = str(_present(ledger.at[idx, "official_signal"], "")).upper().strip()
        status = str(_present(ledger.at[idx, "result_status"], "OPEN")).upper().strip()
        if status == "OPEN" and current_signal == "LEAN" and signal == "BET":
            record = _official_record(obs, "BET", market_key)
            for key, value in record.items(): ledger.at[idx, key] = value
            audit_out = _audit_append(audit_out, {**event, "event": "LEAN_SUPERSEDED_BY_BET"})
        else:
            audit_out = _audit_append(audit_out, {**event, "event": "MARKET_FAMILY_ALREADY_OFFICIAL"})

    for col in OFFICIAL_COLUMNS:
        if col not in ledger.columns: ledger[col] = pd.NA
    return ledger[OFFICIAL_COLUMNS].reset_index(drop=True), audit_out.reset_index(drop=True)
