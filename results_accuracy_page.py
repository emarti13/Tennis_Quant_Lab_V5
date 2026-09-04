from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

BASE = Path(__file__).resolve().parent
DEFAULT_LEDGER = BASE / "v5_daily_ready" / "frozen_predictions.csv"


def _safe_div(a, b):
    return float(a / b) if b else np.nan


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

    metrics = accuracy_metrics(df)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Frozen Markets", f"{metrics['frozen']:,}")
    c2.metric(
        "Recommended Win Rate",
        "—" if pd.isna(metrics["win_rate"]) else f"{metrics['win_rate']:.1%}",
        help="WIN/(WIN+LOSS). Pushes and voids are excluded.",
    )
    c3.metric(
        "Recommended ROI",
        "—" if pd.isna(metrics["roi"]) else f"{metrics['roi']:+.1%}",
        help="Profit units divided by settled WIN/LOSS decisions. Pushes and voids are excluded.",
    )
    c4.metric("Units", f"{metrics['units']:+.2f}")

    st.caption(
        f"Recommended settled: {metrics['settled']:,} • Recommended decisions: {metrics['decisions']:,} • "
        f"Pushes: {metrics['pushes']:,} • Voids: {metrics['voids']:,}. "
        "Headline performance includes BET + LEAN only; PASS and REVIEW remain visible for audit but are not treated as recommendations."
    )
    st.info(
        "Frozen historical predictions are preserved exactly as they were made. Model upgrades do not retroactively rewrite old live predictions; "
        "doing so would contaminate out-of-sample performance. Historical evaluation of a newer engine belongs in a separate time-safe backtest."
    )

    result = df.get("settled_result", pd.Series(index=df.index, dtype=object)).fillna("").astype(str).str.upper()
    status = df.get("result_status", pd.Series(index=df.index, dtype=object)).fillna("").astype(str).str.upper()
    actionable_signal = df.get("signal", pd.Series(index=df.index, dtype=object)).fillna("").astype(str).str.upper().isin(["BET", "LEAN"])
    decisions = df[status.eq("SETTLED") & result.isin(["WIN", "LOSS"]) & actionable_signal].copy()

    st.subheader("Recommended Performance by Signal")
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

    st.subheader("Recommended Performance by Market")
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
        st.info(f"Calibration table begins at 20 WIN/LOSS decisions. Current: {len(calibration)}.")

    all_metrics = accuracy_metrics(df, actionable_only=False)
    with st.expander("All settled model-market rows (audit only)", expanded=False):
        st.caption(
            "This includes PASS and REVIEW observations. These rows are useful for calibration/audit and must not be interpreted as wagers or recommendations."
        )
        st.write({
            "settled_rows": all_metrics["settled"],
            "win_loss_decisions": all_metrics["decisions"],
            "wins": all_metrics["wins"],
            "losses": all_metrics["losses"],
            "units_if_every_row_were_bet": all_metrics["units"],
        })

    st.subheader("Settled Prediction Ledger")
    settled = df[status.eq("SETTLED")].copy()
    if settled.empty:
        st.info("No predictions have settled yet.")
    else:
        display_cols = [
            c for c in [
                "settled_at_utc", "start_time_utc", "tournament", "tour_v5", "surface",
                "resolved_player1", "resolved_player2", "market_group", "selection", "line",
                "model_probability", "model_fair_american", "best_bookmaker", "best_american_odds",
                "edge_vs_consensus", "expected_value", "signal", "result_winner", "result_loser",
                "result_score", "settled_result", "profit_units",
            ] if c in settled.columns
        ]
        st.dataframe(
            settled.sort_values("settled_at_utc", ascending=False)[display_cols].style.format({
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
