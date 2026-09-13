from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd


LEGACY_PERFORMANCE_PATH = Path("v5_daily_ready") / "settled_performance_audit.json"
OFFICIAL_PERFORMANCE_PATH = Path("v5_daily_ready") / "official_performance.json"


def _read_report(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def load_performance_report(base_dir: str | Path = ".") -> dict[str, Any]:
    base = Path(base_dir)
    official_path = base / OFFICIAL_PERFORMANCE_PATH
    legacy_path = base / LEGACY_PERFORMANCE_PATH
    official = _read_report(official_path)
    legacy = _read_report(legacy_path)
    if not official and not legacy:
        return {"status": "missing", "source": str(official_path)}
    if official:
        return {"status": "ok", "source": str(official_path), "official": official, "legacy": legacy}
    legacy.setdefault("status", "ok")
    legacy.setdefault("source", str(legacy_path))
    return legacy


def headline_metrics(report: dict[str, Any] | None) -> dict[str, Any]:
    report = report or {}
    official = report.get("official") or {}
    if official and int(official.get("official_recommendations") or 0) > 0:
        fixtures = official.get("fixture_cluster") or {}
        wins = int(official.get("wins") or 0)
        losses = int(official.get("losses") or 0)
        pushes = int(official.get("pushes") or 0)
        fixture_count = int(fixtures.get("fixtures") or official.get("unique_fixtures") or 0)
        profitable = int(fixtures.get("profitable_fixtures") or 0)
        return {
            "scope": "official",
            "market_record": f"{wins}-{losses}-{pushes}",
            "market_win_rate": official.get("win_rate"),
            "market_roi": official.get("roi"),
            "market_net_units": official.get("net_units"),
            "fixture_record": f"{profitable} profitable / {fixture_count}",
            "fixture_profitable_rate": fixtures.get("profitable_fixture_rate"),
            "fixture_net_units": fixtures.get("net_units"),
            "max_correlated_markets": int(official.get("max_recommendations_per_fixture") or 0),
            "median_american_odds": official.get("median_american_odds"),
            "favorite_recommendations": int(official.get("favorite_recommendations") or 0),
            "underdog_recommendations": int(official.get("underdog_recommendations") or 0),
        }

    legacy = report.get("legacy") or report
    current = legacy.get("current_engine_markets") or {}
    current_fixtures = legacy.get("current_engine_fixture_clusters") or {}
    current_count = int(current.get("bets") or 0)
    if current_count == 0:
        current_count = int(current.get("wins") or 0) + int(current.get("losses") or 0) + int(current.get("pushes") or 0)
    if current_count > 0:
        raw, fixtures, scope = current, current_fixtures, "current_engine"
    elif legacy.get("actionable_markets"):
        raw, fixtures, scope = legacy.get("actionable_markets") or {}, legacy.get("actionable_fixture_clusters") or {}, "all_actionable"
    else:
        raw, fixtures, scope = legacy.get("raw_markets") or {}, legacy.get("fixture_clusters") or {}, "all_settled"
    wins = int(raw.get("wins") or 0)
    losses = int(raw.get("losses") or 0)
    pushes = int(raw.get("pushes") or 0)
    fixture_count = int(fixtures.get("fixtures") or 0)
    profitable = int(fixtures.get("profitable_fixtures") or 0)
    return {
        "scope": scope,
        "market_record": f"{wins}-{losses}-{pushes}",
        "market_win_rate": raw.get("win_rate"),
        "market_roi": raw.get("roi"),
        "market_net_units": raw.get("net_units"),
        "fixture_record": f"{profitable} profitable / {fixture_count}",
        "fixture_profitable_rate": fixtures.get("profitable_fixture_rate"),
        "fixture_net_units": fixtures.get("net_units"),
        "max_correlated_markets": int(fixtures.get("max_markets_on_one_fixture") or 0),
        "median_american_odds": None,
        "favorite_recommendations": 0,
        "underdog_recommendations": 0,
    }


def _percent(value: Any) -> str:
    try:
        if value is None or pd.isna(value):
            return "—"
        return f"{float(value):.1%}"
    except (TypeError, ValueError):
        return "—"


def _odds(value: Any) -> str:
    try:
        if value is None or pd.isna(value):
            return "—"
        return f"{int(round(float(value))):+d}"
    except (TypeError, ValueError):
        return "—"


def render_performance_page(st_module, report: dict[str, Any] | None) -> dict[str, Any] | None:
    report = report or {}
    if str(report.get("status") or "missing").lower() != "ok":
        st_module.info("Settled official recommendation evidence is not available yet. This page will populate automatically after settlement.")
        return None

    headline = headline_metrics(report)
    st_module.markdown('<div class="v5-eyebrow">Validated results</div>', unsafe_allow_html=True)
    st_module.markdown('<div class="v5-title">Performance</div>', unsafe_allow_html=True)
    if headline["scope"] == "official":
        subtitle = "Headline results count each official recommendation once. Price-refresh snapshots and PASS / REVIEW observations are audit data, not bets."
    else:
        subtitle = "Legacy evidence is shown only until the canonical official ledger accumulates settled recommendations."
    st_module.markdown(f'<div class="v5-subtitle">{subtitle}</div>', unsafe_allow_html=True)

    cols = st_module.columns(4)
    cols[0].metric("Market record", headline["market_record"])
    cols[1].metric("Fixture evidence", headline["fixture_record"])
    cols[2].metric("Market ROI", _percent(headline["market_roi"]))
    cols[3].metric("Max recs / fixture", str(headline["max_correlated_markets"]))

    if headline["scope"] == "official":
        meta = st_module.columns(3)
        meta[0].metric("Median odds", _odds(headline["median_american_odds"]))
        meta[1].metric("Favorites", str(headline["favorite_recommendations"]))
        meta[2].metric("Underdogs", str(headline["underdog_recommendations"]))
        official = report.get("official") or {}
        by_signal = official.get("by_signal") or {}
        if by_signal:
            st_module.markdown('<div class="v5-section-title">Official recommendations by signal</div>', unsafe_allow_html=True)
            st_module.dataframe(pd.DataFrame.from_dict(by_signal, orient="index"), use_container_width=True)
        by_price = official.get("by_price_band") or {}
        if by_price:
            with st_module.expander("Official performance by price band", expanded=False):
                st_module.dataframe(pd.DataFrame.from_dict(by_price, orient="index"), use_container_width=True)

    st_module.caption("Fixture-cluster evidence is reported separately so multiple markets from one match are not mistaken for independent proof of model quality.")

    legacy = report.get("legacy") or ({} if headline["scope"] == "official" else report)
    with st_module.expander("Legacy and all-market audit", expanded=False):
        if not legacy:
            st_module.caption("No legacy audit is available.")
        else:
            for label, key in [
                ("Historical audit — by market", "by_market_group"),
                ("Historical audit — by signal", "by_signal"),
                ("Historical audit — by tour", "by_tour"),
                ("Historical audit — by format", "by_best_of"),
            ]:
                payload = legacy.get(key)
                if payload:
                    st_module.markdown(f'<div class="v5-section-title">{label}</div>', unsafe_allow_html=True)
                    frame = pd.DataFrame(payload) if isinstance(payload, list) else pd.DataFrame.from_dict(payload, orient="index")
                    st_module.dataframe(frame, use_container_width=True)

    with st_module.expander("Audit details", expanded=False):
        st_module.json(report)
    return headline
