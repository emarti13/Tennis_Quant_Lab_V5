from __future__ import annotations

import numpy as np
import pandas as pd


DECIDED = {"WIN", "LOSS", "PUSH"}


def _price_band(odds):
    try:
        value = float(odds)
    except Exception:
        return "MISSING"
    if value <= -200:
        return "<=-200"
    if value < -120:
        return "-199 to -121"
    if value <= 120:
        return "-120 to +120"
    if value <= 200:
        return "+121 to +200"
    return ">+200"


def _clean(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    out = frame.copy()
    if "market_key" in out.columns:
        out = out.drop_duplicates("market_key", keep="last")
    out["settled_result"] = out.get("settled_result", "").fillna("").astype(str).str.upper()
    out["profit_units"] = pd.to_numeric(out.get("profit_units"), errors="coerce").fillna(0.0)
    out["official_price_american"] = pd.to_numeric(
        out.get("official_price_american", out.get("best_american_odds")), errors="coerce"
    )
    return out


def _summary(frame: pd.DataFrame) -> dict:
    if frame.empty:
        return {
            "official_recommendations": 0,
            "unique_fixtures": 0,
            "wins": 0,
            "losses": 0,
            "pushes": 0,
            "voids": 0,
            "win_rate": None,
            "net_units": 0.0,
            "roi": None,
            "median_american_odds": None,
            "favorite_recommendations": 0,
            "underdog_recommendations": 0,
            "max_recommendations_per_fixture": 0,
        }
    wins = int(frame["settled_result"].eq("WIN").sum())
    losses = int(frame["settled_result"].eq("LOSS").sum())
    pushes = int(frame["settled_result"].eq("PUSH").sum())
    voids = int(frame["settled_result"].eq("VOID").sum())
    decided = wins + losses
    n = int(len(frame))
    units = float(frame["profit_units"].sum())
    odds = frame["official_price_american"]
    by_fixture = frame.groupby("fixture_id", dropna=False).size() if "fixture_id" in frame.columns else pd.Series(dtype=int)
    return {
        "official_recommendations": n,
        "unique_fixtures": int(frame["fixture_id"].astype(str).nunique()) if "fixture_id" in frame.columns else 0,
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "voids": voids,
        "win_rate": None if decided == 0 else wins / decided,
        "net_units": units,
        "roi": None if n == 0 else units / n,
        "median_american_odds": None if odds.dropna().empty else float(odds.median()),
        "favorite_recommendations": int(odds.lt(0).sum()),
        "underdog_recommendations": int(odds.gt(0).sum()),
        "max_recommendations_per_fixture": 0 if by_fixture.empty else int(by_fixture.max()),
    }


def official_performance_report(frame: pd.DataFrame) -> dict:
    cleaned = _clean(frame)
    settled = cleaned[cleaned["settled_result"].isin({"WIN", "LOSS", "PUSH", "VOID"})].copy() if not cleaned.empty else cleaned
    report = _summary(settled)
    report["open_recommendations"] = int(cleaned["settled_result"].eq("").sum()) if not cleaned.empty else 0
    report["by_signal"] = {}
    if not settled.empty and "official_signal" in settled.columns:
        for signal, group in settled.groupby(settled["official_signal"].fillna("MISSING").astype(str).str.upper()):
            report["by_signal"][str(signal)] = _summary(group)
    report["by_price_band"] = {}
    if not settled.empty:
        settled = settled.copy()
        settled["price_band"] = settled["official_price_american"].map(_price_band)
        for band, group in settled.groupby("price_band", dropna=False):
            report["by_price_band"][str(band)] = _summary(group)
    report["fixture_cluster"] = {
        "fixtures": 0,
        "profitable_fixtures": 0,
        "losing_fixtures": 0,
        "flat_fixtures": 0,
        "profitable_fixture_rate": None,
        "net_units": 0.0,
    }
    if not settled.empty and "fixture_id" in settled.columns:
        grouped = settled.groupby("fixture_id", dropna=False)["profit_units"].sum()
        n = int(len(grouped))
        profitable = int(grouped.gt(0).sum())
        report["fixture_cluster"] = {
            "fixtures": n,
            "profitable_fixtures": profitable,
            "losing_fixtures": int(grouped.lt(0).sum()),
            "flat_fixtures": int(grouped.eq(0).sum()),
            "profitable_fixture_rate": None if n == 0 else profitable / n,
            "net_units": float(grouped.sum()),
        }
    # VOID rows capture retirements/defaults when settlement metadata identifies them.
    non_void = settled[~settled["settled_result"].eq("VOID")].copy() if not settled.empty else settled
    report["retirement_sensitivity"] = {
        "including_voids": _summary(settled),
        "excluding_voids": _summary(non_void),
    }
    return report
