from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


THRESHOLDS = (0.00, 0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60)
CURRENT_THRESHOLD = 0.45
SETTLED_RESULTS = {"WIN", "LOSS", "PUSH"}


def _as_float(value):
    try:
        if pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _truthy(value, default=True) -> bool:
    if value is None or pd.isna(value):
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {"false", "0", "no", "off"}


def pricing_signal_without_confidence(row) -> str:
    """Replay production pricing rules while deliberately omitting only confidence."""
    ev = _as_float(row.get("expected_value"))
    edge = _as_float(row.get("edge_vs_consensus"))
    if ev is None or edge is None:
        return "N/A"
    if ev >= 0.05 and edge >= 0.025:
        signal = "BET"
    elif ev >= 0.02 and edge >= 0.01:
        signal = "LEAN"
    else:
        signal = "PASS"

    if signal in {"BET", "LEAN"}:
        if str(row.get("surface_source", "")).strip() == "Auto default — review":
            return "REVIEW"
        if not _truthy(row.get("production_market_enabled"), default=True):
            return "REVIEW"
    return signal


def replay_signal(row, threshold: float) -> str:
    base = pricing_signal_without_confidence(row)
    if base not in {"BET", "LEAN"}:
        return base
    conf = _as_float(row.get("state_confidence"))
    if conf is not None and conf < float(threshold):
        return "REVIEW"
    return base


def _clean_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    out = frame.copy()
    result = out.get("settled_result", pd.Series(index=out.index, dtype=object)).fillna("").astype(str).str.upper()
    status = out.get("result_status", pd.Series(index=out.index, dtype=object)).fillna("").astype(str).str.upper()
    mask = result.isin(SETTLED_RESULTS)
    if status.ne("").any():
        mask &= status.eq("SETTLED")
    out = out[mask].copy()
    if "freeze_key" in out.columns:
        out = out.drop_duplicates("freeze_key", keep="last")
    else:
        keys = [c for c in ("fixture_id", "market_group", "selection", "line") if c in out.columns]
        if keys:
            out = out.drop_duplicates(keys, keep="last")
    for col in (
        "expected_value", "edge_vs_consensus", "state_confidence", "profit_units",
        "model_probability", "consensus_no_vig_prob", "best_american_odds",
    ):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    time_col = "start_time_utc" if "start_time_utc" in out.columns else "settled_at_utc"
    out["_analysis_time"] = pd.to_datetime(out.get(time_col), errors="coerce", utc=True)
    out["settled_result"] = result.loc[out.index]
    out["profit_units"] = pd.to_numeric(out.get("profit_units"), errors="coerce").fillna(0.0)
    return out.reset_index(drop=True)


def select_fixture_actions(frame: pd.DataFrame, threshold: float) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame(columns=list(frame.columns) if frame is not None else [])
    out = frame.copy()
    out["replayed_signal"] = [replay_signal(row, threshold) for _, row in out.iterrows()]
    out = out[out["replayed_signal"].isin({"BET", "LEAN"})].copy()
    if out.empty:
        return out
    out["_signal_rank"] = out["replayed_signal"].map({"BET": 0, "LEAN": 1}).fillna(2)
    out["_ev_rank"] = pd.to_numeric(out.get("expected_value"), errors="coerce").fillna(-np.inf)
    out["_edge_rank"] = pd.to_numeric(out.get("edge_vs_consensus"), errors="coerce").fillna(-np.inf)
    sort_cols = [c for c in ("fixture_id", "_signal_rank", "_ev_rank", "_edge_rank") if c in out.columns]
    ascending = [True, True, False, False][: len(sort_cols)]
    out = out.sort_values(sort_cols, ascending=ascending, kind="stable")
    if "fixture_id" in out.columns:
        out = out.drop_duplicates("fixture_id", keep="first")
    return out.drop(columns=["_signal_rank", "_ev_rank", "_edge_rank"], errors="ignore").reset_index(drop=True)


def _max_drawdown(values: Iterable[float]) -> float:
    vals = np.asarray(list(values), dtype=float)
    if len(vals) == 0:
        return 0.0
    equity = np.cumsum(vals)
    peaks = np.maximum.accumulate(np.r_[0.0, equity])
    drawdowns = peaks[1:] - equity
    return float(np.max(drawdowns)) if len(drawdowns) else 0.0


