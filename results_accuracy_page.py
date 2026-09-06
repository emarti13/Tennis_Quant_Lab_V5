from pathlib import Path
import json

import numpy as np
import pandas as pd
import streamlit as st

BASE = Path(__file__).resolve().parent
DEFAULT_LEDGER = BASE / "v5_daily_ready" / "frozen_predictions.csv"
PRODUCTION_CANDIDATE_PATH = BASE / "experiments" / "acceptance" / "production_candidate.json"


def _safe_div(a, b):
    return float(a / b) if b else np.nan


def _current_model_version(path=PRODUCTION_CANDIDATE_PATH):
    path = Path(path)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    version = payload.get("version") if isinstance(payload, dict) else None
    return None if not version else str(version)


def filter_current_engine_rows(df, current_model_version):
    if df is None or df.empty or not current_model_version or "model_version" not in df.columns:
        return pd.DataFrame(columns=list(df.columns) if df is not None else [])
    version = df["model_version"].fillna("").astype(str)
    signal = df.get("signal", pd.Series(index=df.index, dtype=object)).fillna("").astype(str).str.upper()
    return df[version.eq(str(current_model_version)) & signal.isin(["BET", "LEAN"])].copy()


def results_ledger_views(df, current_model_version):
    """Return mutually understandable result scopes for the UI.

    current_engine: settled BET/LEAN rows made by the presently promoted model version.
    historical_actionable: settled BET/LEAN rows from every older model version.
    all_settled: every settled modeled market row, including PASS/REVIEW audit observations.
    """
    if df is None or df.empty:
        empty = pd.DataFrame(columns=list(df.columns) if df is not None else [])
        return {"current_engine": empty.copy(), "historical_actionable": empty.copy(), "all_settled": empty.copy()}

    status = df.get("result_status", pd.Series(index=df.index, dtype=object)).fillna("").astype(str).str.upper()
    result = df.get("settled_result", pd.Series(index=df.index, dtype=object)).fillna("").astype(str).str.upper()
    signal = df.get("signal", pd.Series(index=df.index, dtype=object)).fillna("").astype(str).str.upper()
    settled = df[status.eq("SETTLED") & result.isin(["WIN", "LOSS", "PUSH", "VOID"])].copy()
    actionable_mask = signal.loc[settled.index].isin(["BET", "LEAN"])
    actionable = settled[actionable_mask].copy()

    if current_model_version and "model_version" in actionable.columns:
        version = actionable["model_version"].fillna("").astype(str)
        current = actionable[version.eq(str(current_model_version))].copy()
        historical = actionable[~version.eq(str(current_model_version))].copy()
    else:
        current = actionable.iloc[0:0].copy()
        historical = actionable.copy()

    return {
        "current_engine": current,
        "historical_actionable": historical,
        "all_settled": settled,
    }


