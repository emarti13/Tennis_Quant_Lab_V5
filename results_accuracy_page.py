from pathlib import Path
import json

import numpy as np
import pandas as pd
import streamlit as st

from v5_fixture_accuracy import fixture_accuracy_metrics, fixture_accuracy_records
from v5_results_reset import filter_since_reset, load_reset_timestamp

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
    """Return market-level audit scopes for the active results epoch only."""
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
        "model_probability", "full_context_probability_p1", "edge_vs_consensus", "expected_value",
        "expected_margin", "expected_total", "winner_games", "loser_games",
        "state_confidence", "profit_units", "best_american_odds",
        "model_fair_american", "line",
    ):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    try:
        is_production_ledger = path.resolve() == DEFAULT_LEDGER.resolve()
    except OSError:
        is_production_ledger = path == DEFAULT_LEDGER
    if not is_production_ledger:
        return df
    reset_at = load_reset_timestamp()
    return filter_since_reset(
        df,
        reset_at,
        timestamp_columns=("frozen_at_utc", "snapshot_utc", "start_time_utc"),
    )


def accuracy_metrics(df, *, actionable_only=True):
    """Legacy market-outcome metric helper retained for audit compatibility."""
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


def fixture_headline_metrics(records):
    """Public UI helper: headline accuracy is one observation per settled fixture."""
    return fixture_accuracy_metrics(records)


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


def _display_fixture_accuracy(records):
    if records is None or records.empty:
        st.info("No settled fixture forecasts are available yet.")
        return
    columns = [
        c for c in [
            "settled_at_utc", "tournament", "tour", "surface", "player1", "player2",
            "p1_probability", "predicted_winner", "actual_winner", "winner_correct",
            "expected_margin", "actual_margin", "abs_margin_error",
            "expected_total", "actual_total", "abs_total_error", "result_score",
        ] if c in records.columns
    ]
    st.dataframe(
        records[columns].style.format({
            "p1_probability": "{:.1%}",
            "expected_margin": "{:+.2f}",
            "actual_margin": "{:+.2f}",
            "abs_margin_error": "{:.2f}",
            "expected_total": "{:.2f}",
            "actual_total": "{:.0f}",
            "abs_total_error": "{:.2f}",
        }),
        use_container_width=True,
        hide_index=True,
    )


def render_results_accuracy(ledger_path=DEFAULT_LEDGER):
    st.title("Results & Accuracy")
    reset_at = load_reset_timestamp()
    reset_text = "" if reset_at is None else f" Active production epoch: {reset_at.strftime('%Y-%m-%d %H:%M UTC')}."
    st.caption(
        "One frozen pre-match forecast per settled fixture. This page grades V5's tennis prediction — "
        "winner probability, game margin and total games — independently of which market became the official bet." + reset_text
    )

    df = load_accuracy_ledger(ledger_path)
    if df.empty:
        st.info("No post-reset frozen predictions have settled yet.")
        return

    fixtures = fixture_accuracy_records(df)
    headline = fixture_headline_metrics(fixtures)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Settled fixtures", f"{headline['settled_fixtures']:,}")
    c2.metric("Winner accuracy", "—" if pd.isna(headline["winner_accuracy"]) else f"{headline['winner_accuracy']:.1%}")
    c3.metric("Brier score", "—" if pd.isna(headline["brier_score"]) else f"{headline['brier_score']:.3f}")
    c4.metric("Margin MAE", "—" if pd.isna(headline["margin_mae"]) else f"{headline['margin_mae']:.2f} games")
    c5.metric("Total MAE", "—" if pd.isna(headline["total_mae"]) else f"{headline['total_mae']:.2f} games")

    st.info(
        "Each match counts once here even though the frozen ledger contains moneyline, spread and total rows. "
        "Betting ROI and official recommendation results belong on Performance, not in these headline accuracy metrics."
    )

    st.subheader("Fixture forecast results")
    _display_fixture_accuracy(fixtures)

    st.subheader("Match-winner calibration")
    calibration = fixtures[
        pd.to_numeric(fixtures.get("p1_probability"), errors="coerce").notna()
        & pd.to_numeric(fixtures.get("actual_p1_win"), errors="coerce").notna()
    ].copy() if not fixtures.empty else pd.DataFrame()
    if len(calibration) >= 20:
        calibration["bucket"] = pd.cut(
            pd.to_numeric(calibration["p1_probability"], errors="coerce"),
            bins=[0, .4, .45, .5, .55, .6, .65, .7, .75, .8, 1.0],
            include_lowest=True,
        )
        cal = calibration.groupby("bucket", observed=True).agg(
            N=("actual_p1_win", "size"),
            Avg_Prediction=("p1_probability", "mean"),
            Actual_P1_Win_Rate=("actual_p1_win", "mean"),
        ).reset_index()
        cal["Calibration_Error"] = cal["Actual_P1_Win_Rate"] - cal["Avg_Prediction"]
        st.dataframe(
            cal.style.format({
                "Avg_Prediction": "{:.1%}",
                "Actual_P1_Win_Rate": "{:.1%}",
                "Calibration_Error": "{:+.1%}",
            }),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info(f"Calibration table begins at 20 settled fixture forecasts. Current: {len(calibration)}.")

    current_version = _current_model_version()
    views = results_ledger_views(df, current_version)
    with st.expander("Market-level settlement audit — active epoch only", expanded=False):
        st.caption(
            "These rows preserve market settlement evidence from the current production epoch only. "
            "Older raw history remains stored outside this tab for research/audit use."
        )
        current_df = views["current_engine"]
        decisions = _decision_rows(current_df if not current_df.empty else df)
        perf_signal = _performance_table(decisions, "signal", "Signal")
        if not perf_signal.empty:
            st.dataframe(
                perf_signal.style.format({
                    "Win Rate": "{:.1%}", "Units": "{:+.2f}", "ROI": "{:+.1%}",
                    "Avg Model Edge": "{:+.1%}", "Avg Model EV": "{:+.1%}",
                }),
                use_container_width=True,
                hide_index=True,
            )
        _display_ledger(views["all_settled"])
