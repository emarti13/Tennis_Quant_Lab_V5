from __future__ import annotations

import math
from typing import Any


_SIGNAL_CLASSES = {
    "BET": "signal-bet",
    "LEAN": "signal-lean",
    "REVIEW": "signal-review",
    "PASS": "signal-pass",
    "NO PRICE": "signal-neutral",
}


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(math.isnan(float(value)))
    except (TypeError, ValueError):
        return False


def format_probability(value: Any) -> str:
    if _is_missing(value):
        return "—"
    return f"{float(value):.1%}"


def format_american_odds(value: Any) -> str:
    if _is_missing(value):
        return "—"
    odds = int(round(float(value)))
    return f"{odds:+d}" if odds > 0 else str(odds)


def format_edge(value: Any) -> str:
    if _is_missing(value):
        return "—"
    return f"{float(value):+.1%}"


def signal_class(signal: str) -> str:
    return _SIGNAL_CLASSES.get(str(signal or "").upper(), "signal-neutral")


def apply_v5_theme(st_module) -> None:
    st_module.markdown(
        """
        <style>
        :root {
            --v5-bg: #f5f5f7;
            --v5-card: rgba(255, 255, 255, 0.92);
            --v5-text: #1d1d1f;
            --v5-muted: #6e6e73;
            --v5-border: rgba(0, 0, 0, 0.08);
            --v5-accent: #0071e3;
            --v5-radius: 22px;
        }

        html, body, [class*="css"] {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        }

        .stApp {
            background: var(--v5-bg);
            color: var(--v5-text);
        }

        [data-testid="stHeader"] {
            background: rgba(245, 245, 247, 0.86);
            backdrop-filter: blur(18px);
        }

        .block-container {
            max-width: 1260px;
            padding-top: 2rem;
            padding-bottom: 4rem;
        }

        .v5-eyebrow {
            color: var(--v5-muted);
            font-size: 0.82rem;
            font-weight: 600;
            letter-spacing: 0.04em;
            text-transform: uppercase;
            margin-bottom: 0.35rem;
        }

        .v5-title {
            color: var(--v5-text);
            font-size: clamp(2rem, 4vw, 3.4rem);
            font-weight: 700;
            letter-spacing: -0.045em;
            line-height: 1.02;
            margin: 0;
        }

        .v5-subtitle {
            color: var(--v5-muted);
            font-size: 1rem;
            margin-top: 0.6rem;
        }

        .v5-card {
            background: var(--v5-card);
            border: 1px solid var(--v5-border);
            border-radius: var(--v5-radius);
            padding: 1.25rem 1.35rem;
            box-shadow: 0 8px 30px rgba(0, 0, 0, 0.035);
            margin-bottom: 0.9rem;
        }

        .v5-summary-card {
            background: var(--v5-card);
            border: 1px solid var(--v5-border);
            border-radius: 18px;
            padding: 1rem 1.1rem;
            min-height: 108px;
        }

        .v5-summary-label {
            color: var(--v5-muted);
            font-size: 0.82rem;
            font-weight: 600;
        }

        .v5-summary-value {
            color: var(--v5-text);
            font-size: 1.55rem;
            font-weight: 700;
            letter-spacing: -0.035em;
            margin-top: 0.15rem;
        }

        .v5-match-name {
            color: var(--v5-text);
            font-size: 1.25rem;
            font-weight: 700;
            letter-spacing: -0.025em;
        }

        .v5-meta {
            color: var(--v5-muted);
            font-size: 0.88rem;
            margin-top: 0.2rem;
        }

        .v5-primary-market {
            color: var(--v5-text);
            font-size: 1.05rem;
            font-weight: 650;
            margin-top: 0.95rem;
        }

        .v5-signal {
            display: inline-flex;
            align-items: center;
            border-radius: 999px;
            padding: 0.24rem 0.58rem;
            font-size: 0.72rem;
            font-weight: 700;
            letter-spacing: 0.03em;
            margin-left: 0.45rem;
            border: 1px solid transparent;
        }

        .signal-bet { background: #e8f4ff; color: #0057a8; border-color: #c9e5ff; }
        .signal-lean { background: #eef7f1; color: #28633d; border-color: #d9ecdf; }
        .signal-review { background: #fff7e6; color: #7a5510; border-color: #f5e5bf; }
        .signal-pass { background: #f0f0f2; color: #66666b; border-color: #e1e1e4; }
        .signal-neutral { background: #f0f0f2; color: #66666b; border-color: #e1e1e4; }

        .v5-metric-line {
            color: var(--v5-muted);
            font-size: 0.92rem;
            margin-top: 0.55rem;
        }

        .v5-metric-line strong {
            color: var(--v5-text);
            font-weight: 650;
        }

        .v5-why {
            margin-top: 0.75rem;
            color: #424245;
            font-size: 0.93rem;
            line-height: 1.45;
        }

        .v5-section-title {
            color: var(--v5-text);
            font-size: 1.35rem;
            font-weight: 700;
            letter-spacing: -0.025em;
            margin: 1.6rem 0 0.85rem;
        }

        .stButton > button[kind="primary"] {
            border-radius: 999px;
            font-weight: 650;
            padding-left: 1.2rem;
            padding-right: 1.2rem;
        }

        @media (max-width: 760px) {
            .block-container {
                padding-left: 1rem;
                padding-right: 1rem;
                padding-top: 1.2rem;
            }
            .v5-card { border-radius: 18px; padding: 1.05rem; }
            .v5-summary-card { min-height: 92px; }
            .v5-title { font-size: 2.15rem; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
