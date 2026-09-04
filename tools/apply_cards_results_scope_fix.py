from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"Expected source block not found in {path}: {old[:120]!r}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


def replace_all(path: str, old: str, new: str, expected: int) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count != expected:
        raise SystemExit(f"Expected {expected} occurrences in {path}, found {count}: {old[:120]!r}")
    p.write_text(text.replace(old, new), encoding="utf-8")


# Today match cards: bypass Markdown parsing entirely.
replace_once(
    "v5_ui_today.py",
    'def _render_card_action(st_module, row: pd.Series, on_select: Callable[[Any], None] | None) -> None:\n',
    '''def _render_match_card(st_module, row: pd.Series) -> None:\n    card = match_card_html(row)\n    if hasattr(st_module, "html"):\n        st_module.html(card)\n    else:\n        # Compatibility for lightweight test adapters / older Streamlit only.\n        st_module.markdown(card, unsafe_allow_html=True)\n\n\ndef _render_card_action(st_module, row: pd.Series, on_select: Callable[[Any], None] | None) -> None:\n''',
)
replace_all(
    "v5_ui_today.py",
    'st_module.markdown(match_card_html(row), unsafe_allow_html=True)',
    '_render_match_card(st_module, row)',
    expected=3,
)

# Results page: headline performance is recommendations made (BET/LEAN), not PASS/REVIEW audit rows.
replace_once(
    "results_accuracy_page.py",
    'def accuracy_metrics(df):\n',
    'def accuracy_metrics(df, *, actionable_only=True):\n',
)
replace_once(
    "results_accuracy_page.py",
    '    settled_mask = status.eq("SETTLED")\n    decision_mask = settled_mask & result.isin(["WIN", "LOSS"])\n',
    '''    settled_mask = status.eq("SETTLED")\n    if actionable_only and "signal" in df.columns:\n        actionable = df["signal"].fillna("").astype(str).str.upper().isin(["BET", "LEAN"])\n        settled_mask = settled_mask & actionable\n    decision_mask = settled_mask & result.isin(["WIN", "LOSS"])\n''',
)
replace_once(
    "results_accuracy_page.py",
    '    c1.metric("Frozen Markets", f"{metrics[\'frozen\']:,}")\n',
    '    c1.metric("Frozen Markets", f"{metrics[\'frozen\']:,}")\n',
)
replace_once(
    "results_accuracy_page.py",
    '        "Decision Win Rate",\n',
    '        "Recommended Win Rate",\n',
)
replace_once(
    "results_accuracy_page.py",
    '        "Tracked ROI",\n',
    '        "Recommended ROI",\n',
)
replace_once(
    "results_accuracy_page.py",
    '    st.caption(\n        f"Settled: {metrics[\'settled\']:,} • Decisions: {metrics[\'decisions\']:,} • "\n        f"Pushes: {metrics[\'pushes\']:,} • Voids: {metrics[\'voids\']:,} • "\n        f"Open: {metrics[\'frozen\'] - metrics[\'settled\']:,}"\n    )\n',
    '''    st.caption(\n        f"Recommended settled: {metrics['settled']:,} • Recommended decisions: {metrics['decisions']:,} • "\n        f"Pushes: {metrics['pushes']:,} • Voids: {metrics['voids']:,}. "\n        "Headline performance includes BET + LEAN only; PASS and REVIEW remain visible for audit but are not treated as recommendations."\n    )\n    st.info(\n        "Frozen historical predictions are preserved exactly as they were made. Model upgrades do not retroactively rewrite old live predictions; "\n        "doing so would contaminate out-of-sample performance. Historical evaluation of a newer engine belongs in a separate time-safe backtest."\n    )\n''',
)
replace_once(
    "results_accuracy_page.py",
    '    decisions = df[status.eq("SETTLED") & result.isin(["WIN", "LOSS"])].copy()\n',
    '''    actionable_signal = df.get("signal", pd.Series(index=df.index, dtype=object)).fillna("").astype(str).str.upper().isin(["BET", "LEAN"])\n    decisions = df[status.eq("SETTLED") & result.isin(["WIN", "LOSS"]) & actionable_signal].copy()\n''',
)
replace_once(
    "results_accuracy_page.py",
    '    st.subheader("Performance by Signal")\n',
    '    st.subheader("Recommended Performance by Signal")\n',
)
replace_once(
    "results_accuracy_page.py",
    '    st.subheader("Performance by Market")\n',
    '    st.subheader("Recommended Performance by Market")\n',
)
replace_once(
    "results_accuracy_page.py",
    '    st.subheader("Settled Prediction Ledger")\n',
    '''    all_metrics = accuracy_metrics(df, actionable_only=False)\n    with st.expander("All settled model-market rows (audit only)", expanded=False):\n        st.caption(\n            "This includes PASS and REVIEW observations. These rows are useful for calibration/audit and must not be interpreted as wagers or recommendations."\n        )\n        st.write({\n            "settled_rows": all_metrics["settled"],\n            "win_loss_decisions": all_metrics["decisions"],\n            "wins": all_metrics["wins"],\n            "losses": all_metrics["losses"],\n            "units_if_every_row_were_bet": all_metrics["units"],\n        })\n\n    st.subheader("Settled Prediction Ledger")\n''',
)

# Performance audit keeps raw evidence but adds recommendation-only summaries.
replace_once(
    "diagnose_v5_settled_performance.py",
    'def settled_performance_report(frame: pd.DataFrame) -> dict:\n    settled = _clean_settled(frame)\n    report = {\n        "settled_rows_after_dedupe": int(len(settled)),\n        "raw_markets": _raw_summary(settled),\n        "fixture_clusters": _fixture_summary(settled),\n',
    '''def settled_performance_report(frame: pd.DataFrame) -> dict:\n    settled = _clean_settled(frame)\n    signal = settled.get("signal", pd.Series(index=settled.index, dtype=object)).fillna("").astype(str).str.upper()\n    actionable = settled[signal.isin(["BET", "LEAN"])].copy()\n    report = {\n        "settled_rows_after_dedupe": int(len(settled)),\n        "raw_markets": _raw_summary(settled),\n        "fixture_clusters": _fixture_summary(settled),\n        "actionable_markets": _raw_summary(actionable),\n        "actionable_fixture_clusters": _fixture_summary(actionable),\n''',
)

# New Performance UI defaults to recommendation-only report, with backward-compatible fallback.
replace_once(
    "v5_ui_performance.py",
    '    raw = report.get("raw_markets") or {}\n    fixtures = report.get("fixture_clusters") or {}\n',
    '''    raw = report.get("actionable_markets") or report.get("raw_markets") or {}\n    fixtures = report.get("actionable_fixture_clusters") or report.get("fixture_clusters") or {}\n''',
)
replace_once(
    "v5_ui_performance.py",
    '        "market_label": "Market results",\n        "fixture_label": "Independent fixtures",\n',
    '        "market_label": "Recommended market results",\n        "fixture_label": "Recommended fixtures",\n',
)
replace_once(
    "v5_ui_performance.py",
    "        '<div class=\"v5-subtitle\">Market-level results and independent fixture evidence are reported separately.</div>',\n",
    "        '<div class=\"v5-subtitle\">BET + LEAN results are the headline. PASS / REVIEW rows remain audit evidence and are not counted as recommendations.</div>',\n",
)
replace_once(
    "v5_ui_performance.py",
    '    columns[0].metric("Market record", headline["market_record"])\n',
    '    columns[0].metric("Recommended record", headline["market_record"])\n',
)

print("Applied cards/results scope fix")
