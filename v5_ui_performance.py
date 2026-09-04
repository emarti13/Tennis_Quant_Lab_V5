from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd


PERFORMANCE_PATH = Path("v5_daily_ready") / "settled_performance_audit.json"


def load_performance_report(base_dir: str | Path = ".") -> dict[str, Any]:
    path = Path(base_dir) / PERFORMANCE_PATH
    if not path.exists():
        return {"status": "missing", "source": str(path)}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "invalid", "source": str(path), "error": str(exc)}
    if not isinstance(payload, dict):
        return {"status": "invalid", "source": str(path), "error": "report must be a JSON object"}
    payload.setdefault("status", "ok")
    payload.setdefault("source", str(path))
    return payload


def headline_metrics(report: dict[str, Any] | None) -> dict[str, Any]:
    report = report or {}
    raw = report.get("actionable_markets") or report.get("raw_markets") or {}
    fixtures = report.get("actionable_fixture_clusters") or report.get("fixture_clusters") or {}

    wins = int(raw.get("wins") or 0)
    losses = int(raw.get("losses") or 0)
    pushes = int(raw.get("pushes") or 0)
    fixture_count = int(fixtures.get("fixtures") or 0)
    profitable = int(fixtures.get("profitable_fixtures") or 0)

    return {
        "market_label": "Recommended market results",
        "fixture_label": "Recommended fixtures",
        "market_record": f"{wins}-{losses}-{pushes}",
        "market_win_rate": raw.get("win_rate"),
        "market_roi": raw.get("roi"),
        "market_net_units": raw.get("net_units"),
        "fixture_record": f"{profitable} profitable / {fixture_count}",
        "fixture_profitable_rate": fixtures.get("profitable_fixture_rate"),
        "fixture_net_units": fixtures.get("net_units"),
        "mean_markets_per_fixture": fixtures.get("mean_markets_per_fixture"),
        "max_correlated_markets": int(fixtures.get("max_markets_on_one_fixture") or 0),
    }


def _percent(value: Any) -> str:
    try:
        if value is None or pd.isna(value):
            return "—"
        return f"{float(value):.1%}"
    except (TypeError, ValueError):
        return "—"


def _number(value: Any, digits: int = 2) -> str:
    try:
        if value is None or pd.isna(value):
            return "—"
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def render_performance_page(st_module, report: dict[str, Any] | None) -> dict[str, Any] | None:
    report = report or {}
    status = str(report.get("status") or "missing").lower()
    if status != "ok":
        st_module.info(
            "Settled performance evidence is not available yet. This page will populate after the settlement audit produces a current report."
        )
        return None

    headline = headline_metrics(report)
    st_module.markdown('<div class="v5-eyebrow">Validated results</div>', unsafe_allow_html=True)
    st_module.markdown('<div class="v5-title">Performance</div>', unsafe_allow_html=True)
    st_module.markdown(
        '<div class="v5-subtitle">BET + LEAN results are the headline. PASS / REVIEW rows remain audit evidence and are not counted as recommendations.</div>',
        unsafe_allow_html=True,
    )

    columns = st_module.columns(4)
    columns[0].metric("Market record", headline["market_record"])
    columns[1].metric("Fixture evidence", headline["fixture_record"])
    columns[2].metric("Market ROI", _percent(headline["market_roi"]))
    columns[3].metric("Max correlated markets", str(headline["max_correlated_markets"]))

    st_module.caption(
        "Multiple correlated markets from the same match remain legitimate market observations, but they are not treated as independent evidence of model quality."
    )

    calibration = report.get("moneyline_calibration") or {}
    if calibration:
        st_module.markdown('<div class="v5-section-title">Moneyline calibration</div>', unsafe_allow_html=True)
        cal_cols = st_module.columns(3)
        cal_cols[0].metric("Settled ML", str(int(calibration.get("n") or 0)))
        cal_cols[1].metric("Brier", _number(calibration.get("brier"), 3))
        cal_cols[2].metric("Log loss", _number(calibration.get("log_loss"), 3))

    breakdowns = [
        ("By market", "by_market_group"),
        ("By signal", "by_signal"),
        ("By tour", "by_tour"),
        ("By format", "by_best_of"),
    ]
    for label, key in breakdowns:
        payload = report.get(key)
        if payload:
            st_module.markdown(f'<div class="v5-section-title">{label}</div>', unsafe_allow_html=True)
            frame = pd.DataFrame(payload) if isinstance(payload, list) else pd.DataFrame.from_dict(payload, orient="index")
            st_module.dataframe(frame, use_container_width=True)

    with st_module.expander("Audit details", expanded=False):
        st_module.json(report)

    return headline
