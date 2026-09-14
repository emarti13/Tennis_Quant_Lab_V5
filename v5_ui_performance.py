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
        return {
            "status": "ok",
            "source": str(official_path),
            "official": official,
            "legacy": legacy,
        }
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
            "market_label": "Official recommendations",
            "fixture_label": "Independent fixtures",
            "market_record": f"{wins}-{losses}-{pushes}",
            "market_win_rate": official.get("win_rate"),
            "market_roi": official.get("roi"),
            "market_net_units": official.get("net_units"),
            "fixture_record": f"{profitable} profitable / {fixture_count}",
            "fixture_profitable_rate": fixtures.get("profitable_fixture_rate"),
            "fixture_net_units": fixtures.get("net_units"),
            "mean_markets_per_fixture": None,
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
        raw = current
        fixtures = current_fixtures
        scope = "current_engine"
    elif legacy.get("actionable_markets"):
        raw = legacy.get("actionable_markets") or {}
        fixtures = legacy.get("actionable_fixture_clusters") or {}
        scope = "all_actionable"
    else:
        raw = legacy.get("raw_markets") or {}
        fixtures = legacy.get("fixture_clusters") or {}
        scope = "all_settled"

    wins = int(raw.get("wins") or 0)
    losses = int(raw.get("losses") or 0)
    pushes = int(raw.get("pushes") or 0)
    fixture_count = int(fixtures.get("fixtures") or 0)
    profitable = int(fixtures.get("profitable_fixtures") or 0)
    return {
        "scope": scope,
        "market_label": "Current engine results" if scope == "current_engine" else "Recommended market results",
        "fixture_label": "Current engine fixtures" if scope == "current_engine" else "Recommended fixtures",
        "market_record": f"{wins}-{losses}-{pushes}",
        "market_win_rate": raw.get("win_rate"),
        "market_roi": raw.get("roi"),
        "market_net_units": raw.get("net_units"),
        "fixture_record": f"{profitable} profitable / {fixture_count}",
        "fixture_profitable_rate": fixtures.get("profitable_fixture_rate"),
        "fixture_net_units": fixtures.get("net_units"),
        "mean_markets_per_fixture": fixtures.get("mean_markets_per_fixture"),
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


def _number(value: Any, digits: int = 2) -> str:
    try:
        if value is None or pd.isna(value):
            return "—"
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def _odds(value: Any) -> str:
    try:
        if value is None or pd.isna(value):
            return "—"
        n = int(round(float(value)))
        return f"{n:+d}"
    except (TypeError, ValueError):
        return "—"


def render_performance_page(st_module, report: dict[str, Any] | None) -> dict[str, Any] | None:
    report = report or {}
    status = str(report.get("status") or "missing").lower()
    if status != "ok":
        st_module.info("Settled official recommendation evidence is not available yet. This page will populate automatically after settlement.")
        return None

    headline = headline_metrics(report)
    st_module.markdown('<div class="v5-eyebrow">Validated results</div>', unsafe_allow_html=True)
    st_module.markdown('<div class="v5-title">Performance</div>', unsafe_allow_html=True)
    if headline["scope"] == "official":
        subtitle = "Headline results count one official top play per fixture. Supporting pricing candidates, price-refresh snapshots and PASS / REVIEW observations are audit data, not additional bets."
    elif headline["scope"] == "current_engine":
        subtitle = "Current full-context engine BET + LEAN results are shown while the one-play official recommendation ledger accumulates. Legacy rows remain separate."
    else:
        subtitle = "Historical BET + LEAN results are shown while the one-play official recommendation ledger accumulates. PASS / REVIEW rows are audit-only."
    st_module.markdown(f'<div class="v5-subtitle">{subtitle}</div>', unsafe_allow_html=True)

    columns = st_module.columns(4)
    columns[0].metric("Official record" if headline["scope"] == "official" else "Market record", headline["market_record"])
    columns[1].metric("Fixture evidence", headline["fixture_record"])
    columns[2].metric("Official ROI" if headline["scope"] == "official" else "Market ROI", _percent(headline["market_roi"]))
    columns[3].metric("Max correlated markets", str(headline["max_correlated_markets"]))

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

    st_module.caption("Production Performance settles one official top play per fixture. Supporting pricing candidates are excluded from the betting record and remain available only as audit evidence.")

    legacy = report.get("legacy") or ({} if headline["scope"] == "official" else report)
    with st_module.expander("Legacy and all-market audit", expanded=False):
        if not legacy:
            st_module.caption("No legacy audit is available.")
        else:
            breakdowns = [
                ("Historical audit — by market", "by_market_group"),
                ("Historical audit — by signal", "by_signal"),
                ("Historical audit — by tour", "by_tour"),
                ("Historical audit — by format", "by_best_of"),
            ]
            for label, key in breakdowns:
                payload = legacy.get(key)
                if payload:
                    st_module.markdown(f'<div class="v5-section-title">{label}</div>', unsafe_allow_html=True)
                    frame = pd.DataFrame(payload) if isinstance(payload, list) else pd.DataFrame.from_dict(payload, orient="index")
                    st_module.dataframe(frame, use_container_width=True)

    with st_module.expander("Audit details", expanded=False):
        st_module.json(report)
    return headline