def load_accuracy_ledger(path=DEFAULT_LEDGER):
    path = Path(path)
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path, low_memory=False)
    for col in ("frozen_at_utc", "start_time_utc", "settled_at_utc"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce", utc=True)
    for col in (
        "model_probability", "edge_vs_consensus", "expected_value",
        "state_confidence", "profit_units", "best_american_odds",
        "model_fair_american", "line",
    ):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def accuracy_metrics(df, *, actionable_only=True):
    if df is None or df.empty:
        return {
            "frozen": 0, "settled": 0, "decisions": 0, "wins": 0,
            "losses": 0, "pushes": 0, "voids": 0, "win_rate": np.nan,
            "units": 0.0, "roi": np.nan,
        }
    status = df.get("result_status", pd.Series(index=df.index, dtype=object)).fillna("").astype(str).str.upper()
    result = df.get("settled_result", pd.Series(index=df.index, dtype=object)).fillna("").astype(str).str.upper()
    settled_mask = status.eq("SETTLED")
    if actionable_only and "signal" in df.columns:
        actionable = df["signal"].fillna("").astype(str).str.upper().isin(["BET", "LEAN"])
        settled_mask = settled_mask & actionable
    decision_mask = settled_mask & result.isin(["WIN", "LOSS"])
    wins = int((decision_mask & result.eq("WIN")).sum())
    losses = int((decision_mask & result.eq("LOSS")).sum())
    decisions = wins + losses
    units = pd.to_numeric(df.loc[decision_mask, "profit_units"], errors="coerce").sum() if "profit_units" in df.columns else 0.0
    return {
        "frozen": int(len(df)),
        "settled": int(settled_mask.sum()),
        "decisions": decisions,
        "wins": wins,
        "losses": losses,
        "pushes": int((settled_mask & result.eq("PUSH")).sum()),
        "voids": int((settled_mask & result.eq("VOID")).sum()),
        "win_rate": _safe_div(wins, decisions),
        "units": float(units),
        "roi": _safe_div(units, decisions),
    }


def _performance_table(decisions, group_col, label):
    if decisions.empty or group_col not in decisions.columns:
        return pd.DataFrame()
    rows = []
    for key, g in decisions.groupby(group_col, dropna=False):
        result = g["settled_result"].astype(str).str.upper()
        wins = int((result == "WIN").sum())
        losses = int((result == "LOSS").sum())
        n = wins + losses
        units = pd.to_numeric(g["profit_units"], errors="coerce").sum()
        rows.append({
            label: key,
            "Decisions": n,
            "Wins": wins,
            "Losses": losses,
            "Win Rate": _safe_div(wins, n),
            "Units": units,
            "ROI": _safe_div(units, n),
            "Avg Model Edge": pd.to_numeric(g.get("edge_vs_consensus"), errors="coerce").mean(),
            "Avg Model EV": pd.to_numeric(g.get("expected_value"), errors="coerce").mean(),
        })
    return pd.DataFrame(rows).sort_values(["Decisions", "ROI"], ascending=[False, False])


def _decision_rows(df):
    result = df.get("settled_result", pd.Series(index=df.index, dtype=object)).fillna("").astype(str).str.upper()
    status = df.get("result_status", pd.Series(index=df.index, dtype=object)).fillna("").astype(str).str.upper()
    signal = df.get("signal", pd.Series(index=df.index, dtype=object)).fillna("").astype(str).str.upper()
    return df[status.eq("SETTLED") & result.isin(["WIN", "LOSS"]) & signal.isin(["BET", "LEAN"])].copy()


def _display_ledger(frame):
    if frame is None or frame.empty:
        st.info("No rows are available in this result scope yet.")
        return
    display_cols = [
        c for c in [
            "settled_at_utc", "start_time_utc", "model_version", "selected_model_candidate", "selected_score_candidate",
            "tournament", "tour_v5", "surface", "resolved_player1", "resolved_player2", "market_group", "selection", "line",
            "model_probability", "model_fair_american", "best_bookmaker", "best_american_odds",
            "edge_vs_consensus", "expected_value", "signal", "result_winner", "result_loser",
            "result_score", "settled_result", "profit_units",
        ] if c in frame.columns
    ]
    sort_col = "settled_at_utc" if "settled_at_utc" in frame.columns else None
    shown = frame.sort_values(sort_col, ascending=False) if sort_col else frame.copy()
    st.dataframe(
        shown[display_cols].style.format({
            "model_probability": "{:.1%}",
            "edge_vs_consensus": "{:+.1%}",
            "expected_value": "{:+.1%}",
            "profit_units": "{:+.2f}",
            "model_fair_american": "{:+.0f}",
            "best_american_odds": "{:+.0f}",
        }),
        use_container_width=True,
        hide_index=True,
    )


def render_results_accuracy(ledger_path=DEFAULT_LEDGER):
    st.title("Results & Accuracy")
    st.caption(
        "Frozen pre-match V5 predictions only. Results are settled automatically from "
        "TennisMyLife and the original model probabilities and sportsbook prices are never rewritten."
    )

    df = load_accuracy_ledger(ledger_path)
    if df.empty:
        st.info("No frozen predictions have been logged yet.")
        return

    current_version = _current_model_version()
    views = results_ledger_views(df, current_version)
    current_df = views["current_engine"]
    current_metrics = accuracy_metrics(current_df)
    historical_metrics = accuracy_metrics(df)
    use_current = current_metrics["decisions"] > 0
    headline = current_metrics if use_current else historical_metrics

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Current Engine Decisions" if use_current else "Recommended Decisions", f"{headline['decisions']:,}")
    c2.metric(
        "Current Engine Win Rate" if use_current else "Recommended Win Rate",
        "—" if pd.isna(headline["win_rate"]) else f"{headline['win_rate']:.1%}",
        help="WIN/(WIN+LOSS). Pushes and voids are excluded.",
    )
    c3.metric(
        "Current Engine ROI" if use_current else "Recommended ROI",
        "—" if pd.isna(headline["roi"]) else f"{headline['roi']:+.1%}",
        help="Profit units divided by settled WIN/LOSS recommendations. Pushes and voids are excluded.",
    )
    c4.metric("Units", f"{headline['units']:+.2f}")

    if use_current:
        st.caption(
            f"Current full-context engine {current_version}: {headline['wins']}-{headline['losses']} across "
            f"{headline['decisions']} settled BET/LEAN recommendations. Historical recommendation results are retained below for audit."
        )
    else:
        st.caption(
            f"Recommended settled: {headline['settled']:,} • Recommended decisions: {headline['decisions']:,}. "
            "Headline performance includes BET + LEAN only; PASS and REVIEW are audit observations, not recommendations."
        )

    st.info(
        "The thousands of stored rows are not thousands of recommendations. They include alternate spreads/totals and PASS/REVIEW model observations. "
        "The current-engine record below uses only settled BET/LEAN rows produced by the presently promoted model version."
    )

    decisions = _decision_rows(current_df if use_current else df)
    scope_label = "Current Engine" if use_current else "Recommended"

    st.subheader(f"{scope_label} Performance by Signal")
    perf_signal = _performance_table(decisions, "signal", "Signal")
    if perf_signal.empty:
        st.info("Performance tables populate after settled WIN/LOSS decisions are available.")
    else:
        st.dataframe(
            perf_signal.style.format({
                "Win Rate": "{:.1%}", "Units": "{:+.2f}", "ROI": "{:+.1%}",
                "Avg Model Edge": "{:+.1%}", "Avg Model EV": "{:+.1%}",
            }),
            use_container_width=True,
            hide_index=True,
        )

    st.subheader(f"{scope_label} Performance by Market")
    perf_market = _performance_table(decisions, "market_group", "Market")
    if not perf_market.empty:
        st.dataframe(
            perf_market.style.format({
                "Win Rate": "{:.1%}", "Units": "{:+.2f}", "ROI": "{:+.1%}",
                "Avg Model Edge": "{:+.1%}", "Avg Model EV": "{:+.1%}",
            }),
            use_container_width=True,
            hide_index=True,
        )

    st.subheader("Calibration")
    calibration = decisions[pd.to_numeric(decisions.get("model_probability"), errors="coerce").notna()].copy()
    if len(calibration) >= 20:
        calibration["actual"] = (calibration["settled_result"].astype(str).str.upper() == "WIN").astype(int)
        calibration["model_probability"] = pd.to_numeric(calibration["model_probability"], errors="coerce")
        calibration["bucket"] = pd.cut(
            calibration["model_probability"],
            bins=[0, .4, .45, .5, .55, .6, .65, .7, .75, .8, 1.0],
            include_lowest=True,
        )
        cal = calibration.groupby("bucket", observed=True).agg(
            N=("actual", "size"),
            Avg_Prediction=("model_probability", "mean"),
            Actual_Win_Rate=("actual", "mean"),
        ).reset_index()
        cal["Calibration_Error"] = cal["Actual_Win_Rate"] - cal["Avg_Prediction"]
        st.dataframe(
            cal.style.format({
                "Avg_Prediction": "{:.1%}",
                "Actual_Win_Rate": "{:.1%}",
                "Calibration_Error": "{:+.1%}",
            }),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info(f"Calibration table begins at 20 WIN/LOSS decisions in this scope. Current: {len(calibration)}.")

    st.subheader("Current Engine Settled Recommendations")
    st.caption(
        f"Only settled BET/LEAN rows from {current_version or 'the current promoted model'} are shown here. "
        f"Rows in this table: {len(views['current_engine'])}."
    )
    _display_ledger(views["current_engine"])

    with st.expander(f"Legacy BET + LEAN recommendations ({len(views['historical_actionable'])})", expanded=False):
        st.caption("These are real historical recommendations from older V5 generations. They are preserved, but they do not measure the current engine.")
        _display_ledger(views["historical_actionable"])

    with st.expander(f"All settled model-market rows — audit only ({len(views['all_settled'])})", expanded=False):
        st.caption(
            "This is the large table: every settled modeled market row, including PASS/REVIEW and alternate lines. "
            "It is diagnostic evidence only and is intentionally excluded from the current-engine recommendation record."
        )
        _display_ledger(views["all_settled"])
