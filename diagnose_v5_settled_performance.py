from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd


SETTLED = {"WIN", "LOSS", "PUSH"}


def _clean_settled(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    out = frame.copy()
    out["settled_result"] = out.get("settled_result", "").astype(str).str.upper()
    out = out[out["settled_result"].isin(SETTLED)].copy()
    if "freeze_key" in out.columns:
        out = out.drop_duplicates("freeze_key", keep="last")
    else:
        keys = [c for c in ("fixture_id", "market_group", "selection", "line") if c in out.columns]
        if keys:
            out = out.drop_duplicates(keys, keep="last")
    out["profit_units"] = pd.to_numeric(out.get("profit_units"), errors="coerce").fillna(0.0)
    out["model_probability"] = pd.to_numeric(out.get("model_probability"), errors="coerce")
    out["consensus_no_vig_prob"] = pd.to_numeric(out.get("consensus_no_vig_prob"), errors="coerce")
    return out.reset_index(drop=True)


def _raw_summary(frame: pd.DataFrame) -> dict:
    if frame.empty:
        return {"bets":0,"wins":0,"losses":0,"pushes":0,"win_rate":None,"net_units":0.0,"roi":None}
    wins = int(frame["settled_result"].eq("WIN").sum())
    losses = int(frame["settled_result"].eq("LOSS").sum())
    pushes = int(frame["settled_result"].eq("PUSH").sum())
    decided = wins + losses
    bets = int(len(frame))
    units = float(frame["profit_units"].sum())
    return {
        "bets": bets,
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "win_rate": None if decided == 0 else wins / decided,
        "net_units": units,
        "roi": None if bets == 0 else units / bets,
    }


def _fixture_summary(frame: pd.DataFrame) -> dict:
    if frame.empty or "fixture_id" not in frame.columns:
        return {"fixtures":0,"profitable_fixtures":0,"losing_fixtures":0,"flat_fixtures":0,"profitable_fixture_rate":None,"mean_markets_per_fixture":None,"max_markets_on_one_fixture":0,"net_units":0.0}
    grouped = frame.groupby("fixture_id", dropna=False).agg(markets=("settled_result","size"), net_units=("profit_units","sum")).reset_index()
    profitable = int(grouped["net_units"].gt(0).sum())
    losing = int(grouped["net_units"].lt(0).sum())
    flat = int(grouped["net_units"].eq(0).sum())
    n = int(len(grouped))
    return {
        "fixtures": n,
        "profitable_fixtures": profitable,
        "losing_fixtures": losing,
        "flat_fixtures": flat,
        "profitable_fixture_rate": None if n == 0 else profitable / n,
        "mean_markets_per_fixture": None if n == 0 else float(grouped["markets"].mean()),
        "max_markets_on_one_fixture": 0 if n == 0 else int(grouped["markets"].max()),
        "net_units": float(grouped["net_units"].sum()),
    }


def _group_summaries(frame: pd.DataFrame, column: str) -> dict:
    if frame.empty or column not in frame.columns:
        return {}
    out = {}
    for key, group in frame.groupby(column, dropna=False):
        label = "MISSING" if pd.isna(key) else str(key)
        out[label] = _raw_summary(group)
    return out


def _moneyline_calibration(frame: pd.DataFrame) -> dict:
    if frame.empty or "market_group" not in frame.columns:
        return {"n":0,"mean_model_probability":None,"mean_market_probability":None,"observed_win_rate":None,"brier":None,"log_loss":None,"buckets":{}}
    ml = frame[frame["market_group"].astype(str).str.lower().eq("moneyline")].copy()
    ml = ml[ml["settled_result"].isin({"WIN","LOSS"})]
    ml = ml[ml["model_probability"].notna()].copy()
    if ml.empty:
        return {"n":0,"mean_model_probability":None,"mean_market_probability":None,"observed_win_rate":None,"brier":None,"log_loss":None,"buckets":{}}
    y = ml["settled_result"].eq("WIN").astype(float).to_numpy()
    p = ml["model_probability"].clip(1e-6, 1-1e-6).to_numpy(dtype=float)
    brier = float(np.mean((p-y)**2))
    log_loss = float(-np.mean(y*np.log(p)+(1-y)*np.log(1-p)))
    bins = [0,.1,.2,.3,.4,.5,.6,.7,.8,.9,1.000001]
    labels = ["0-10%","10-20%","20-30%","30-40%","40-50%","50-60%","60-70%","70-80%","80-90%","90-100%"]
    ml["prob_bucket"] = pd.cut(ml["model_probability"], bins=bins, labels=labels, right=False, include_lowest=True)
    buckets = {}
    for label, group in ml.groupby("prob_bucket", observed=True):
        yy = group["settled_result"].eq("WIN").astype(float)
        buckets[str(label)] = {
            "n": int(len(group)),
            "mean_model_probability": float(group["model_probability"].mean()),
            "mean_market_probability": None if group["consensus_no_vig_prob"].isna().all() else float(group["consensus_no_vig_prob"].mean()),
            "observed_win_rate": float(yy.mean()),
            "calibration_error": float(group["model_probability"].mean() - yy.mean()),
        }
    return {
        "n": int(len(ml)),
        "mean_model_probability": float(np.mean(p)),
        "mean_market_probability": None if ml["consensus_no_vig_prob"].isna().all() else float(ml["consensus_no_vig_prob"].mean()),
        "observed_win_rate": float(np.mean(y)),
        "brier": brier,
        "log_loss": log_loss,
        "buckets": buckets,
    }


def settled_performance_report(frame: pd.DataFrame) -> dict:
    settled = _clean_settled(frame)
    signal = settled.get("signal", pd.Series(index=settled.index, dtype=object)).fillna("").astype(str).str.upper()
    actionable = settled[signal.isin(["BET", "LEAN"])].copy()
    report = {
        "settled_rows_after_dedupe": int(len(settled)),
        "raw_markets": _raw_summary(settled),
        "fixture_clusters": _fixture_summary(settled),
        "actionable_markets": _raw_summary(actionable),
        "actionable_fixture_clusters": _fixture_summary(actionable),
        "moneyline_calibration": _moneyline_calibration(settled),
        "by_market_group": _group_summaries(settled, "market_group"),
        "by_signal": _group_summaries(settled, "signal"),
        "by_tour": _group_summaries(settled, "tour_v5" if "tour_v5" in settled.columns else "tour"),
        "by_best_of": _group_summaries(settled, "best_of"),
    }
    return report


def main(base_dir: str | Path = ".") -> int:
    base = Path(base_dir)
    path = base / "v5_daily_ready" / "frozen_predictions.csv"
    out_path = base / "v5_daily_ready" / "settled_performance_audit.json"
    if not path.exists():
        report = {"status":"missing","source":str(path)}
    else:
        try:
            frame = pd.read_csv(path, low_memory=False)
        except pd.errors.EmptyDataError:
            frame = pd.DataFrame()
        report = {"status":"ok","source":str(path), **settled_performance_report(frame)}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(report, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
