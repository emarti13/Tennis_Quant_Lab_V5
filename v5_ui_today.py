from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Any, Callable

import pandas as pd

from v5_ui_theme import (
    format_american_odds,
    format_edge,
    format_probability,
    signal_class,
)


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
    if value is None:
        return True
    try:
        missing = pd.isna(value)
        if isinstance(missing, bool) and missing:
            return True
    except (TypeError, ValueError):
        pass
    return str(value).strip() == ""


def _is_true(value: Any) -> bool:
    if _missing(value):
        return False
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes"}


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


def _display_primary_for_row(row: pd.Series) -> dict[str, Any]:
    """Use the immutable official play once one has been frozen for this fixture."""
    candidate = primary_market_for_row(row)
    official_signal = str(row.get("Official Signal") or "").upper().strip()
    official_market = row.get("Official Market")
    if _is_true(row.get("Official Locked")) and not _missing(official_market) and official_signal in {"BET", "LEAN"}:
        return {
            "family": "official",
            "selection": str(official_market),
            "signal": official_signal,
            "edge": _float_or_none(row.get("Official Edge")),
            "market_odds": _float_or_none(row.get("Official Price")),
            "signal_col": None,
            "ev_col": None,
            "odds_col": None,
        }
    return candidate


def prepare_today_board(board: pd.DataFrame) -> pd.DataFrame:
    if board is None or board.empty:
        return pd.DataFrame(columns=list(board.columns) if board is not None else [])

    out = board.copy()
    primary = [_display_primary_for_row(row) for _, row in out.iterrows()]
    out["Best Signal"] = [item["signal"] for item in primary]
    out["Primary Market"] = [item["selection"] for item in primary]
    out["Primary Market Family"] = [item["family"] for item in primary]
    out["Primary Edge"] = [item["edge"] for item in primary]
    out["Primary Market Odds"] = [item["market_odds"] for item in primary]
    out["Primary Signal Col"] = [item["signal_col"] for item in primary]
    out["Primary EV Col"] = [item["ev_col"] for item in primary]
    out["Primary Odds Col"] = [item["odds_col"] for item in primary]
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


def today_summary(
    board: pd.DataFrame,
    market_feed: pd.DataFrame | None,
    snapshot: str | None,
) -> dict[str, Any]:
    prepared = board.copy() if board is not None else pd.DataFrame()
    if not prepared.empty and ("Best Signal" not in prepared.columns or "Primary Edge" not in prepared.columns):
        prepared = prepare_today_board(prepared)

    edges = pd.to_numeric(prepared.get("Primary Edge", pd.Series(dtype=float)), errors="coerce")
    best_edge = None if edges.dropna().empty else float(edges.max())
    signals = prepared.get("Best Signal", pd.Series(dtype=str)).astype(str).str.upper()
    qualified = int(signals.isin(["BET", "LEAN"]).sum())

    feed = market_feed if market_feed is not None else pd.DataFrame()
    markets_live = 0
    for col in ("bookmaker", "book", "sportsbook"):
        if col in feed.columns:
            markets_live = int(feed[col].dropna().astype(str).replace("", pd.NA).dropna().nunique())
            break

    return {
        "best_edge": best_edge,
        "qualified_plays": qualified,
        "matches_analyzed": int(len(prepared)),
        "markets_live": markets_live,
        "snapshot": snapshot or "Unknown",
    }


def _format_start(value: Any) -> str:
    if _missing(value):
        return "Time TBD"
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    if pd.isna(parsed):
        return str(value)
    try:
        return parsed.strftime("%b %-d · %-I:%M %p UTC")
    except ValueError:
        return parsed.strftime("%b %d · %I:%M %p UTC").replace(" 0", " ")


def _model_probability_and_fair(row: pd.Series) -> tuple[Any, Any]:
    source = str(row.get("Primary Signal Col") or "")
    primary = str(row.get("Primary Market") or "")
    p2 = str(row.get("Player 2") or "")
    use_p2 = source.startswith("P2 ") or (p2 and primary.startswith(p2))
    if use_p2:
        return row.get("P2 V5 %"), row.get("P2 Fair")
    return row.get("P1 V5 %"), row.get("P1 Fair")


def _ordinal(value: Any) -> str:
    number = _float_or_none(value)
    if number is None:
        return "—"
    n = int(round(number))
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _form_label(value: Any) -> str:
    number = _float_or_none(value)
    if number is None:
        return "Unknown"
    magnitude = abs(number)
    if magnitude < 0.010:
        return "Neutral"
    if magnitude < 0.025:
        return "Slightly positive" if number > 0 else "Slightly negative"
    if magnitude < 0.050:
        return "Positive" if number > 0 else "Negative"
    return "Strong positive" if number > 0 else "Strong negative"