def policy_metrics(actions: pd.DataFrame, universe_fixtures: int | None = None) -> dict:
    if actions is None or actions.empty:
        return {
            "bets": 0, "wins": 0, "losses": 0, "pushes": 0, "win_rate": None,
            "net_units": 0.0, "roi": None, "units_per_fixture": 0.0 if universe_fixtures else None,
            "max_drawdown_units": 0.0, "avg_expected_value": None, "avg_edge": None,
            "avg_state_confidence": None,
        }
    out = actions.sort_values("_analysis_time", kind="stable") if "_analysis_time" in actions.columns else actions.copy()
    result = out["settled_result"].astype(str).str.upper()
    wins = int(result.eq("WIN").sum())
    losses = int(result.eq("LOSS").sum())
    pushes = int(result.eq("PUSH").sum())
    bets = int(len(out))
    units = float(pd.to_numeric(out["profit_units"], errors="coerce").fillna(0.0).sum())
    decided = wins + losses
    return {
        "bets": bets,
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "win_rate": None if decided == 0 else wins / decided,
        "net_units": units,
        "roi": None if bets == 0 else units / bets,
        "units_per_fixture": None if not universe_fixtures else units / int(universe_fixtures),
        "max_drawdown_units": _max_drawdown(pd.to_numeric(out["profit_units"], errors="coerce").fillna(0.0)),
        "avg_expected_value": None if "expected_value" not in out else float(pd.to_numeric(out["expected_value"], errors="coerce").mean()),
        "avg_edge": None if "edge_vs_consensus" not in out else float(pd.to_numeric(out["edge_vs_consensus"], errors="coerce").mean()),
        "avg_state_confidence": None if "state_confidence" not in out else float(pd.to_numeric(out["state_confidence"], errors="coerce").mean()),
    }


