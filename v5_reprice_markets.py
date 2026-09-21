from __future__ import annotations

import pandas as pd

from v5_live_market import fair_american, signal_row
from v5_production_artifacts import stable_market_key
from v5_recommendation_ledger import update_official_recommendations
from v5_recommendation_policy import select_primary_market_rows


def _decimal_from_american(value):
    try: odds = float(value)
    except Exception: return pd.NA
    if odds > 0: return 1.0 + odds / 100.0
    if odds < 0: return 1.0 + 100.0 / abs(odds)
    return pd.NA


def reprice_market_snapshot(prices, frozen_market_probs, *, prices_fresh):
    if prices is None or prices.empty: return pd.DataFrame()
    out = prices.copy()
    out["market_key"] = [stable_market_key(r.fixture_id, r.market_group, r.selection, getattr(r, "line", None)) for r in out.itertuples(index=False)]
    frozen = pd.DataFrame() if frozen_market_probs is None else frozen_market_probs.copy()
    keep = [c for c in frozen.columns if c not in {"fixture_id", "market_group", "selection", "line"}]
    out = out.merge(frozen[keep], on="market_key", how="left", suffixes=("", "_forecast")) if not frozen.empty else out
    if "best_decimal_odds" not in out.columns:
        out["best_decimal_odds"] = [_decimal_from_american(x) for x in out.get("best_american_odds", pd.Series(index=out.index))]
    else:
        missing = pd.to_numeric(out["best_decimal_odds"], errors="coerce").isna()
        if "best_american_odds" in out.columns:
            out.loc[missing, "best_decimal_odds"] = [_decimal_from_american(x) for x in out.loc[missing, "best_american_odds"]]
    model_p = pd.to_numeric(out.get("model_probability"), errors="coerce")
    win_p = pd.to_numeric(out.get("model_win_probability"), errors="coerce")
    push_p = pd.to_numeric(out.get("model_push_probability"), errors="coerce").fillna(0.0)
    decimal = pd.to_numeric(out.get("best_decimal_odds"), errors="coerce")
    consensus = pd.to_numeric(out.get("consensus_no_vig_prob"), errors="coerce")
    out["model_fair_american"] = [fair_american(p) if pd.notna(p) and 0 < p < 1 else pd.NA for p in model_p]
    out["edge_vs_consensus"] = model_p - consensus
    out["expected_value"] = win_p * decimal + push_p - 1.0
    signals = []
    for _, row in out.iterrows():
        if pd.isna(row.get("model_probability")): signals.append("N/A"); continue
        if not prices_fresh: signals.append("STALE"); continue
        conf = row.get("state_confidence")
        try: conf = float(conf) if pd.notna(conf) else None
        except Exception: conf = None
        sig = signal_row(row, disagreement_level=None, state_confidence=conf)
        if str(row.get("surface_source", "")) == "Auto default — review" and sig in {"BET", "LEAN"}: sig = "REVIEW"
        signals.append(sig)
    out["signal"] = signals
    return out


def update_repricing_artifacts(prices, frozen_market_probs, *, prices_fresh, existing_official=None, existing_audit=None):
    repriced = reprice_market_snapshot(prices, frozen_market_probs, prices_fresh=prices_fresh)
    selected = select_primary_market_rows(repriced)
    actionable = selected
    if not actionable.empty and "signal" in actionable.columns:
        actionable = actionable[actionable["signal"].fillna("").astype(str).str.upper().isin({"BET", "LEAN"})].copy()
    official, audit = update_official_recommendations(existing_official, actionable, existing_audit)
    return repriced, official, audit
