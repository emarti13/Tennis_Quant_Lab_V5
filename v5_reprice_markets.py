from __future__ import annotations

import pandas as pd

from v5_devig import book_lam, devig
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


# Model guard (rebuild plan Step 4; user decision 2026-10-18): a model price more than 15
# points from the market's fair price is labelled REVIEW, never BET or LEAN. Measured on 2026
# matches before the sealed period: above that gap the market was right and the model wrong
# (docs/experiments/2026-10-18-market-gap-guard.md).
MARKET_GAP_LIMIT = 0.15
REFERENCE_BOOK = "pinnacle"


def market_reference(book_prices: pd.DataFrame) -> pd.DataFrame:
    """market_key -> the reference book's fair probability (both sides de-vigged with its
    measured lam). Pinnacle is information (CLAUDE.md), which is what a guard needs."""
    cols = ["market_key", "reference_probability", "reference_source"]
    if book_prices is None or book_prices.empty or "bookmaker" not in book_prices.columns:
        return pd.DataFrame(columns=cols)
    ref = book_prices[(book_prices["bookmaker"].astype(str).str.lower() == REFERENCE_BOOK)
                      & (book_prices["market_group"] == "moneyline")]
    rows = []
    for _, g in ref.groupby("fixture_id"):
        g = g.drop_duplicates("selection", keep="last")
        odds = pd.to_numeric(g["decimal_odds"], errors="coerce")
        if len(g) != 2 or odds.isna().any() or (odds <= 1).any():
            continue
        try:
            fair = devig(list(odds), book_lam(REFERENCE_BOOK))
        except ValueError:
            continue
        for r, q in zip(g.itertuples(index=False), fair):
            rows.append({"market_key": stable_market_key(r.fixture_id, r.market_group, r.selection, None),
                         "reference_probability": q, "reference_source": REFERENCE_BOOK})
    return pd.DataFrame(rows, columns=cols)


def apply_market_gap_guard(repriced: pd.DataFrame, reference: pd.DataFrame | None = None) -> pd.DataFrame:
    """Adds market_reference_probability, its source, model_market_gap and guard_reason; a gap
    above MARKET_GAP_LIMIT turns the signal into REVIEW. The reference is the reference book's
    fair price, else the feed's consensus fair price (no reference: no gap, no flag)."""
    out = repriced.copy()
    if out.empty:
        return out
    empty = pd.DataFrame(columns=["market_key", "reference_probability", "reference_source"])
    ref = (reference if reference is not None and len(reference) else empty).drop_duplicates("market_key")
    out = out.drop(columns=[c for c in ("reference_probability", "reference_source") if c in out.columns])
    out = out.merge(ref, on="market_key", how="left")
    consensus = pd.to_numeric(out.get("consensus_no_vig_prob", pd.Series(index=out.index, dtype=float)), errors="coerce")
    has_ref = out["reference_probability"].notna()
    out["market_reference_probability"] = out["reference_probability"].where(has_ref, consensus)
    out["market_reference_source"] = out["reference_source"].where(has_ref, pd.Series("consensus", index=out.index).where(consensus.notna(), ""))
    out = out.drop(columns=["reference_probability", "reference_source"])
    gap = (pd.to_numeric(out["model_probability"], errors="coerce") - out["market_reference_probability"]).abs()
    out["model_market_gap"] = gap
    flagged = gap > MARKET_GAP_LIMIT
    out["guard_reason"] = flagged.map({True: "MODEL_MARKET_GAP", False: ""})
    # STALE and N/A stay: the guard only stops a price from being acted on.
    out.loc[flagged & out["signal"].isin(["BET", "LEAN", "PASS", "REVIEW"]), "signal"] = "REVIEW"
    return out


def reprice_market_snapshot(prices, frozen_market_probs, *, prices_fresh, reference=None):
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
    consensus = pd.to_numeric(out.get("consensus_no_vig_prob", pd.Series(index=out.index, dtype=float)), errors="coerce")
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
        signals.append(sig)
    out["signal"] = signals
    return apply_market_gap_guard(out, reference)


def update_repricing_artifacts(prices, frozen_market_probs, *, prices_fresh, existing_official=None, existing_audit=None,
                               official_enabled=True, reference=None):
    repriced = reprice_market_snapshot(prices, frozen_market_probs, prices_fresh=prices_fresh, reference=reference)
    if not official_enabled:
        # Paused (production_switches.json): the ledger and its audit are returned unchanged.
        official = existing_official.copy() if existing_official is not None else pd.DataFrame()
        audit = existing_audit.copy() if existing_audit is not None else pd.DataFrame()
        return repriced, official, audit
    selected = select_primary_market_rows(repriced)
    actionable = selected
    if not actionable.empty and "signal" in actionable.columns:
        actionable = actionable[actionable["signal"].fillna("").astype(str).str.upper().isin({"BET", "LEAN"})].copy()
    official, audit = update_official_recommendations(existing_official, actionable, existing_audit)
    return repriced, official, audit
