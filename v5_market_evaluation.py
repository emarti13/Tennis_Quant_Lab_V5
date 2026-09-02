from __future__ import annotations

import math

import numpy as np
import pandas as pd


def _canon(value) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _line_token(value) -> str:
    try:
        x = float(value)
        return "" if not math.isfinite(x) else f"{x:g}"
    except Exception:
        return ""


def _join_key(frame: pd.DataFrame) -> pd.Series:
    fixture = frame.get("fixture_id", pd.Series("", index=frame.index)).astype(str)
    group = frame.get("market_group", pd.Series("", index=frame.index)).astype(str).str.lower()
    selection = frame.get("selection", pd.Series("", index=frame.index)).map(_canon)
    line = frame.get("line", pd.Series(np.nan, index=frame.index)).map(_line_token)
    return fixture + "|" + group + "|" + selection + "|" + line


def _profit(row: pd.Series) -> float:
    supplied = pd.to_numeric(pd.Series([row.get("profit_units")]), errors="coerce").iloc[0]
    if pd.notna(supplied):
        return float(supplied)
    result = str(row.get("settled_result") or "").upper()
    decimal = pd.to_numeric(pd.Series([row.get("best_decimal_odds")]), errors="coerce").iloc[0]
    if result == "WIN" and pd.notna(decimal):
        return float(decimal - 1.0)
    if result == "LOSS":
        return -1.0
    if result in {"PUSH", "VOID"}:
        return 0.0
    return float("nan")


def evaluate_market_edges(frozen_model_rows: pd.DataFrame, historical_odds: pd.DataFrame) -> dict:
    """Join prices only after model output is frozen; never mutate model probabilities."""
    model = frozen_model_rows.copy()
    odds = historical_odds.copy()
    if model.empty or odds.empty:
        return {"joined_rows": 0, "rejected_pre_freeze_odds": 0, "edge_mean": None, "expected_value_mean": None, "roi": None, "units": 0.0}

    model["_key"] = _join_key(model)
    odds["_key"] = _join_key(odds)
    model["_freeze"] = pd.to_datetime(model["frozen_at_utc"], errors="coerce", utc=True)
    odds["_snapshot"] = pd.to_datetime(odds["snapshot_utc"], errors="coerce", utc=True)

    rejected = 0
    joined = []
    by_key = {key: group.sort_values("_snapshot", kind="stable") for key, group in odds.groupby("_key", sort=False)}
    for _, row in model.iterrows():
        key = row["_key"]
        candidates = by_key.get(key)
        if candidates is None or candidates.empty or pd.isna(row["_freeze"]):
            continue
        rejected += int((candidates["_snapshot"] < row["_freeze"]).sum())
        post = candidates[candidates["_snapshot"] >= row["_freeze"]]
        if post.empty:
            continue
        price = post.iloc[0]
        merged = {**row.to_dict(), **{k: v for k, v in price.to_dict().items() if k not in row.index}}
        # Explicitly take market fields from the selected post-freeze snapshot.
        for field in ("consensus_no_vig_prob", "best_decimal_odds", "best_american_odds", "bookmaker", "snapshot_utc"):
            if field in price.index:
                merged[field] = price[field]
        joined.append(merged)

    if not joined:
        return {"joined_rows": 0, "rejected_pre_freeze_odds": int(rejected), "edge_mean": None, "expected_value_mean": None, "roi": None, "units": 0.0}

    df = pd.DataFrame(joined)
    p = pd.to_numeric(df["model_probability"], errors="coerce")
    q = pd.to_numeric(df["consensus_no_vig_prob"], errors="coerce")
    dec = pd.to_numeric(df["best_decimal_odds"], errors="coerce")
    df["edge"] = p - q
    df["expected_value"] = p * dec - 1.0
    df["_profit"] = df.apply(_profit, axis=1)
    settled = df["_profit"].notna()
    units = float(df.loc[settled, "_profit"].sum()) if settled.any() else 0.0
    roi = float(units / settled.sum()) if settled.any() else None

    by_market = {}
    if "market_group" in df.columns:
        for market, group in df.groupby("market_group", dropna=False):
            profits = group["_profit"].dropna()
            by_market[str(market)] = {
                "n": int(len(group)),
                "edge_mean": float(pd.to_numeric(group["edge"], errors="coerce").mean()),
                "units": float(profits.sum()) if len(profits) else 0.0,
                "roi": float(profits.mean()) if len(profits) else None,
            }

    return {
        "joined_rows": int(len(df)),
        "rejected_pre_freeze_odds": int(rejected),
        "edge_mean": float(df["edge"].mean()),
        "expected_value_mean": float(df["expected_value"].mean()),
        "units": units,
        "roi": roi,
        "by_market": by_market,
    }
