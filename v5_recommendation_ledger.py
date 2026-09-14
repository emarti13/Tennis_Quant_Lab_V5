from __future__ import annotations

import pandas as pd

from v5_production_artifacts import stable_market_key


OFFICIAL_COLUMNS = [
    "fixture_id", "tournament", "tour", "player1", "player2",
    "resolved_player1", "resolved_player2",
    "market_group", "selection", "line", "market_key",
    "official_signal", "signal",
    "official_price_american", "official_price_decimal",
    "best_american_odds", "best_decimal_odds",
    "official_model_probability", "model_probability",
    "official_expected_value", "expected_value",
    "official_edge", "edge_vs_consensus", "consensus_no_vig_prob",
    "official_at_utc", "snapshot_utc", "start_time_utc",
    "model_version", "selected_model_candidate",
    "score_model_version", "selected_score_candidate",
    "result_status", "settled_result", "profit_units",
    "settled_at_utc", "result_source", "result_tourney_date", "result_tournament",
    "result_winner", "result_loser", "result_score", "winner_games", "loser_games",
    "settlement_note",
]

_SIGNAL_PRIORITY = {"BET": 0, "LEAN": 1}


def _utc(value):
    ts = pd.Timestamp(value)
    if pd.isna(ts):
        raise ValueError("missing timestamp")
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _present(value, fallback=None):
    try:
        if value is None or pd.isna(value):
            return fallback
    except (TypeError, ValueError):
        pass
    if isinstance(value, str) and not value.strip():
        return fallback
    return value


def _empty_official() -> pd.DataFrame:
    return pd.DataFrame(columns=OFFICIAL_COLUMNS)


def _audit_append(audit: pd.DataFrame | None, row: dict) -> pd.DataFrame:
    base = pd.DataFrame() if audit is None else audit.copy()
    return pd.concat([base, pd.DataFrame([row])], ignore_index=True, sort=False)


def _observation_market_key(row) -> str:
    value = _present(row.get("market_key"))
    if value is not None:
        return str(value).strip()
    return stable_market_key(row.get("fixture_id"), row.get("market_group"), row.get("selection"), row.get("line"))


def _official_record(row, signal: str, market_key: str) -> dict:
    price_american = row.get("best_american_odds")
    price_decimal = row.get("best_decimal_odds")
    model_probability = row.get("model_probability")
    expected_value = row.get("expected_value")
    edge = row.get("edge_vs_consensus")
    snapshot = row.get("snapshot_utc")
    player1 = row.get("player1")
    player2 = row.get("player2")
    return {
        "fixture_id": row.get("fixture_id"),
        "tournament": row.get("tournament"),
        "tour": row.get("tour"),
        "player1": player1,
        "player2": player2,
        "resolved_player1": _present(row.get("resolved_player1"), player1),
        "resolved_player2": _present(row.get("resolved_player2"), player2),
        "market_group": row.get("market_group"),
        "selection": row.get("selection"),
        "line": row.get("line"),
        "market_key": market_key,
        "official_signal": signal,
        "signal": signal,
        "official_price_american": price_american,
        "official_price_decimal": price_decimal,
        "best_american_odds": price_american,
        "best_decimal_odds": price_decimal,
        "official_model_probability": model_probability,
        "model_probability": model_probability,
        "official_expected_value": expected_value,
        "expected_value": expected_value,
        "official_edge": edge,
        "edge_vs_consensus": edge,
        "consensus_no_vig_prob": row.get("consensus_no_vig_prob"),
        "official_at_utc": snapshot,
        "snapshot_utc": snapshot,
        "start_time_utc": row.get("start_time_utc"),
        "model_version": row.get("model_version"),
        "selected_model_candidate": row.get("selected_model_candidate"),
        "score_model_version": row.get("score_model_version"),
        "selected_score_candidate": row.get("selected_score_candidate"),
        "result_status": "OPEN",
        "settled_result": "",
        "profit_units": pd.NA,
        "settled_at_utc": pd.NA,
        "result_source": pd.NA,
        "result_tourney_date": pd.NA,
        "result_tournament": pd.NA,
        "result_winner": pd.NA,
        "result_loser": pd.NA,
        "result_score": pd.NA,
        "winner_games": pd.NA,
        "loser_games": pd.NA,
        "settlement_note": pd.NA,
    }