def _roi_bootstrap_ci(actions: pd.DataFrame, n_boot: int = 2000, seed: int = 20260914) -> list[float | None]:
    if actions is None or len(actions) < 10:
        return [None, None]
    units = pd.to_numeric(actions["profit_units"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
    rng = np.random.default_rng(seed)
    samples = rng.choice(units, size=(n_boot, len(units)), replace=True).mean(axis=1)
    lo, hi = np.quantile(samples, [0.025, 0.975])
    return [float(lo), float(hi)]


def _paired_delta_ci(frame: pd.DataFrame, candidate: float, baseline: float = CURRENT_THRESHOLD, n_boot: int = 3000, seed: int = 20260914) -> dict:
    if frame is None or frame.empty or "fixture_id" not in frame.columns:
        return {"delta_units_per_fixture": None, "ci95": [None, None], "fixtures": 0}
    a = select_fixture_actions(frame, candidate)
    b = select_fixture_actions(frame, baseline)
    fixtures = pd.Index(frame["fixture_id"].dropna().astype(str).unique())
    if len(fixtures) < 10:
        return {"delta_units_per_fixture": None, "ci95": [None, None], "fixtures": int(len(fixtures))}
    amap = a.assign(_fid=a["fixture_id"].astype(str)).set_index("_fid")["profit_units"].to_dict() if not a.empty else {}
    bmap = b.assign(_fid=b["fixture_id"].astype(str)).set_index("_fid")["profit_units"].to_dict() if not b.empty else {}
    delta = np.array([float(amap.get(fid, 0.0)) - float(bmap.get(fid, 0.0)) for fid in fixtures], dtype=float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(delta), size=(n_boot, len(delta)))
    boot = delta[idx].mean(axis=1)
    lo, hi = np.quantile(boot, [0.025, 0.975])
    return {
        "delta_units_per_fixture": float(delta.mean()),
        "ci95": [float(lo), float(hi)],
        "fixtures": int(len(delta)),
    }


def threshold_table(frame: pd.DataFrame, thresholds=THRESHOLDS) -> list[dict]:
    universe = int(frame["fixture_id"].nunique()) if frame is not None and not frame.empty and "fixture_id" in frame.columns else 0
    rows = []
    for threshold in thresholds:
        actions = select_fixture_actions(frame, threshold)
        metrics = policy_metrics(actions, universe_fixtures=universe)
        metrics["roi_ci95"] = _roi_bootstrap_ci(actions)
        rows.append({"threshold": float(threshold), **metrics})
    return rows


def _chronological_split(frame: pd.DataFrame, fraction: float = 0.70) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    valid = frame[frame["_analysis_time"].notna() & frame["fixture_id"].notna()].copy()
    if valid.empty:
        return frame.iloc[0:0].copy(), frame.iloc[0:0].copy(), {"status": "no_dates"}
    fixture_times = valid.groupby("fixture_id", as_index=False)["_analysis_time"].min().sort_values("_analysis_time", kind="stable")
    cut = max(1, min(len(fixture_times) - 1, int(np.floor(len(fixture_times) * fraction))))
    dev_ids = set(fixture_times.iloc[:cut]["fixture_id"].astype(str))
    test_ids = set(fixture_times.iloc[cut:]["fixture_id"].astype(str))
    dev = valid[valid["fixture_id"].astype(str).isin(dev_ids)].copy()
    test = valid[valid["fixture_id"].astype(str).isin(test_ids)].copy()
    return dev, test, {
        "status": "ok",
        "development_fixtures": len(dev_ids),
        "holdout_fixtures": len(test_ids),
        "development_end": str(fixture_times.iloc[cut - 1]["_analysis_time"]),
        "holdout_start": str(fixture_times.iloc[cut]["_analysis_time"]),
    }


def _holdout_stability(frame: pd.DataFrame, candidate: float, baseline: float = CURRENT_THRESHOLD) -> list[dict]:
    if frame.empty:
        return []
    fixture_times = frame.groupby("fixture_id", as_index=False)["_analysis_time"].min().sort_values("_analysis_time", kind="stable")
    chunks = np.array_split(fixture_times, 3)
    out = []
    for i, chunk in enumerate(chunks, 1):
        ids = set(chunk["fixture_id"].astype(str))
        part = frame[frame["fixture_id"].astype(str).isin(ids)]
        cand = policy_metrics(select_fixture_actions(part, candidate), universe_fixtures=len(ids))
        base = policy_metrics(select_fixture_actions(part, baseline), universe_fixtures=len(ids))
        out.append({
            "block": i,
            "fixtures": len(ids),
            "candidate_units": cand["net_units"],
            "baseline_units": base["net_units"],
            "delta_units": cand["net_units"] - base["net_units"],
        })
    return out


def _current_model_version(base: Path) -> str | None:
    path = base / "experiments" / "acceptance" / "production_candidate.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    value = payload.get("version") if isinstance(payload, dict) else None
    return str(value) if value else None


def _scope_audit(frame: pd.DataFrame, scope_name: str) -> dict:
    dev, holdout, split = _chronological_split(frame)
    all_table = threshold_table(frame)
    dev_table = threshold_table(dev) if not dev.empty else []
    holdout_table = threshold_table(holdout) if not holdout.empty else []

    universe_dev = int(dev["fixture_id"].nunique()) if not dev.empty else 0
    eligible = [r for r in dev_table if r["bets"] >= 30 and r["units_per_fixture"] is not None]
    selected = max(eligible, key=lambda r: (r["units_per_fixture"], -r["max_drawdown_units"])) if eligible else None
    selected_threshold = float(selected["threshold"]) if selected else CURRENT_THRESHOLD

    holdout_candidate = next((r for r in holdout_table if r["threshold"] == selected_threshold), None)
    holdout_baseline = next((r for r in holdout_table if r["threshold"] == CURRENT_THRESHOLD), None)
    paired = _paired_delta_ci(holdout, selected_threshold, CURRENT_THRESHOLD) if not holdout.empty else {"delta_units_per_fixture": None, "ci95": [None, None], "fixtures": 0}
    stability = _holdout_stability(holdout, selected_threshold, CURRENT_THRESHOLD) if not holdout.empty else []
    positive_blocks = sum(1 for block in stability if block["delta_units"] > 0)

    if selected_threshold == CURRENT_THRESHOLD:
        decision = "KEEP_45_DEV_SELECTED"
    elif not holdout_candidate or not holdout_baseline or holdout_candidate["bets"] < 20 or holdout_baseline["bets"] < 20:
        decision = "KEEP_45_INSUFFICIENT_HOLDOUT"
    elif paired["ci95"][0] is None or paired["ci95"][0] <= 0:
        decision = "KEEP_45_NO_SIGNIFICANT_HOLDOUT_GAIN"
    elif holdout_candidate["roi"] is None or holdout_baseline["roi"] is None or holdout_candidate["roi"] <= holdout_baseline["roi"]:
        decision = "KEEP_45_NO_HOLDOUT_ROI_GAIN"
    elif positive_blocks < 2:
        decision = "KEEP_45_UNSTABLE_ACROSS_HOLDOUT"
    else:
        decision = f"PROMOTION_CANDIDATE_{selected_threshold:.2f}"

    no_gate = select_fixture_actions(frame, 0.0)
    current = select_fixture_actions(frame, CURRENT_THRESHOLD)
    raw = frame.copy()
    raw["pre_confidence_signal"] = [pricing_signal_without_confidence(r) for _, r in raw.iterrows()]
    raw["current_replay_signal"] = [replay_signal(r, CURRENT_THRESHOLD) for _, r in raw.iterrows()]
    downgraded = raw[
        raw["pre_confidence_signal"].isin({"BET", "LEAN"})
        & raw["current_replay_signal"].eq("REVIEW")
    ].copy()

    return {
        "scope": scope_name,
        "settled_market_rows": int(len(frame)),
        "fixtures": int(frame["fixture_id"].nunique()) if "fixture_id" in frame.columns else 0,
        "state_confidence_non_null_fraction": float(frame["state_confidence"].notna().mean()) if "state_confidence" in frame.columns and len(frame) else None,
        "state_confidence_quantiles": {
            str(q): float(frame["state_confidence"].dropna().quantile(q))
            for q in (0.1, 0.25, 0.5, 0.75, 0.9)
        } if "state_confidence" in frame.columns and frame["state_confidence"].notna().any() else {},
        "current_45_gate_impact": {
            "market_rows_downgraded": int(len(downgraded)),
            "fixtures_with_downgraded_market": int(downgraded["fixture_id"].nunique()) if "fixture_id" in downgraded.columns else 0,
            "no_gate_fixture_actions": policy_metrics(no_gate, universe_fixtures=int(frame["fixture_id"].nunique())),
            "threshold_45_fixture_actions": policy_metrics(current, universe_fixtures=int(frame["fixture_id"].nunique())),
            "paired_no_gate_vs_45": _paired_delta_ci(frame, 0.0, CURRENT_THRESHOLD),
        },
        "thresholds_all": all_table,
        "chronological_split": split,
        "thresholds_development": dev_table,
        "thresholds_holdout": holdout_table,
        "development_selected_threshold": selected_threshold,
        "development_selection_basis": "maximum net units per available fixture; minimum 30 development bets; drawdown tie-breaker",
        "holdout_selected_vs_45": paired,
        "holdout_stability_blocks": stability,
        "decision": decision,
        "promotion_rule": "A non-45 threshold must be selected on development, have >=20 bets for both policies on holdout, paired fixture-bootstrap 95% CI for incremental units/fixture entirely above zero, higher holdout ROI, and positive incremental units in >=2/3 holdout time blocks.",
    }


def build_report(base_dir: str | Path = ".") -> dict:
    base = Path(base_dir)
    source = base / "v5_daily_ready" / "frozen_predictions.csv"
    frame = pd.read_csv(source, low_memory=False)
    settled = _clean_frame(frame)
    version = _current_model_version(base)
    current = settled
    if version and "model_version" in settled.columns:
        scoped = settled[settled["model_version"].fillna("").astype(str).eq(version)].copy()
        if not scoped.empty:
            current = scoped
    report = {
        "audit_version": "state-confidence-gate-v1",
        "source": str(source),
        "source_rows": int(len(frame)),
        "settled_rows": int(len(settled)),
        "current_model_version": version,
        "candidate_thresholds": list(THRESHOLDS),
        "production_threshold": CURRENT_THRESHOLD,
        "primary_scope": _scope_audit(current, "current_model_version" if version and len(current) != len(settled) else "all_settled"),
        "all_history_scope": _scope_audit(settled, "all_settled"),
        "production_policy_changed": False,
    }
    return report


def _fmt_pct(value):
    return "—" if value is None else f"{100 * float(value):+.1f}%"


def _fmt_num(value):
    return "—" if value is None else f"{float(value):+.3f}"


def report_markdown(report: dict) -> str:
    p = report["primary_scope"]
    lines = [
        "# State-confidence gate audit — 2026-09-14",
        "",
        "This is a frozen-history diagnostic. It does **not** alter the production signal policy.",
        "",
        f"Primary scope: **{p['scope']}**; {p['settled_market_rows']:,} settled market rows across {p['fixtures']:,} fixtures.",
        f"Current production confidence threshold: **{report['production_threshold']:.0%}**.",
        "",
        "## Threshold comparison — primary scope",
        "",
        "| Confidence gate | Bets | W-L-P | Net units | ROI | Max DD | Units / fixture | ROI 95% bootstrap CI |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in p["thresholds_all"]:
        ci = row["roi_ci95"]
        ci_text = "—" if ci[0] is None else f"[{_fmt_pct(ci[0])}, {_fmt_pct(ci[1])}]"
        lines.append(
            f"| {row['threshold']:.0%} | {row['bets']} | {row['wins']}-{row['losses']}-{row['pushes']} | "
            f"{row['net_units']:+.3f} | {_fmt_pct(row['roi'])} | {row['max_drawdown_units']:.3f} | "
            f"{_fmt_num(row['units_per_fixture'])} | {ci_text} |"
        )
    impact = p["current_45_gate_impact"]
    lines += [
        "",
        "## What the 45% gate is doing",
        "",
        f"It downgraded {impact['market_rows_downgraded']:,} otherwise BET/LEAN-priced market rows across {impact['fixtures_with_downgraded_market']:,} fixtures in the primary settled scope.",
        f"Fixture-capped no-confidence-gate result: {impact['no_gate_fixture_actions']['bets']} bets, {impact['no_gate_fixture_actions']['net_units']:+.3f} units, {_fmt_pct(impact['no_gate_fixture_actions']['roi'])} ROI.",
        f"Fixture-capped 45% result: {impact['threshold_45_fixture_actions']['bets']} bets, {impact['threshold_45_fixture_actions']['net_units']:+.3f} units, {_fmt_pct(impact['threshold_45_fixture_actions']['roi'])} ROI.",
        "",
        "## Chronological validation",
        "",
        f"Development-selected threshold: **{p['development_selected_threshold']:.0%}**.",
        f"Holdout paired incremental units/fixture vs 45%: {_fmt_num(p['holdout_selected_vs_45']['delta_units_per_fixture'])}; 95% CI {p['holdout_selected_vs_45']['ci95']}.",
        f"Decision under the predeclared promotion rule: **{p['decision']}**.",
        "",
        "The threshold is changed only if the development-selected alternative survives the untouched chronological holdout with a positive paired fixture-bootstrap interval, higher holdout ROI, adequate sample size, and time-block stability.",
    ]
    return "\n".join(lines) + "\n"


def main(base_dir: str | Path = ".") -> int:
    base = Path(base_dir)
    report = build_report(base)
    out_json = base / "experiments" / "acceptance" / "signal_confidence_gate_audit.json"
    out_md = base / "docs" / "experiments" / "2026-09-14-signal-confidence-gate.md"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    out_md.write_text(report_markdown(report), encoding="utf-8")
    print(json.dumps({
        "status": "ok",
        "primary_scope": report["primary_scope"]["scope"],
        "settled_rows": report["primary_scope"]["settled_market_rows"],
        "fixtures": report["primary_scope"]["fixtures"],
        "selected_threshold": report["primary_scope"]["development_selected_threshold"],
        "decision": report["primary_scope"]["decision"],
        "json": str(out_json),
        "markdown": str(out_md),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
