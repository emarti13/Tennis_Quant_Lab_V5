from pathlib import Path

# 1) Enrich the existing daily simulation row with the same already-computed
# player-state values shown by Matchup Lab. No model calculation changes.
app = Path("tennis_quant_app_v5.py")
text = app.read_text(encoding="utf-8")
needle = '''        "P1 State Conf": p1_conf,\n        "P2 State Conf": p2_conf,\n        "Note": "",\n'''
replacement = '''        "P1 State Conf": p1_conf,\n        "P2 State Conf": p2_conf,\n        "P1 Form": form_a,\n        "P2 Form": form_b,\n        "P1 Form Percentile": float(a.get("form_percentile", 50.0)),\n        "P2 Form Percentile": float(b.get("form_percentile", 50.0)),\n        "P1 Volatility": vol_a,\n        "P2 Volatility": vol_b,\n        "P1 Volatility Percentile": float(a.get("vol_percentile", 50.0)),\n        "P2 Volatility Percentile": float(b.get("vol_percentile", 50.0)),\n        "P1 Volatility Label": str(a.get("volatility_label", "Average")),\n        "P2 Volatility Label": str(b.get("volatility_label", "Average")),\n        "P1 State Conf Label": str(a.get("state_confidence_label", "Unknown")),\n        "P2 State Conf Label": str(b.get("state_confidence_label", "Unknown")),\n        "Surface Elo P1 %": p_elo,\n        "Note": "",\n'''
if needle not in text:
    raise SystemExit("daily result insertion point not found")
app.write_text(text.replace(needle, replacement, 1), encoding="utf-8")

# 2) Preserve the exact market inputs used for the daily simulation so Today can
# render the same pricing context without recomputation.
host = Path("v5_ui_host.py")
text = host.read_text(encoding="utf-8")
needle = '''            if "Best Of" in row.index and "Best Of" not in result:\n                result["Best Of"] = row.get("Best Of")\n            results.append(result)\n'''
replacement = '''            if "Best Of" in row.index and "Best Of" not in result:\n                result["Best Of"] = row.get("Best Of")\n            for market_field in (\n                "P1 ML", "P2 ML", "P1 Spread", "P1 Spread Odds",\n                "P2 Spread", "P2 Spread Odds", "Total", "Over Odds", "Under Odds",\n            ):\n                if market_field in row.index:\n                    result[market_field] = row.get(market_field)\n            results.append(result)\n'''
if needle not in text:
    raise SystemExit("host market-preservation insertion point not found")
host.write_text(text.replace(needle, replacement, 1), encoding="utf-8")

# 3) Replace only the Today card renderer. Ranking/navigation/other pages stay unchanged.
today = Path("v5_ui_today.py")
text = today.read_text(encoding="utf-8")
start = text.index("def match_card_html(row: pd.Series) -> str:\n")
end = text.index("\ndef _summary_card_html", start)
new_block = r'''def _ordinal(value: Any) -> str:
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

    return f"""
    <div class="v5-card">
      <div class="v5-match-name">{p1} <span style="color:#86868b;font-weight:500;">vs</span> {p2}</div>
      <div class="v5-meta">{tournament} · {start} · {tour} · {bo}</div>
      <div class="v5-primary-market">{primary_market}<span class="v5-signal {signal_class(signal)}">{escape(signal)}</span></div>

      <div class="v5-why"><strong>Match projection</strong></div>
      <div class="v5-metric-line"><strong>{p1}</strong> {format_probability(p1_prob)} · Fair {format_american_odds(p1_fair)} &nbsp;&nbsp; <strong>{p2}</strong> {format_probability(p2_prob)} · Fair {format_american_odds(p2_fair)}</div>
      <div class="v5-metric-line">Expected margin <strong>{margin_text}</strong> · Expected total <strong>{total_text}</strong></div>

      <div class="v5-why"><strong>Current form, volatility & confidence</strong></div>
      <div class="v5-metric-line"><strong>{p1}</strong> — Recent form {_form_label(p1_form)} ({p1_form_num}, {_ordinal(row.get('P1 Form Percentile'))} pct) · Match-day volatility {escape(str(row.get('P1 Volatility Label') or 'Unknown'))} ({p1_vol_num}, {_ordinal(row.get('P1 Volatility Percentile'))} pct) · State confidence {escape(str(row.get('P1 State Conf Label') or 'Unknown'))} ({p1_conf_text})</div>
      <div class="v5-metric-line"><strong>{p2}</strong> — Recent form {_form_label(p2_form)} ({p2_form_num}, {_ordinal(row.get('P2 Form Percentile'))} pct) · Match-day volatility {escape(str(row.get('P2 Volatility Label') or 'Unknown'))} ({p2_vol_num}, {_ordinal(row.get('P2 Volatility Percentile'))} pct) · State confidence {escape(str(row.get('P2 State Conf Label') or 'Unknown'))} ({p2_conf_text})</div>
      <div class="v5-metric-line">Simulator vs Surface Elo <strong>{agreement}</strong> · {gap_text} probability gap</div>

      <div class="v5-why"><strong>Current pricing output</strong></div>
      {_market_output_html(row)}
      <div class="v5-metric-line">Best market <strong>{format_american_odds(market_odds)}</strong> · EV/edge <strong>{format_edge(edge)}</strong></div>
      <div class="v5-why"><strong>Why it stands out:</strong> {explanation}</div>
    </div>
    """.strip()
'''
today.write_text(text[:start] + new_block + text[end:], encoding="utf-8")
print("Applied Today matchup-lab parity without changing model calculations or secondary pages")