def _market_output_html(row: pd.Series) -> str:
    items = []
    p1 = escape(str(row.get("Player 1") or "Player 1"))
    p2 = escape(str(row.get("Player 2") or "Player 2"))
    candidates = (
        (f"{p1} ML", "P1 ML Signal", "P1 ML EV", "P1 ML"),
        (f"{p2} ML", "P2 ML Signal", "P2 ML EV", "P2 ML"),
        (f"{p1} spread", "P1 Spread Signal", "P1 Spread EV", "P1 Spread Odds"),
        (f"{p2} spread", "P2 Spread Signal", "P2 Spread EV", "P2 Spread Odds"),
        ("Over", "Over Signal", "Over EV", "Over Odds"),
        ("Under", "Under Signal", "Under EV", "Under Odds"),
    )
    for label, signal_col, ev_col, odds_col in candidates:
        signal = str(row.get(signal_col) or "").upper().strip()
        if signal not in {"BET", "LEAN", "REVIEW"}:
            continue
        ev = _float_or_none(row.get(ev_col))
        odds = row.get(odds_col)
        items.append(
            f'<span class="v5-signal {signal_class(signal)}">{escape(signal)}</span> '
            f'<strong>{label}</strong> · {format_american_odds(odds)} · '
            f'EV {format_edge(ev)}'
        )
    if not items:
        return '<div class="v5-metric-line">No BET / LEAN / REVIEW market clears the current pricing policy.</div>'
    return '<div class="v5-market-output">' + '<br>'.join(items[:4]) + '</div>'


def match_card_html(row: pd.Series) -> str:
    p1 = escape(str(row.get("Player 1") or "Player 1"))
    p2 = escape(str(row.get("Player 2") or "Player 2"))
    tournament = escape(str(row.get("Tournament") or "Tournament TBD"))
    tour_raw = str(row.get("Tour") or "").upper()
    tour = "Men" if tour_raw == "MEN" else ("WTA" if tour_raw == "WTA" else escape(tour_raw or "Tour TBD"))
    best_of = _float_or_none(row.get("Best Of"))
    bo = f"Bo{int(best_of)}" if best_of is not None else "Format TBD"
    start = escape(_format_start(row.get("Start")))
    signal = str(row.get("Best Signal") or "NO PRICE").upper()
    primary_market = escape(str(row.get("Primary Market") or "No priced market"))
    edge = row.get("Primary Edge")
    market_odds = row.get("Primary Market Odds")
    explanation = escape(why_it_stands_out(row))

    p1_prob = row.get("P1 V5 %")
    p2_prob = row.get("P2 V5 %")
    p1_fair = row.get("P1 Fair")
    p2_fair = row.get("P2 Fair")
    margin = _float_or_none(row.get("Expected Margin"))
    total = _float_or_none(row.get("Expected Total"))
    gap = _float_or_none(row.get("Model Gap"))
    agreement = escape(str(row.get("Agreement") or "Unknown"))

    p1_form = _float_or_none(row.get("P1 Form"))
    p2_form = _float_or_none(row.get("P2 Form"))
    p1_vol = _float_or_none(row.get("P1 Volatility"))
    p2_vol = _float_or_none(row.get("P2 Volatility"))
    p1_conf = _float_or_none(row.get("P1 State Conf"))
    p2_conf = _float_or_none(row.get("P2 State Conf"))

    margin_text = "—" if margin is None else f"{margin:+.2f}"
    total_text = "—" if total is None else f"{total:.2f}"
    gap_text = "—" if gap is None else f"{gap:.1%}"
    p1_form_num = "—" if p1_form is None else f"{p1_form:+.3f}"
    p2_form_num = "—" if p2_form is None else f"{p2_form:+.3f}"
    p1_vol_num = "—" if p1_vol is None else f"σ {p1_vol:.3f}"
    p2_vol_num = "—" if p2_vol is None else f"σ {p2_vol:.3f}"
    p1_conf_text = "—" if p1_conf is None else f"{p1_conf:.0%}"
    p2_conf_text = "—" if p2_conf is None else f"{p2_conf:.0%}"
    if _is_true(row.get("Official Locked")):
        primary_label = "Official top play"
    elif signal in {"BET", "LEAN"}:
        primary_label = "Top play candidate"
    else:
        primary_label = "Primary model view"

    html = f"""
    <div class="v5-card">
      <div class="v5-match-name">{p1} <span style="color:#86868b;font-weight:500;">vs</span> {p2}</div>
      <div class="v5-meta">{tournament} · {start} · {tour} · {bo}</div>
      <div class="v5-why"><strong>{primary_label}</strong></div>
      <div class="v5-primary-market">{primary_market}<span class="v5-signal {signal_class(signal)}">{escape(signal)}</span></div>

      <div class="v5-why"><strong>Match projection</strong></div>
      <div class="v5-metric-line"><strong>{p1}</strong> {format_probability(p1_prob)} · Fair {format_american_odds(p1_fair)} &nbsp;&nbsp; <strong>{p2}</strong> {format_probability(p2_prob)} · Fair {format_american_odds(p2_fair)}</div>
      <div class="v5-metric-line">Expected margin <strong>{margin_text}</strong> · Expected total <strong>{total_text}</strong></div>

      <div class="v5-why"><strong>Current form, volatility & confidence</strong></div>
      <div class="v5-metric-line"><strong>{p1}</strong> — Recent form {_form_label(p1_form)} ({p1_form_num}, {_ordinal(row.get('P1 Form Percentile'))} pct) · Match-day volatility {escape(str(row.get('P1 Volatility Label') or 'Unknown'))} ({p1_vol_num}, {_ordinal(row.get('P1 Volatility Percentile'))} pct) · State confidence {escape(str(row.get('P1 State Conf Label') or 'Unknown'))} ({p1_conf_text})</div>
      <div class="v5-metric-line"><strong>{p2}</strong> — Recent form {_form_label(p2_form)} ({p2_form_num}, {_ordinal(row.get('P2 Form Percentile'))} pct) · Match-day volatility {escape(str(row.get('P2 Volatility Label') or 'Unknown'))} ({p2_vol_num}, {_ordinal(row.get('P2 Volatility Percentile'))} pct) · State confidence {escape(str(row.get('P2 State Conf Label') or 'Unknown'))} ({p2_conf_text})</div>
      <div class="v5-metric-line">Simulator vs Surface Elo <strong>{agreement}</strong> · {gap_text} probability gap</div>

      <div class="v5-why"><strong>Current pricing candidates</strong> — not separately logged as official bets</div>
      {_market_output_html(row)}
      <div class="v5-metric-line">Selected market price <strong>{format_american_odds(market_odds)}</strong> · EV/edge <strong>{format_edge(edge)}</strong></div>
      <div class="v5-why"><strong>Why it stands out:</strong> {explanation}</div>
    </div>
    """
    return "".join(line.strip() for line in html.splitlines())


