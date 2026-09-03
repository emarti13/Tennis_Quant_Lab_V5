from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd


_SIGNAL_PRIORITY = {
    "BET": 0,
    "LEAN": 1,
    "REVIEW": 2,
    "PASS": 3,
    "NO PRICE": 4,
    "": 5,
}


@dataclass(frozen=True)
class MarketCandidate:
    family: str
    selection: str
    signal_col: str
    ev_col: str
    odds_col: str | None


_MARKET_CANDIDATES = (
    MarketCandidate("moneyline", "{p1} ML", "P1 ML Signal", "P1 ML EV", "P1 ML"),
    MarketCandidate("moneyline", "{p2} ML", "P2 ML Signal", "P2 ML EV", "P2 ML"),
    MarketCandidate("spread", "{p1} {p1_spread}", "P1 Spread Signal", "P1 Spread EV", "P1 Spread Odds"),
    MarketCandidate("spread", "{p2} {p2_spread}", "P2 Spread Signal", "P2 Spread EV", "P2 Spread Odds"),
    MarketCandidate("total", "Over {total}", "Over Signal", "Over EV", "Over Odds"),
    MarketCandidate("total", "Under {total}", "Under Signal", "Under EV", "Under Odds"),
)


def _missing(value: Any) -> bool:
    return pd.isna(value) or str(value).strip() == ""


def _float_or_none(value: Any) -> float | None:
    if _missing(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clean_line(value: Any) -> str:
    number = _float_or_none(value)
    if number is None:
        return ""
    if number.is_integer():
        return f"{number:+.0f}" if number != 0 else "0"
    return f"{number:+g}" if number < 0 else f"+{number:g}"


def _selection_text(candidate: MarketCandidate, row: pd.Series) -> str:
    p1 = str(row.get("Player 1") or "Player 1")
    p2 = str(row.get("Player 2") or "Player 2")
    total = _float_or_none(row.get("Total"))
    total_text = f"{total:g}" if total is not None else ""
    return candidate.selection.format(
        p1=p1,
        p2=p2,
        p1_spread=_clean_line(row.get("P1 Spread")),
        p2_spread=_clean_line(row.get("P2 Spread")),
        total=total_text,
    ).strip()


def primary_market_for_row(row: pd.Series) -> dict[str, Any]:
    ranked: list[tuple[int, float, int, dict[str, Any]]] = []
    for index, candidate in enumerate(_MARKET_CANDIDATES):
        signal = str(row.get(candidate.signal_col) or "").upper().strip()
        if not signal:
            continue
        edge = _float_or_none(row.get(candidate.ev_col))
        market_odds = _float_or_none(row.get(candidate.odds_col)) if candidate.odds_col else None
        payload = {
            "family": candidate.family,
            "selection": _selection_text(candidate, row),
            "signal": signal,
            "edge": edge,
            "market_odds": market_odds,
            "signal_col": candidate.signal_col,
            "ev_col": candidate.ev_col,
            "odds_col": candidate.odds_col,
        }
        edge_sort = edge if edge is not None else float("-inf")
        ranked.append((_SIGNAL_PRIORITY.get(signal, 9), -edge_sort, index, payload))

    if not ranked:
        return {
            "family": "",
            "selection": "No priced market",
            "signal": "NO PRICE",
            "edge": None,
            "market_odds": None,
            "signal_col": None,
            "ev_col": None,
            "odds_col": None,
        }

    ranked.sort(key=lambda item: (item[0], item[1], item[2]))
    return ranked[0][3]


def prepare_today_board(board: pd.DataFrame) -> pd.DataFrame:
    if board is None or board.empty:
        return pd.DataFrame(columns=list(board.columns) if board is not None else [])

    out = board.copy()
    primary = [primary_market_for_row(row) for _, row in out.iterrows()]
    out["Best Signal"] = [item["signal"] for item in primary]
    out["Primary Market"] = [item["selection"] for item in primary]
    out["Primary Market Family"] = [item["family"] for item in primary]
    out["Primary Edge"] = [item["edge"] for item in primary]
    out["Primary Market Odds"] = [item["market_odds"] for item in primary]
    out["_signal_rank"] = out["Best Signal"].map(lambda value: _SIGNAL_PRIORITY.get(str(value), 9))
    out["_edge_rank"] = pd.to_numeric(out["Primary Edge"], errors="coerce").fillna(float("-inf"))

    sort_cols = ["_signal_rank", "_edge_rank"]
    ascending = [True, False]
    if "Start" in out.columns:
        sort_cols.append("Start")
        ascending.append(True)

    out = out.sort_values(sort_cols, ascending=ascending, kind="stable", na_position="last")
    return out.drop(columns=["_signal_rank", "_edge_rank"]).reset_index(drop=True)


def why_it_stands_out(row: pd.Series) -> str:
    reasons: list[str] = []

    agreement = _float_or_none(row.get("Agreement"))
    if agreement is not None:
        if agreement >= 0.85:
            reasons.append("strong model agreement")
        elif agreement >= 0.70:
            reasons.append("solid model agreement")
        else:
            reasons.append("mixed model agreement")

    gap = _float_or_none(row.get("Model Gap"))
    if gap is not None and gap <= 0.04:
        reasons.append("low model disagreement")

    margin = _float_or_none(row.get("Expected Margin"))
    if margin is not None:
        reasons.append(f"projected margin {margin:+.1f} games")

    total = _float_or_none(row.get("Expected Total"))
    if total is not None and not reasons:
        reasons.append(f"projected total {total:.1f} games")

    if not reasons:
        primary = primary_market_for_row(row)
        edge = primary.get("edge")
        if edge is not None:
            reasons.append(f"{primary['signal'].lower()}-tier edge {float(edge):+.1%}")

    if not reasons:
        return "Model output available; deeper context is available in match analysis."

    text = ", ".join(reasons[:3])
    return text[0].upper() + text[1:] + "."
