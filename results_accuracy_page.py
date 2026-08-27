
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

from prediction_store import PredictionStore


def _safe_div(a, b):
    return float(a / b) if b else np.nan


def render_results_accuracy(db_path="v5_predictions.sqlite3"):
    st.title("Results & Accuracy")
    st.caption(
        "Frozen V5 predictions only. This page is designed to prevent hindsight "
        "editing and to measure actual out-of-sample performance."
    )

    store = PredictionStore(db_path)
    df = store.predictions_df()

    if df.empty:
        st.info("No frozen predictions have been logged yet.")
        return

    df["created_at_utc"] = pd.to_datetime(df["created_at_utc"], errors="coerce")
    df["start_time_utc"] = pd.to_datetime(df["start_time_utc"], errors="coerce")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Frozen Predictions", f"{len(df):,}")

    settled = df[df.result_status == "SETTLED"].copy()
    wins = int((settled.settled_result == "WIN").sum())
    losses = int((settled.settled_result == "LOSS").sum())
    decisions = wins + losses

    c2.metric(
        "Win Rate",
        "—" if not decisions else f"{wins / decisions:.1%}",
    )

    units = pd.to_numeric(settled.profit_units, errors="coerce").sum()
    risked = int(settled.profit_units.notna().sum())
    roi = _safe_div(units, risked)
    c3.metric("Tracked ROI", "—" if pd.isna(roi) else f"{roi:+.1%}")
    c4.metric("Units", f"{units:+.2f}")

    st.subheader("Performance by Signal")
    if not settled.empty:
        grouped = []
        for signal, g in settled.groupby("signal", dropna=False):
            gw = int((g.settled_result == "WIN").sum())
            gl = int((g.settled_result == "LOSS").sum())
            n = gw + gl
            u = pd.to_numeric(g.profit_units, errors="coerce").sum()
            grouped.append({
                "Signal": signal,
                "N": len(g),
                "Decisions": n,
                "Win Rate": _safe_div(gw, n),
                "Units": u,
                "ROI": _safe_div(u, int(g.profit_units.notna().sum())),
                "Avg Model Edge": pd.to_numeric(
                    g.probability_edge, errors="coerce"
                ).mean(),
                "Avg Model EV": pd.to_numeric(
                    g.expected_roi, errors="coerce"
                ).mean(),
                "Avg CLV (prob)": pd.to_numeric(
                    g.clv_probability, errors="coerce"
                ).mean(),
            })

        perf = pd.DataFrame(grouped)
        st.dataframe(
            perf.style.format({
                "Win Rate": "{:.1%}",
                "Units": "{:+.2f}",
                "ROI": "{:+.1%}",
                "Avg Model Edge": "{:+.1%}",
                "Avg Model EV": "{:+.1%}",
                "Avg CLV (prob)": "{:+.1%}",
            }),
            use_container_width=True,
            hide_index=True,
        )

    st.subheader("Calibration")
    calibration = df[
        df.model_probability.notna()
        & df.settled_result.isin(["WIN", "LOSS"])
    ].copy()

    if len(calibration) >= 20:
        calibration["actual"] = (calibration.settled_result == "WIN").astype(int)
        calibration["bucket"] = pd.cut(
            calibration.model_probability,
            bins=[0, .4, .45, .5, .55, .6, .65, .7, .75, .8, 1.0],
            include_lowest=True,
        )
        cal = calibration.groupby("bucket", observed=True).agg(
            N=("actual", "size"),
            Avg_Prediction=("model_probability", "mean"),
            Actual_Win_Rate=("actual", "mean"),
        ).reset_index()
        cal["Calibration_Error"] = (
            cal.Actual_Win_Rate - cal.Avg_Prediction
        )
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
        st.info("Calibration table begins after at least 20 settled predictions.")

    st.subheader("Prediction Ledger")
    cols = [
        c for c in [
            "created_at_utc",
            "fixture_id",
            "tour",
            "tournament",
            "player1",
            "player2",
            "market_type",
            "selection",
            "line",
            "model_probability",
            "model_fair_odds",
            "bookmaker",
            "book_odds",
            "probability_edge",
            "expected_roi",
            "agreement",
            "state_confidence",
            "signal",
            "result_status",
            "settled_result",
            "profit_units",
            "closing_odds",
            "clv_probability",
        ] if c in df.columns
    ]
    st.dataframe(
        df[cols].style.format({
            "model_probability": "{:.1%}",
            "probability_edge": "{:+.1%}",
            "expected_roi": "{:+.1%}",
            "state_confidence": "{:.0%}",
            "profit_units": "{:+.2f}",
            "clv_probability": "{:+.1%}",
        }),
        use_container_width=True,
        hide_index=True,
    )
