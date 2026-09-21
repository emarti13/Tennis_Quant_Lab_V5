from __future__ import annotations

import pandas as pd


_SIGNAL_PRIORITY = {
    "BET": 0,
    "LEAN": 1,
    "REVIEW": 2,
    "PASS": 3,
    "N/A": 4,
    "NO PRICE": 5,
    "STALE": 6,
    "": 7,
}


def select_primary_market_rows(observations: pd.DataFrame | None) -> pd.DataFrame:
    """Return one deterministic primary row per fixture and market family.

    Selection mirrors the Decision Feed contract: strongest signal tier first,
    then highest expected value inside that tier, then original source order.
    Rows without a fixture id are excluded because they cannot form an official
    fixture-level market-family decision.
    """
    if observations is None or observations.empty:
        return pd.DataFrame(columns=list(observations.columns) if observations is not None else [])
    if "fixture_id" not in observations.columns:
        return observations.iloc[0:0].copy()

    work = observations.copy()
    work["_source_order"] = range(len(work))
    fixture = work["fixture_id"].fillna("").astype(str).str.strip()
    work = work.loc[fixture.ne("")].copy()
    if work.empty:
        return observations.iloc[0:0].copy()

    signal = work.get("signal", pd.Series(index=work.index, dtype=object)).fillna("").astype(str).str.upper().str.strip()
    work["_signal_rank"] = signal.map(lambda value: _SIGNAL_PRIORITY.get(value, 9))
    work["_ev_rank"] = pd.to_numeric(work.get("expected_value"), errors="coerce").fillna(float("-inf"))

    ranked = work.sort_values(
        ["fixture_id", "market_group", "_signal_rank", "_ev_rank", "_source_order"],
        ascending=[True, True, True, False, True],
        kind="stable",
    )
    selected = ranked.drop_duplicates(["fixture_id", "market_group"], keep="first")
    selected = selected.sort_values("_source_order", kind="stable")
    return selected.drop(columns=["_source_order", "_signal_rank", "_ev_rank"]).reset_index(drop=True)