def _summary_card_html(label: str, value: str, detail: str = "") -> str:
    detail_html = f'<div class="v5-meta">{escape(detail)}</div>' if detail else ""
    return (
        '<div class="v5-summary-card">'
        f'<div class="v5-summary-label">{escape(label)}</div>'
        f'<div class="v5-summary-value">{escape(value)}</div>'
        f"{detail_html}</div>"
    )


def _render_match_card(st_module, row: pd.Series) -> None:
    card = match_card_html(row)
    if hasattr(st_module, "html"):
        st_module.html(card)
    else:
        st_module.markdown(card, unsafe_allow_html=True)


def _render_card_action(st_module, row: pd.Series, on_select: Callable[[Any], None] | None) -> None:
    if on_select is None or not hasattr(st_module, "button"):
        return
    fixture_id = row.get("Fixture ID")
    if _missing(fixture_id):
        fixture_id = f"{row.get('Player 1', '')}-{row.get('Player 2', '')}-{row.name}"
    if st_module.button("View analysis", key=f"v5_view_{fixture_id}", use_container_width=True):
        on_select(fixture_id)


def render_today_results(
    st_module,
    board: pd.DataFrame | None,
    market_feed: pd.DataFrame | None,
    snapshot: str | None,
    on_select: Callable[[Any], None] | None = None,
) -> pd.DataFrame:
    if board is None or board.empty:
        st_module.info("No modeled matches are available yet. Run the current slate to populate Today.")
        return pd.DataFrame()

    prepared = prepare_today_board(board)
    summary = today_summary(prepared, market_feed, snapshot)

    st_module.caption(
        f'{summary["matches_analyzed"]} matches analyzed · market snapshot {summary["snapshot"]}'
    )

    if hasattr(st_module, "columns"):
        cols = st_module.columns(4)
        cards = [
            ("Best Edge", format_edge(summary["best_edge"]), "strongest frozen/candidate edge"),
            ("Qualified Plays", str(summary["qualified_plays"]), "official or current BET + LEAN top plays"),
            ("Model Health", "Live", "production outputs loaded"),
            ("Markets Live", str(summary["markets_live"]), "books in current feed"),
        ]
        for col, (label, value, detail) in zip(cols, cards):
            col.markdown(_summary_card_html(label, value, detail), unsafe_allow_html=True)

    actionable = prepared[prepared["Best Signal"].isin(["BET", "LEAN", "REVIEW"])].copy()
    other = prepared[~prepared.index.isin(actionable.index)].copy()

    if actionable.empty:
        st_module.info("No qualified plays on the current slate. The full modeled board remains available below.")
    else:
        st_module.markdown('<div class="v5-section-title">Top opportunities</div>', unsafe_allow_html=True)
        for _, row in actionable.iterrows():
            _render_match_card(st_module, row)
            _render_card_action(st_module, row, on_select)

    if not other.empty:
        if hasattr(st_module, "expander"):
            with st_module.expander(f"Other matches ({len(other)})", expanded=False):
                for _, row in other.iterrows():
                    _render_match_card(st_module, row)
                    _render_card_action(st_module, row, on_select)
        else:
            for _, row in other.iterrows():
                _render_match_card(st_module, row)

    return prepared