def _normalize_open_fixture_duplicates(ledger: pd.DataFrame) -> pd.DataFrame:
    """Keep at most one OPEN official row per fixture without rewriting settled history."""
    if ledger is None or ledger.empty or "fixture_id" not in ledger.columns:
        return _empty_official() if ledger is None else ledger.copy()

    work = ledger.copy()
    for col in OFFICIAL_COLUMNS:
        if col not in work.columns:
            work[col] = pd.NA
    work["_source_order"] = range(len(work))
    status = work["result_status"].fillna("OPEN").astype(str).str.upper().str.strip()
    settled = work.loc[status.ne("OPEN")].copy()
    open_rows = work.loc[status.eq("OPEN")].copy()
    if open_rows.empty:
        return work.drop(columns=["_source_order"])[OFFICIAL_COLUMNS].reset_index(drop=True)

    settled_fixtures = set(settled["fixture_id"].dropna().astype(str))
    if settled_fixtures:
        open_rows = open_rows.loc[~open_rows["fixture_id"].astype(str).isin(settled_fixtures)].copy()

    signal = open_rows["official_signal"].fillna(open_rows["signal"]).astype(str).str.upper().str.strip()
    open_rows["_signal_rank"] = signal.map(lambda value: _SIGNAL_PRIORITY.get(value, 9))
    ev = pd.to_numeric(open_rows["official_expected_value"], errors="coerce")
    fallback_ev = pd.to_numeric(open_rows["expected_value"], errors="coerce")
    open_rows["_ev_rank"] = ev.fillna(fallback_ev).fillna(float("-inf"))
    open_rows = open_rows.sort_values(
        ["fixture_id", "_signal_rank", "_ev_rank", "_source_order"],
        ascending=[True, True, False, True],
        kind="stable",
    ).drop_duplicates("fixture_id", keep="first")

    combined = pd.concat([settled, open_rows], ignore_index=True, sort=False)
    combined = combined.sort_values("_source_order", kind="stable")
    return combined.drop(columns=["_source_order", "_signal_rank", "_ev_rank"], errors="ignore")[OFFICIAL_COLUMNS].reset_index(drop=True)


def update_official_recommendations(
    existing: pd.DataFrame | None,
    observations: pd.DataFrame | None,
    audit: pd.DataFrame | None = None,
    *,
    now_utc=None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    ledger = _empty_official() if existing is None or existing.empty else existing.copy()
    ledger = _normalize_open_fixture_duplicates(ledger)
    audit_out = pd.DataFrame() if audit is None else audit.copy()
    if observations is None or observations.empty:
        for col in OFFICIAL_COLUMNS:
            if col not in ledger.columns:
                ledger[col] = pd.NA
        return ledger[OFFICIAL_COLUMNS].reset_index(drop=True), audit_out.reset_index(drop=True)

    if "market_key" not in ledger.columns:
        ledger["market_key"] = ledger.apply(
            lambda r: stable_market_key(r.get("fixture_id"), r.get("market_group"), r.get("selection"), r.get("line")),
            axis=1,
        )

    for _, obs in observations.iterrows():
        signal = str(_present(obs.get("signal"), "")).upper().strip()
        market_key = _observation_market_key(obs)
        fixture_value = _present(obs.get("fixture_id"))
        fixture_id = "" if fixture_value is None else str(fixture_value).strip()
        snapshot = _present(obs.get("snapshot_utc"))
        start = _present(obs.get("start_time_utc"))
        event_base = {
            "market_key": market_key,
            "fixture_id": obs.get("fixture_id"),
            "signal": signal,
            "snapshot_utc": snapshot,
            "best_american_odds": obs.get("best_american_odds"),
            "model_probability": obs.get("model_probability"),
        }

        if signal not in {"BET", "LEAN"}:
            continue
        if not fixture_id:
            audit_out = _audit_append(audit_out, {**event_base, "event": "BLOCKED_MISSING_FIXTURE"})
            continue
        if start is None:
            audit_out = _audit_append(audit_out, {**event_base, "event": "BLOCKED_MISSING_START"})
            continue
        if snapshot is None:
            audit_out = _audit_append(audit_out, {**event_base, "event": "BLOCKED_MISSING_SNAPSHOT"})
            continue

        try:
            after_start = _utc(snapshot) >= _utc(start)
        except Exception:
            audit_out = _audit_append(audit_out, {**event_base, "event": "BLOCKED_INVALID_TIME"})
            continue
        if after_start:
            audit_out = _audit_append(audit_out, {**event_base, "event": "BLOCKED_POST_START"})
            continue

        matches = ledger.index[ledger["fixture_id"].astype(str) == fixture_id].tolist()
        if not matches:
            record = _official_record(obs, signal, market_key)
            ledger = pd.concat([ledger, pd.DataFrame([record])], ignore_index=True, sort=False)
            audit_out = _audit_append(audit_out, {**event_base, "event": f"OFFICIAL_{signal}_CREATED"})
            continue

        open_matches = []
        for idx in matches:
            status = str(_present(ledger.at[idx, "result_status"], "OPEN")).upper().strip()
            if status == "OPEN":
                open_matches.append(idx)
        if not open_matches:
            audit_out = _audit_append(audit_out, {**event_base, "event": "DUPLICATE_ACTIONABLE_IGNORED"})
            continue

        idx = open_matches[0]
        current_signal = str(_present(ledger.at[idx, "official_signal"], "")).upper().strip()
        if current_signal == "LEAN" and signal == "BET":
            record = _official_record(obs, "BET", market_key)
            for key, value in record.items():
                ledger.at[idx, key] = value
            audit_out = _audit_append(audit_out, {**event_base, "event": "LEAN_SUPERSEDED_BY_BET"})
        else:
            audit_out = _audit_append(audit_out, {**event_base, "event": "DUPLICATE_ACTIONABLE_IGNORED"})

    ledger = _normalize_open_fixture_duplicates(ledger)
    for col in OFFICIAL_COLUMNS:
        if col not in ledger.columns:
            ledger[col] = pd.NA
    return ledger[OFFICIAL_COLUMNS].reset_index(drop=True), audit_out.reset_index(drop=True)
