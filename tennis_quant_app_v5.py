
from pathlib import Path
from datetime import date, timedelta
import json
import math

import numpy as np
import pandas as pd
import streamlit as st

from v5_core import logistic, logit, simulate_match, american_from_prob
from v5_live_market import load_market_board, find_match_rows, add_model_pricing, signal_row

BASE = Path(__file__).resolve().parent


# ============================================================
# MODEL / ODDS HELPERS
# ============================================================

def load_ratings(tour):
    return pd.read_csv(BASE / f"v5_{tour.lower()}_ratings.csv", low_memory=False)


def base_probs_from_ratings(df, p1, p2, surface, baseline):
    a = df[(df.player == p1) & (df.surface == surface)]
    b = df[(df.player == p2) & (df.surface == surface)]

    if a.empty or b.empty:
        raise ValueError("Player/surface not found in V5 ratings.")

    a = a.iloc[-1]
    b = b.iloc[-1]

    wa = min(1.0, (a.surface_points + b.surface_points) / 700.0)

    eta_a = (
        logit(baseline[surface])
        + a.serve_global
        - b.return_global
        + 0.55 * wa * (a.serve_surface - b.return_surface)
    )

    eta_b = (
        logit(baseline[surface])
        + b.serve_global
        - a.return_global
        + 0.55 * wa * (b.serve_surface - a.return_surface)
    )

    return logistic(eta_a), logistic(eta_b), a, b


def prob_odds_text(prob):
    odds = american_from_prob(prob)
    return f"{prob:.1%}  |  {odds:+d}"


def american_to_prob(odds):
    if odds is None or pd.isna(odds):
        return np.nan
    odds = float(odds)
    if odds == 0:
        return np.nan
    return 100.0 / (odds + 100.0) if odds > 0 else (-odds) / ((-odds) + 100.0)


def american_to_decimal(odds):
    if odds is None or pd.isna(odds):
        return np.nan
    odds = float(odds)
    if odds == 0:
        return np.nan
    return 1.0 + odds / 100.0 if odds > 0 else 1.0 + 100.0 / abs(odds)


def expected_roi(model_prob, odds):
    dec = american_to_decimal(odds)
    if pd.isna(dec):
        return np.nan
    return float(model_prob) * dec - 1.0


def no_vig_probs(odds_a, odds_b):
    pa = american_to_prob(odds_a)
    pb = american_to_prob(odds_b)
    if pd.isna(pa) or pd.isna(pb) or pa + pb <= 0:
        return np.nan, np.nan
    total = pa + pb
    return pa / total, pb / total


def form_magnitude(value):
    """Absolute magnitude label, separate from relative percentile rank."""
    v = float(value)
    av = abs(v)
    if av < 0.010:
        label = "Neutral"
    elif av < 0.025:
        label = "Slightly Positive" if v > 0 else "Slightly Negative"
    elif av < 0.050:
        label = "Positive" if v > 0 else "Negative"
    else:
        label = "Strong Positive" if v > 0 else "Strong Negative"
    return label


def market_signal(ev, edge, disagreement, confidence):
    """
    Transparent research classification, not a claim of guaranteed profitability.
    REVIEW takes precedence when model disagreement/sample uncertainty is meaningful.
    """
    if pd.isna(ev):
        return "NO PRICE"

    if ev < 0.02:
        return "PASS"

    if confidence < 0.45:
        return "REVIEW"

    if disagreement == "HIGH":
        return "REVIEW"

    if disagreement == "MODERATE" and ev >= 0.04:
        return "REVIEW"

    if edge is not None and not pd.isna(edge):
        if ev >= 0.05 and edge >= 0.025 and disagreement == "LOW":
            return "BET"
        if ev >= 0.02 and edge >= 0.010:
            return "LEAN"
        return "PASS"

    # EV can still be calculated from one sportsbook price even if the opposite
    # price wasn't supplied, but no-vig market edge cannot.
    return "LEAN" if ev >= 0.03 else "PASS"


def make_market_row(
    market,
    selection,
    model_prob,
    odds,
    opposite_odds,
    disagreement,
    confidence,
):
    if odds is None or pd.isna(odds):
        return None

    raw_implied = american_to_prob(odds)
    nv, _ = no_vig_probs(odds, opposite_odds)
    edge = model_prob - nv if not pd.isna(nv) else np.nan
    ev = expected_roi(model_prob, odds)

    return {
        "Market": market,
        "Selection": selection,
        "V5 Probability": model_prob,
        "V5 Fair Odds": american_from_prob(model_prob),
        "Book Odds": int(round(float(odds))),
        "Book Implied %": raw_implied,
        "No-Vig Market %": nv,
        "Probability Edge": edge,
        "Expected ROI": ev,
        "Model Agreement": disagreement,
        "State Confidence": confidence,
        "Signal": market_signal(ev, edge, disagreement, confidence),
    }


# ============================================================
# STREAMLIT APP
# ============================================================

def matchup_lab():

    st.title("Tennis Quant Lab V5 — Bottom-Up Tennis Simulator")
    st.caption(
        "Opponent-adjusted serve/return ratings → current state → "
        "player-day variation → points → games → sets → matches → market pricing."
    )

    summary = {}
    summary_path = BASE / "v5_build_summary.json"
    if summary_path.exists():
        summary = json.loads(summary_path.read_text())

    tour = st.sidebar.selectbox("Tour", ["MEN", "WTA"])
    surface = st.sidebar.selectbox("Surface", ["Hard", "Clay", "Grass"])

    ratings = load_ratings(tour)
    names = sorted(ratings.player.dropna().unique())

    c1, c2 = st.columns(2)
    p1 = c1.selectbox("Player 1", names)
    p2 = c2.selectbox("Player 2", names, index=min(1, len(names) - 1))

    best_of = st.selectbox("Best of", [3, 5], index=0)

    precision = st.selectbox(
        "Simulation Precision",
        ["Fast — 5,000", "Standard — 20,000", "High — 50,000"],
        index=1,
        help=(
            "More simulations reduce Monte Carlo noise. "
            "They do not change the underlying player-strength estimate."
        ),
    )

    simulations = {
        "Fast — 5,000": 5000,
        "Standard — 20,000": 20000,
        "High — 50,000": 50000,
    }[precision]

    baseline = summary.get(tour, {}).get(
        "baseline",
        {"Hard": 0.62, "Clay": 0.62, "Grass": 0.62},
    )

    if st.button("RUN V5 SIMULATION", type="primary"):
        try:
            p1_serve, p2_serve, a, b = base_probs_from_ratings(
                ratings, p1, p2, surface, baseline
            )

            elo_a = (1 - 0.65) * a.elo + 0.65 * a.surface_elo
            elo_b = (1 - 0.65) * b.elo + 0.65 * b.surface_elo
            p_elo = 1 / (1 + 10 ** ((elo_b - elo_a) / 400))

            form_a = float(a.get("form_logit", 0.0))
            form_b = float(b.get("form_logit", 0.0))
            vol_a = float(a.get("day_vol_logit", 0.06))
            vol_b = float(b.get("day_vol_logit", 0.06))

            result = simulate_match(
                p1_serve,
                p2_serve,
                best_of=best_of,
                n=simulations,
                seed=42,
                formA=form_a,
                formB=form_b,
                volA=vol_a,
                volB=vol_b,
                state_variation=True,
            )

            st.session_state["v5_projection"] = {
                "tour": tour,
                "surface": surface,
                "p1": p1,
                "p2": p2,
                "best_of": best_of,
                "precision": precision,
                "simulations": simulations,
                "p1_serve": p1_serve,
                "p2_serve": p2_serve,
                "p_elo": p_elo,
                "a": a.to_dict(),
                "b": b.to_dict(),
                "result": result,
            }

        except Exception as exc:
            st.error(str(exc))

    proj = st.session_state.get("v5_projection")

    if not proj:
        st.info("Run a V5 simulation to create the projection and open the sportsbook market board.")
        return

    # Warn if player selectors changed after the stored simulation.
    if (
        proj["p1"] != p1
        or proj["p2"] != p2
        or proj["surface"] != surface
        or proj["tour"] != tour
        or proj["best_of"] != best_of
    ):
        st.warning(
            "The displayed projection belongs to the previous player/surface selection. "
            "Click RUN V5 SIMULATION to refresh it."
        )

    p1 = proj["p1"]
    p2 = proj["p2"]
    result = proj["result"]
    p1_serve = float(proj["p1_serve"])
    p2_serve = float(proj["p2_serve"])
    p_elo = float(proj["p_elo"])
    a = pd.Series(proj["a"])
    b = pd.Series(proj["b"])

    p1_match = float(result["pA_win"])
    p2_match = 1.0 - p1_match

    # --------------------------------------------------------
    # MATCH PROJECTION
    # --------------------------------------------------------
    st.subheader("Match Projection")

    k1, k2, k3, k4 = st.columns(4)

    k1.metric(
        f"{p1} Win Probability | Fair Odds",
        prob_odds_text(p1_match),
    )
    k2.metric(
        f"{p2} Win Probability | Fair Odds",
        prob_odds_text(p2_match),
    )
    k3.metric(
        "Expected Game Margin",
        f"{result['expected_margin']:+.2f}",
        help=f"Positive = {p1}; negative = {p2}",
    )
    k4.metric(
        "Expected Total Games",
        f"{result['expected_total']:.2f}",
    )

    st.caption(
        "Fair odds are V5 probability translated into American odds. "
        "They are not a separate prediction."
    )

    # --------------------------------------------------------
    # STATE / DIAGNOSTICS
    # --------------------------------------------------------
    st.subheader("Current Form, Volatility & Confidence")

    p1_form = float(a.get("form_logit", 0.0))
    p2_form = float(b.get("form_logit", 0.0))
    p1_fp = float(a.get("form_percentile", 50.0))
    p2_fp = float(b.get("form_percentile", 50.0))
    p1_v = float(a.get("day_vol_logit", 0.06))
    p2_v = float(b.get("day_vol_logit", 0.06))
    p1_vp = float(a.get("vol_percentile", 50.0))
    p2_vp = float(b.get("vol_percentile", 50.0))

    f1, f2, f3, f4 = st.columns(4)

    f1.metric(
        f"{p1} Recent Form",
        form_magnitude(p1_form),
        delta=f"{p1_form:+.3f} | {p1_fp:.0f}th percentile",
        help=(
            "The label reflects absolute magnitude. "
            "The percentile separately shows where that value ranks versus comparable players."
        ),
    )
    f2.metric(
        f"{p1} Match-Day Volatility",
        f"{a.get('volatility_label', 'Average')} — {p1_vp:.0f}th pct",
        delta=f"σ {p1_v:.3f}",
    )
    f3.metric(
        f"{p2} Recent Form",
        form_magnitude(p2_form),
        delta=f"{p2_form:+.3f} | {p2_fp:.0f}th percentile",
    )
    f4.metric(
        f"{p2} Match-Day Volatility",
        f"{b.get('volatility_label', 'Average')} — {p2_vp:.0f}th pct",
        delta=f"σ {p2_v:.3f}",
    )

    p1_conf = float(a.get("state_confidence", 0.0))
    p2_conf = float(b.get("state_confidence", 0.0))
    match_conf = min(p1_conf, p2_conf)

    model_gap = abs(p1_match - p_elo)
    disagreement = (
        "HIGH"
        if model_gap >= 0.12
        else ("MODERATE" if model_gap >= 0.07 else "LOW")
    )

    s1, s2, s3 = st.columns(3)
    s1.metric(
        f"{p1} State Confidence",
        str(a.get("state_confidence_label", "Unknown")),
        f"{p1_conf:.0%} sample confidence",
    )
    s2.metric(
        f"{p2} State Confidence",
        str(b.get("state_confidence_label", "Unknown")),
        f"{p2_conf:.0%} sample confidence",
    )
    s3.metric(
        "Simulator vs Surface Elo",
        disagreement,
        f"{model_gap:.1%} probability gap",
    )

    if disagreement == "HIGH":
        st.warning(
            "High model disagreement: simulator and Surface Elo differ materially. "
            "Market edges are marked REVIEW rather than automatically promoted."
        )
    elif disagreement == "MODERATE":
        st.info(
            "Moderate model disagreement: the structural point model and Surface Elo "
            "are not fully aligned."
        )


    # --------------------------------------------------------
    # AUTOMATED ODDSPAPI SNAPSHOT
    # --------------------------------------------------------
    st.subheader("Automated Market Snapshot")
    live_market_board = load_market_board()
    live_rows = find_match_rows(live_market_board, p1, p2)

    if live_rows.empty:
        st.info(
            "No current OddsPapi snapshot matches this matchup. "
            "This does not affect the V5 projection."
        )
    else:
        priced_live = add_model_pricing(live_rows, result, p1, p2)
        priced_live["Signal"] = priced_live.apply(
            lambda rr: signal_row(
                rr,
                disagreement_level=disagreement,
                state_confidence=match_conf,
            ),
            axis=1,
        )
        actionable_live = priced_live[priced_live["model_probability"].notna()].copy()

        if actionable_live.empty:
            st.info(
                "OddsPapi prices were found, but the available lines are not directly "
                "gradeable from the current simulation output."
            )
        else:
            actionable_live["Market"] = actionable_live["market_group"]
            actionable_live["Selection"] = actionable_live["selection"]
            actionable_live["Line"] = actionable_live["line"]
            actionable_live["Book"] = actionable_live["best_bookmaker"]
            actionable_live["Best Odds"] = actionable_live["best_american_odds"]
            actionable_live["Model Prob"] = actionable_live["model_probability"]
            actionable_live["Fair Odds"] = actionable_live["model_fair_american"]
            actionable_live["Consensus No-Vig"] = actionable_live["consensus_no_vig_prob"]
            actionable_live["Edge"] = actionable_live["edge_vs_consensus"]
            actionable_live["EV"] = actionable_live["expected_value"]

            actionable_live = actionable_live.sort_values(
                ["expected_value","edge_vs_consensus"],
                ascending=False,
                na_position="last",
            )

            st.dataframe(
                actionable_live[
                    [
                        "Signal","Market","Selection","Line","Book","Best Odds",
                        "Model Prob","Fair Odds","Consensus No-Vig","Edge","EV"
                    ]
                ].style.format(
                    {
                        "Line": lambda x: "" if pd.isna(x) else f"{x:+g}",
                        "Best Odds": lambda x: "" if pd.isna(x) else f"{int(x):+d}",
                        "Model Prob": "{:.1%}",
                        "Fair Odds": lambda x: "" if pd.isna(x) else f"{int(round(x)):+d}",
                        "Consensus No-Vig": "{:.1%}",
                        "Edge": "{:+.1%}",
                        "EV": "{:+.1%}",
                    }
                ),
                use_container_width=True,
                hide_index=True,
            )
            books = ", ".join(sorted(set(actionable_live["Book"].dropna().astype(str))))
            st.caption(
                f"Snapshot books represented for this matchup: {books}. "
                "V5 probabilities are generated independently before sportsbook prices are joined."
            )


    # --------------------------------------------------------
    # SPORTSBOOK MARKET BOARD
    # --------------------------------------------------------
    st.subheader("Sportsbook Market Board")
    st.caption(
        "Enter the sportsbook prices you actually have. V5 converts its simulated "
        "probabilities to fair odds, removes vig when both sides are supplied, "
        "calculates probability edge and expected ROI, and assigns a transparent signal."
    )

    with st.expander("Enter sportsbook prices", expanded=True):
        st.markdown("#### Moneyline")
        ml1, ml2 = st.columns(2)

        p1_ml = ml1.number_input(
            f"{p1} ML",
            value=None,
            step=1,
            placeholder="e.g. +102",
            key="v5_p1_ml",
        )
        p2_ml = ml2.number_input(
            f"{p2} ML",
            value=None,
            step=1,
            placeholder="e.g. -134",
            key="v5_p2_ml",
        )

        st.markdown("#### Game Spreads")
        st.caption(
            f"Enter prices for the paired half-game lines. "
            f"Each row is {p1} on the listed line versus {p2} on the opposite line."
        )

        spread_lines = [-6.5, -5.5, -4.5, -3.5, -2.5, -1.5, -0.5, 0.5, 1.5, 2.5, 3.5, 4.5, 5.5, 6.5]
        spread_input = pd.DataFrame({
            f"{p1} Line": spread_lines,
            f"{p1} Odds": [np.nan] * len(spread_lines),
            f"{p2} Line": [-x for x in spread_lines],
            f"{p2} Odds": [np.nan] * len(spread_lines),
        })

        spread_edit = st.data_editor(
            spread_input,
            hide_index=True,
            use_container_width=True,
            disabled=[f"{p1} Line", f"{p2} Line"],
            key=f"spread_editor_{p1}_{p2}",
            column_config={
                f"{p1} Odds": st.column_config.NumberColumn(format="%d"),
                f"{p2} Odds": st.column_config.NumberColumn(format="%d"),
            },
        )

        st.markdown("#### Total Games")
        total_lines = [18.5, 19.5, 20.5, 21.5, 22.5, 23.5, 24.5, 25.5, 26.5]
        total_input = pd.DataFrame({
            "Total": total_lines,
            "Over Odds": [np.nan] * len(total_lines),
            "Under Odds": [np.nan] * len(total_lines),
        })

        total_edit = st.data_editor(
            total_input,
            hide_index=True,
            use_container_width=True,
            disabled=["Total"],
            key=f"total_editor_{p1}_{p2}",
            column_config={
                "Over Odds": st.column_config.NumberColumn(format="%d"),
                "Under Odds": st.column_config.NumberColumn(format="%d"),
            },
        )

    market_rows = []

    # Moneyline
    if p1_ml is not None:
        market_rows.append(
            make_market_row(
                "Moneyline",
                p1,
                p1_match,
                p1_ml,
                p2_ml,
                disagreement,
                p1_conf,
            )
        )
    if p2_ml is not None:
        market_rows.append(
            make_market_row(
                "Moneyline",
                p2,
                p2_match,
                p2_ml,
                p1_ml,
                disagreement,
                p2_conf,
            )
        )

    # Spreads
    for _, row in spread_edit.iterrows():
        line1 = float(row[f"{p1} Line"])
        line2 = float(row[f"{p2} Line"])
        odds1 = row[f"{p1} Odds"]
        odds2 = row[f"{p2} Odds"]

        key1 = f"{line1:+.1f}"
        p_cover_1 = float(result["spread"].get(key1, np.nan))

        # Half-game paired markets have no push, so counterpart probability is complement.
        p_cover_2 = 1.0 - p_cover_1 if not pd.isna(p_cover_1) else np.nan

        if not pd.isna(odds1) and not pd.isna(p_cover_1):
            market_rows.append(
                make_market_row(
                    "Game Spread",
                    f"{p1} {line1:+.1f}",
                    p_cover_1,
                    odds1,
                    odds2,
                    disagreement,
                    p1_conf,
                )
            )

        if not pd.isna(odds2) and not pd.isna(p_cover_2):
            market_rows.append(
                make_market_row(
                    "Game Spread",
                    f"{p2} {line2:+.1f}",
                    p_cover_2,
                    odds2,
                    odds1,
                    disagreement,
                    p2_conf,
                )
            )

    # Totals
    for _, row in total_edit.iterrows():
        line = float(row["Total"])
        over_odds = row["Over Odds"]
        under_odds = row["Under Odds"]

        p_over = float(result["over"].get(str(line), np.nan))
        p_under = 1.0 - p_over if not pd.isna(p_over) else np.nan

        if not pd.isna(over_odds) and not pd.isna(p_over):
            market_rows.append(
                make_market_row(
                    "Total Games",
                    f"Over {line:.1f}",
                    p_over,
                    over_odds,
                    under_odds,
                    disagreement,
                    match_conf,
                )
            )

        if not pd.isna(under_odds) and not pd.isna(p_under):
            market_rows.append(
                make_market_row(
                    "Total Games",
                    f"Under {line:.1f}",
                    p_under,
                    under_odds,
                    over_odds,
                    disagreement,
                    match_conf,
                )
            )

    market_rows = [x for x in market_rows if x is not None]

    if market_rows:
        market_df = pd.DataFrame(market_rows)
        signal_order = {"BET": 0, "LEAN": 1, "REVIEW": 2, "PASS": 3, "NO PRICE": 4}
        market_df["_signal_sort"] = market_df["Signal"].map(signal_order).fillna(9)
        market_df = market_df.sort_values(
            ["_signal_sort", "Expected ROI"],
            ascending=[True, False],
        ).drop(columns="_signal_sort")

        st.markdown("#### V5 +EV / Pricing Output")

        def style_signal(val):
            if val == "BET":
                return "font-weight: 700; background-color: rgba(0, 180, 90, 0.15)"
            if val == "LEAN":
                return "font-weight: 700; background-color: rgba(250, 180, 0, 0.15)"
            if val == "REVIEW":
                return "font-weight: 700; background-color: rgba(50, 120, 255, 0.12)"
            return ""

        styled = (
            market_df.style
            .format({
                "V5 Probability": "{:.1%}",
                "V5 Fair Odds": lambda x: f"{int(x):+d}",
                "Book Odds": lambda x: f"{int(x):+d}",
                "Book Implied %": "{:.1%}",
                "No-Vig Market %": lambda x: "—" if pd.isna(x) else f"{x:.1%}",
                "Probability Edge": lambda x: "—" if pd.isna(x) else f"{x:+.1%}",
                "Expected ROI": "{:+.1%}",
                "State Confidence": "{:.0%}",
            })
            .map(style_signal, subset=["Signal"])
        )

        st.dataframe(
            styled,
            use_container_width=True,
            hide_index=True,
        )

        actionable = market_df[market_df.Signal.isin(["BET", "LEAN", "REVIEW"])].copy()

        if not actionable.empty:
            top = actionable.iloc[0]
            st.markdown("#### Top Current Pricing Signal")

            q1, q2, q3, q4 = st.columns(4)
            q1.metric("Selection", str(top["Selection"]))
            q2.metric(
                "V5 Probability | Fair",
                f"{top['V5 Probability']:.1%} | {int(top['V5 Fair Odds']):+d}",
            )
            q3.metric(
                "Book Price | EV",
                f"{int(top['Book Odds']):+d} | {top['Expected ROI']:+.1%}",
            )
            q4.metric("Signal", str(top["Signal"]))

            if top["Signal"] == "REVIEW":
                st.info(
                    "The price may be attractive versus the V5 simulator, but the "
                    "independent-model agreement and/or player-state confidence is not "
                    "strong enough to promote it as a clean model selection."
                )
        else:
            st.info("None of the entered prices currently clear V5's value thresholds.")

        st.caption(
            "Signal logic is deliberately conservative: BET requires positive EV, "
            "a meaningful no-vig probability edge, LOW model disagreement, and sufficient "
            "state confidence. REVIEW prevents a large simulator/market discrepancy from "
            "being mistaken for an automatic betting edge."
        )
    else:
        st.info(
            "Enter at least one sportsbook price above. Supplying both sides lets V5 "
            "calculate the no-vig market probability; one side alone still allows model EV."
        )

    # --------------------------------------------------------
    # RAW DISTRIBUTION OUTPUTS
    # --------------------------------------------------------
    with st.expander("Detailed V5 Simulation Distribution"):
        st.subheader("Underlying Point Model")
        p1c, p2c, eloc = st.columns(3)

        p1c.metric(f"{p1} Serve-Point Win %", f"{p1_serve:.1%}")
        p2c.metric(f"{p2} Serve-Point Win %", f"{p2_serve:.1%}")
        eloc.metric(
            f"Surface Elo — {p1}",
            prob_odds_text(p_elo),
            help="Independent diagnostic model; not silently blended into V5.",
        )

        st.subheader("Exact Match Score Distribution")
        score_df = pd.DataFrame([
            {
                "Score": score,
                "Probability": probability,
                "Fair Odds": american_from_prob(probability),
            }
            for score, probability in sorted(result["score_probs"].items())
        ])

        st.dataframe(
            score_df.style.format({
                "Probability": "{:.1%}",
                "Fair Odds": lambda x: f"{int(x):+d}",
            }),
            use_container_width=True,
            hide_index=True,
        )

        st.subheader("Game Spread Probabilities")
        spread_df = pd.DataFrame([
            {
                f"{p1} Spread": line,
                "Cover Probability": probability,
                "Fair Odds": american_from_prob(probability),
            }
            for line, probability in result["spread"].items()
        ])

        st.dataframe(
            spread_df.style.format({
                "Cover Probability": "{:.1%}",
                "Fair Odds": lambda x: f"{int(x):+d}",
            }),
            use_container_width=True,
            hide_index=True,
        )

        st.subheader("Total Games Probabilities")
        total_df = pd.DataFrame([
            {
                "Total": f"Over {line}",
                "Over Probability": probability,
                "Fair Odds": american_from_prob(probability),
            }
            for line, probability in result["over"].items()
        ])

        st.dataframe(
            total_df.style.format({
                "Over Probability": "{:.1%}",
                "Fair Odds": lambda x: f"{int(x):+d}",
            }),
            use_container_width=True,
            hide_index=True,
        )

        st.subheader("Additional Simulation Diagnostics")
        d1, d2 = st.columns(2)

        d1.metric(
            "Tiebreak Occurs",
            prob_odds_text(float(result["tiebreak_prob"])),
        )

        diagnostics = {
            "Margin SD": round(float(result["margin_sd"]), 2),
            "Total SD": round(float(result["total_sd"]), 2),
            "Average sampled serve % — Player 1": round(float(result["sampled_serve_A_mean"]) * 100, 2),
            "Average sampled serve % — Player 2": round(float(result["sampled_serve_B_mean"]) * 100, 2),
            "Sampled serve SD — Player 1": round(float(result["sampled_serve_A_sd"]) * 100, 2),
            "Sampled serve SD — Player 2": round(float(result["sampled_serve_B_sd"]) * 100, 2),
            "Simulation precision": proj["precision"],
            "Simulations": proj["simulations"],
        }

        if "sampled_serve_A_p10" in result:
            diagnostics["Player 1 sampled serve 10–90%"] = (
                f"{result['sampled_serve_A_p10']:.1%} to {result['sampled_serve_A_p90']:.1%}"
            )
            diagnostics["Player 2 sampled serve 10–90%"] = (
                f"{result['sampled_serve_B_p10']:.1%} to {result['sampled_serve_B_p90']:.1%}"
            )

        d2.write(diagnostics)

    with st.expander("How to interpret V5 diagnostics"):
        st.markdown("""
**V5 Probability / Fair Odds**  
The simulator's probability and that probability translated into American odds.

**No-Vig Market %**  
The sportsbook's two-sided market after removing the bookmaker margin.

**Probability Edge**  
V5 probability minus the no-vig market probability.

**Expected ROI**  
Expected return per 1 unit staked if the V5 probability were the true probability at the entered sportsbook price.

**Recent Form**  
Opponent-adjusted recent performance relative to expectation. Absolute magnitude and relative percentile are displayed separately.

**Match-Day Volatility**  
Historically learned player-day variation. Percentiles compare the player to the relevant tour/surface population.

**State Confidence**  
How much sample depth supports the player's form/volatility state.

**Simulator vs Surface Elo**  
Independent-model disagreement. A large gap is a REVIEW flag, not proof that the market is wrong.

**Simulation Precision**  
5,000 vs 50,000 simulations changes Monte Carlo noise only. It does not change the underlying player-strength estimate.
""")

    st.divider()
    st.caption(
        "V5 Research Build: sportsbook prices are evaluation inputs only. "
        "They do not feed back into the independent player-strength simulation."
    )





# ============================================================
# TNNS LIVE SLATE PULL
# ============================================================

def _tnns_decimal_to_american(value):
    try:
        d=float(value)
        if d <= 1:
            return np.nan
        if d >= 2:
            return int(round((d-1)*100))
        return int(round(-100/(d-1)))
    except Exception:
        return np.nan

def _tnns_surface(meta):
    text=f"{meta.get('su','')} {meta.get('t','')}".lower()
    if "clay" in text:
        return "Clay"
    if "grass" in text:
        return "Grass"
    return "Hard"

def _tnns_tour(meta):
    d=meta.get("d") or {}
    category=str(d.get("category","")).upper()
    fmt=str(d.get("format","")).upper()
    tours=" ".join(d.get("tour",[]) if isinstance(d.get("tour"),list) else [str(d.get("tour",""))]).upper()

    if "WTA" in category or "WOMEN" in fmt or "WTA" in tours:
        return "WTA"
    return "MEN"

def _tnns_supported(meta):
    """
    V5 currently has ATP, ATP qualifying, Challenger, WTA and WTA125-type history.
    Exclude ITF/UTR from the automatic board until those tours have equivalent
    historical player-state coverage.
    """
    d=meta.get("d") or {}
    category=str(d.get("category","")).upper()
    tours=" ".join(d.get("tour",[]) if isinstance(d.get("tour"),list) else [str(d.get("tour",""))]).upper()

    if "ITF" in category or "ITF" in tours:
        return False
    if "UTR" in category or "UTR" in tours:
        return False
    return any(x in category or x in tours for x in ("ATP","WTA","CHALLENGER"))

def _tnns_extract_matches(payload):
    """
    Actual TNNS /v1/matches schema:
      payload["sids"]      = tournament metadata keyed by sid
      payload["all_matches"] = match rows
      match["p"]           = two player/team objects, name in ["n"]
      match["sid"]         = link to tournament metadata
      match["ka"]          = ds scheduled, dl live, dc completed
      match["od"]["o"]     = two decimal moneyline prices when available
    """
    sids=payload.get("sids") or {}
    all_matches=payload.get("all_matches") or []

    # JSON keys may arrive as strings even though match sid values are numeric.
    sids={str(k):v for k,v in sids.items()}

    out=[]
    seen=set()

    for m in all_matches:
        if not isinstance(m,dict):
            continue

        # Daily Board should load upcoming/live matches, not already completed ones.
        if m.get("ka") not in ("ds","dl"):
            continue

        players=m.get("p")
        if not isinstance(players,list) or len(players) != 2:
            continue

        p1=str((players[0] or {}).get("n","")).strip()
        p2=str((players[1] or {}).get("n","")).strip()
        if not p1 or not p2:
            continue

        # TNNS represents doubles teams as e.g. "Danilina / Kato".
        if "/" in p1 or "/" in p2:
            continue

        meta=sids.get(str(m.get("sid")),{})
        if not meta:
            continue

        if not _tnns_supported(meta):
            continue

        tour=_tnns_tour(meta)
        surface=_tnns_surface(meta)
        tournament=str(meta.get("t","")).replace("Â·","·").strip()

        # TNNS gives decimal odds in od.o. Pull them directly into the Daily Board.
        odds=((m.get("od") or {}).get("o") or [])
        p1_ml=_tnns_decimal_to_american(odds[0]) if len(odds)>=1 else np.nan
        p2_ml=_tnns_decimal_to_american(odds[1]) if len(odds)>=2 else np.nan

        round_name=""
        d_st=m.get("d_st")
        if isinstance(d_st,dict):
            round_name=str(d_st.get("s",""))

        # ATP/WTA qualifiers, Challenger and normal tour events are BO3.
        # Men's Slam main draw can later be promoted to BO5 when TNNS round/status
        # explicitly tells us it is a main-draw men's singles match.
        best_of=3

        key=(str(m.get("k","")),p1.casefold(),p2.casefold())
        if key in seen:
            continue
        seen.add(key)

        out.append({
            "Tournament":tournament,
            "Round":round_name,
            "Tour":tour,
            "Surface":surface,
            "Player 1":p1,
            "Player 2":p2,
            "Best Of":best_of,
            "P1 ML":p1_ml,
            "P2 ML":p2_ml,
            "Start":m.get("start_time_timestamp"),
            "TNNS Match ID":m.get("k"),
            "TNNS Status":m.get("ka"),
        })

    return out
def pull_tnns_slate(target_date):
    """
    Call TNNS using the exact query-string layout captured from Chrome.
    TNNS has returned 403s to semantically equivalent Python-generated URLs,
    so V5 preserves parameter order and percent-encoding from the browser request.
    """
    import json as _json
    import subprocess

    date_str = target_date.strftime("%Y-%m-%d")

    # Exact browser-captured query order:
    # date -> url -> web -> referring_domain -> timezone -> language -> platform
    exact_url = (
        "https://api.tnnslive.com/v1/matches"
        f"?date={date_str}"
        "&url=https%3A%2F%2Fapi.tnnslive.com%2Fv1%2Fmatches"
        "&web=true"
        "&referring_domain=https%3A%2F%2Ftnnslive.com%2F"
        "&timezone=America%2FNew_York"
        "&language=en"
        "&platform=web"
    )

    headers = [
        ("accept", "*/*"),
        ("accept-language", "en-US,en;q=0.9,de-DE;q=0.8,de;q=0.7"),
        ("dnt", "1"),
        ("origin", "https://tnnslive.com"),
        ("priority", "u=1, i"),
        ("referer", "https://tnnslive.com/"),
        ("sec-ch-ua", '"Not=A?Brand";v="99", "Google Chrome";v="151", "Chromium";v="151"'),
        ("sec-ch-ua-mobile", "?0"),
        ("sec-ch-ua-platform", '"Windows"'),
        ("sec-fetch-dest", "empty"),
        ("sec-fetch-mode", "cors"),
        ("sec-fetch-site", "same-site"),
        (
            "user-agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/151.0.0.0 Safari/537.36",
        ),
    ]

    errors = []

    # 1) Windows curl.exe first because the captured request itself is a curl command.
    try:
        cmd = [
            "curl.exe",
            "--silent",
            "--show-error",
            "--location",
            "--fail-with-body",
            "--compressed",
            "--url",
            exact_url,
        ]
        for key, value in headers:
            cmd.extend(["-H", f"{key}: {value}"])

        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=40,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

        body = proc.stdout.strip()

        if proc.returncode == 0 and body:
            payload = _json.loads(body)
            return _tnns_extract_matches(payload), payload

        detail = proc.stderr.strip() or body[:1000]
        errors.append(f"curl.exe returned code {proc.returncode}: {detail}")
    except Exception as exc:
        errors.append(f"curl.exe failed: {exc}")

    # 2) Chrome TLS impersonation using the exact URL.
    try:
        from curl_cffi import requests as cffi_requests

        response = cffi_requests.get(
            exact_url,
            headers={k: v for k, v in headers},
            impersonate="chrome",
            timeout=30,
        )

        if response.status_code == 200:
            payload = response.json()
            return _tnns_extract_matches(payload), payload

        errors.append(
            f"Chrome-impersonated request returned HTTP {response.status_code}: "
            f"{response.text[:500]}"
        )
    except Exception as exc:
        errors.append(f"Chrome-impersonated request failed: {exc}")

    # 3) Ordinary requests only as a final diagnostic fallback.
    try:
        import requests

        response = requests.get(
            exact_url,
            headers={k: v for k, v in headers},
            timeout=30,
        )

        if response.status_code == 200:
            payload = response.json()
            return _tnns_extract_matches(payload), payload

        errors.append(
            f"Standard request returned HTTP {response.status_code}: "
            f"{response.text[:500]}"
        )
    except Exception as exc:
        errors.append(f"Standard request failed: {exc}")

    raise RuntimeError(
        "TNNS rejected the exact browser-captured request. "
        + " | ".join(errors)
    )

# ============================================================
# DAILY BOARD — BATCH SLATE MODE
# ============================================================

DAILY_TEMPLATE_COLUMNS = [
    "Tour",
    "Surface",
    "Player 1",
    "Player 2",
    "Best Of",
    "P1 ML",
    "P2 ML",
    "P1 Spread",
    "P1 Spread Odds",
    "P2 Spread Odds",
    "Total",
    "Over Odds",
    "Under Odds",
]

def _blank_daily_template(rows=20):
    df = pd.DataFrame(index=range(rows), columns=DAILY_TEMPLATE_COLUMNS)
    df["Tour"] = "MEN"
    df["Surface"] = "Hard"
    df["Best Of"] = 3
    return df

def _norm_name(x):
    return " ".join(str(x).strip().split()).casefold()

def _player_lookup(ratings):
    return {_norm_name(x): x for x in ratings.player.dropna().unique()}

def _resolve_player(name, lookup):
    if pd.isna(name) or not str(name).strip():
        return None
    return lookup.get(_norm_name(name))

def _batch_one_match(row, ratings_by_tour, summary, sims):
    tour = str(row.get("Tour", "MEN")).upper().strip()
    if tour not in ("MEN", "WTA"):
        return {"Status": "ERROR", "Note": f"Invalid Tour: {tour}"}

    surface = str(row.get("Surface", "Hard")).title().strip()
    if surface not in ("Hard", "Clay", "Grass"):
        return {"Status": "ERROR", "Note": f"Invalid Surface: {surface}"}

    ratings = ratings_by_tour[tour]
    lookup = _player_lookup(ratings)

    p1 = _resolve_player(row.get("Player 1"), lookup)
    p2 = _resolve_player(row.get("Player 2"), lookup)

    if p1 is None:
        return {"Status": "ERROR", "Note": f"Player 1 not found: {row.get('Player 1')}"}
    if p2 is None:
        return {"Status": "ERROR", "Note": f"Player 2 not found: {row.get('Player 2')}"}
    if p1 == p2:
        return {"Status": "ERROR", "Note": "Players cannot be identical."}

    best_of = int(pd.to_numeric(row.get("Best Of", 3), errors="coerce") or 3)
    if best_of not in (3, 5):
        best_of = 3

    baseline = summary.get(tour, {}).get(
        "baseline", {"Hard": .62, "Clay": .62, "Grass": .62}
    )

    p1_serve, p2_serve, a, b = base_probs_from_ratings(
        ratings, p1, p2, surface, baseline
    )

    elo_a = (1 - .65) * a.elo + .65 * a.surface_elo
    elo_b = (1 - .65) * b.elo + .65 * b.surface_elo
    p_elo = 1 / (1 + 10 ** ((elo_b - elo_a) / 400))

    form_a = float(a.get("form_logit", 0.0))
    form_b = float(b.get("form_logit", 0.0))
    vol_a = float(a.get("day_vol_logit", .06))
    vol_b = float(b.get("day_vol_logit", .06))

    result = simulate_match(
        p1_serve, p2_serve,
        best_of=best_of,
        n=sims,
        seed=42,
        formA=form_a,
        formB=form_b,
        volA=vol_a,
        volB=vol_b,
        state_variation=True,
    )

    p1_match = float(result["pA_win"])
    p2_match = 1 - p1_match

    model_gap = abs(p1_match - p_elo)
    disagreement = (
        "HIGH" if model_gap >= .12
        else ("MODERATE" if model_gap >= .07 else "LOW")
    )

    p1_conf = float(a.get("state_confidence", 0.0))
    p2_conf = float(b.get("state_confidence", 0.0))
    match_conf = min(p1_conf, p2_conf)

    out = {
        "Status": "OK",
        "Tour": tour,
        "Surface": surface,
        "Player 1": p1,
        "Player 2": p2,
        "P1 V5 %": p1_match,
        "P1 Fair": american_from_prob(p1_match),
        "P2 V5 %": p2_match,
        "P2 Fair": american_from_prob(p2_match),
        "Expected Margin": float(result["expected_margin"]),
        "Expected Total": float(result["expected_total"]),
        "Model Gap": model_gap,
        "Agreement": disagreement,
        "P1 State Conf": p1_conf,
        "P2 State Conf": p2_conf,
        "Note": "",
    }

    # Moneyline
    p1_ml = pd.to_numeric(row.get("P1 ML"), errors="coerce")
    p2_ml = pd.to_numeric(row.get("P2 ML"), errors="coerce")
    if not pd.isna(p1_ml):
        nv1, _ = no_vig_probs(p1_ml, p2_ml)
        edge = p1_match - nv1 if not pd.isna(nv1) else np.nan
        ev = expected_roi(p1_match, p1_ml)
        out["P1 ML EV"] = ev
        out["P1 ML Edge"] = edge
        out["P1 ML Signal"] = market_signal(ev, edge, disagreement, p1_conf)
    if not pd.isna(p2_ml):
        nv2, _ = no_vig_probs(p2_ml, p1_ml)
        edge = p2_match - nv2 if not pd.isna(nv2) else np.nan
        ev = expected_roi(p2_match, p2_ml)
        out["P2 ML EV"] = ev
        out["P2 ML Edge"] = edge
        out["P2 ML Signal"] = market_signal(ev, edge, disagreement, p2_conf)

    # Primary spread pair
    p1_spread = pd.to_numeric(row.get("P1 Spread"), errors="coerce")
    p1_sp_odds = pd.to_numeric(row.get("P1 Spread Odds"), errors="coerce")
    p2_sp_odds = pd.to_numeric(row.get("P2 Spread Odds"), errors="coerce")
    if not pd.isna(p1_spread):
        key = f"{float(p1_spread):+.1f}"
        pcover1 = result["spread"].get(key)
        if pcover1 is not None:
            pcover2 = 1 - float(pcover1)
            if not pd.isna(p1_sp_odds):
                nv, _ = no_vig_probs(p1_sp_odds, p2_sp_odds)
                edge = float(pcover1) - nv if not pd.isna(nv) else np.nan
                ev = expected_roi(float(pcover1), p1_sp_odds)
                out["P1 Spread Prob"] = float(pcover1)
                out["P1 Spread EV"] = ev
                out["P1 Spread Signal"] = market_signal(ev, edge, disagreement, p1_conf)
            if not pd.isna(p2_sp_odds):
                nv, _ = no_vig_probs(p2_sp_odds, p1_sp_odds)
                edge = pcover2 - nv if not pd.isna(nv) else np.nan
                ev = expected_roi(pcover2, p2_sp_odds)
                out["P2 Spread Prob"] = pcover2
                out["P2 Spread EV"] = ev
                out["P2 Spread Signal"] = market_signal(ev, edge, disagreement, p2_conf)

    # Primary total pair
    total_line = pd.to_numeric(row.get("Total"), errors="coerce")
    over_odds = pd.to_numeric(row.get("Over Odds"), errors="coerce")
    under_odds = pd.to_numeric(row.get("Under Odds"), errors="coerce")
    if not pd.isna(total_line):
        p_over = result["over"].get(str(float(total_line)))
        if p_over is not None:
            p_under = 1 - float(p_over)
            if not pd.isna(over_odds):
                nv, _ = no_vig_probs(over_odds, under_odds)
                edge = float(p_over) - nv if not pd.isna(nv) else np.nan
                ev = expected_roi(float(p_over), over_odds)
                out["Over Prob"] = float(p_over)
                out["Over EV"] = ev
                out["Over Signal"] = market_signal(ev, edge, disagreement, match_conf)
            if not pd.isna(under_odds):
                nv, _ = no_vig_probs(under_odds, over_odds)
                edge = p_under - nv if not pd.isna(nv) else np.nan
                ev = expected_roi(p_under, under_odds)
                out["Under Prob"] = p_under
                out["Under EV"] = ev
                out["Under Signal"] = market_signal(ev, edge, disagreement, match_conf)

    return out

def daily_board():
    st.title("Tennis Quant Lab V5 — Daily Board")
    st.caption(
        "Batch an entire slate through the same V5 engine. "
        "Use Matchup Lab for deeper one-on-one analysis."
    )

    summary = {}
    summary_path = BASE / "v5_build_summary.json"
    if summary_path.exists():
        summary = json.loads(summary_path.read_text())

    ratings_by_tour = {
        "MEN": load_ratings("MEN"),
        "WTA": load_ratings("WTA"),
    }

    precision = st.selectbox(
        "Batch Simulation Precision",
        ["Fast — 2,000 per match", "Standard — 5,000 per match", "High — 10,000 per match"],
        index=1,
        help="Daily Board uses fewer simulations per match for speed. Shortlisted matches can be rerun at 20k–50k in Matchup Lab."
    )
    sims = {
        "Fast — 2,000 per match": 2000,
        "Standard — 5,000 per match": 5000,
        "High — 10,000 per match": 10000,
    }[precision]

    st.markdown("### Load today's slate")

    source_mode=st.radio(
        "Slate Source",
        ["Pull from TNNS Live","Upload CSV","Manual Entry"],
        horizontal=True,
        index=0,
    )

    slate=None

    if source_mode=="Pull from TNNS Live":
        cdate,cbutton=st.columns([2,1])
        target_date=cdate.date_input(
            "TNNS Date",
            value=date.today(),
            help="The app calls the TNNS matches endpoint for this date."
        )

        if cbutton.button("PULL TNNS SLATE",type="primary",use_container_width=True):
            try:
                with st.spinner("Pulling matches from TNNS Live..."):
                    matches,raw_payload=pull_tnns_slate(target_date)

                if not matches:
                    st.error(
                        "TNNS responded, but no singles matches were recognized. "
                        "Download the raw TNNS response below so the parser can be adjusted without redoing browser developer tools."
                    )
                    st.download_button(
                        "Download Raw TNNS Response",
                        json.dumps(raw_payload,indent=2,default=str).encode("utf-8"),
                        file_name=f"tnns_raw_{target_date}.json",
                        mime="application/json",
                    )
                else:
                    pulled=pd.DataFrame(matches)
                    for c in DAILY_TEMPLATE_COLUMNS:
                        if c not in pulled.columns:
                            pulled[c]=np.nan
                    pulled=pulled[DAILY_TEMPLATE_COLUMNS+([c for c in ["Tournament","Round","Start","TNNS Match ID","TNNS Status"] if c in pulled.columns])]
                    st.session_state["tnns_slate"]=pulled
                    st.success(f"Pulled {len(pulled)} supported singles matches from TNNS Live — including TNNS moneyline prices where available.")

            except Exception as exc:
                st.error(f"TNNS pull failed: {exc}")
                st.caption(
                    "TNNS uses browser/TLS checks. V5 now tries Chrome impersonation first and Windows curl.exe second. "
                    "If the error mentions curl_cffi is unavailable, install it once with: "
                    "python -m pip install curl_cffi"
                )

        slate=st.session_state.get("tnns_slate")
        if slate is None:
            slate=_blank_daily_template()

    elif source_mode=="Upload CSV":
        uploaded=st.file_uploader(
            "Upload CSV",
            type=["csv"],
            help="Use the downloadable template below or a file with matching column names."
        )
        if uploaded is not None:
            try:
                slate=pd.read_csv(uploaded)
                for c in DAILY_TEMPLATE_COLUMNS:
                    if c not in slate.columns:
                        slate[c]=np.nan
                slate=slate[DAILY_TEMPLATE_COLUMNS]
            except Exception as exc:
                st.error(f"Could not read slate CSV: {exc}")
                slate=_blank_daily_template()
        else:
            slate=_blank_daily_template()

    else:
        slate=_blank_daily_template()

    if source_mode=="Pull from TNNS Live" and slate is not None and not slate.empty:
        extra_cols=[c for c in ["Tournament","Round","Start"] if c in slate.columns]
        if extra_cols:
            st.markdown("#### TNNS Matches Found")
            st.caption("ATP, ATP qualifying, Challenger, WTA and WTA125 are loaded. ITF and UTR are intentionally excluded until V5 has equivalent historical state coverage for those tours.")
            show_cols=extra_cols+["Tour","Surface","Player 1","Player 2"]
            st.dataframe(slate[show_cols],use_container_width=True,hide_index=True)

        # The pricing editor only needs the Daily Board input columns.
        for c in DAILY_TEMPLATE_COLUMNS:
            if c not in slate.columns:
                slate[c]=np.nan
        slate=slate[DAILY_TEMPLATE_COLUMNS]

    template_csv = _blank_daily_template(1).to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download Daily Board CSV Template",
        template_csv,
        file_name="v5_daily_board_template.csv",
        mime="text/csv",
    )

    edited = st.data_editor(
        slate,
        num_rows="dynamic",
        hide_index=True,
        use_container_width=True,
        key="daily_board_editor",
        column_config={
            "Tour": st.column_config.SelectboxColumn(options=["MEN","WTA"]),
            "Surface": st.column_config.SelectboxColumn(options=["Hard","Clay","Grass"]),
            "Best Of": st.column_config.SelectboxColumn(options=[3,5]),
        }
    )

    if st.button("RUN ENTIRE DAILY BOARD", type="primary"):
        valid = edited[
            edited["Player 1"].notna()
            & edited["Player 2"].notna()
            & (edited["Player 1"].astype(str).str.strip() != "")
            & (edited["Player 2"].astype(str).str.strip() != "")
        ].copy()

        if valid.empty:
            st.warning("Enter at least one matchup.")
        else:
            # Preflight player-name matching against the V5 ratings database.
            unmatched=[]
            for _,rr in valid.iterrows():
                t=str(rr.get("Tour","MEN")).upper()
                if t not in ratings_by_tour:
                    continue
                lookup=_player_lookup(ratings_by_tour[t])
                for side in ("Player 1","Player 2"):
                    nm=rr.get(side)
                    if nm and _resolve_player(nm,lookup) is None:
                        unmatched.append(str(nm))

            if unmatched:
                st.warning(
                    f"{len(set(unmatched))} TNNS/player names are not an exact V5 database match. "
                    "Those rows will be flagged ERROR so they can be mapped rather than silently guessed."
                )
                st.write(sorted(set(unmatched)))

            results = []
            progress = st.progress(0)
            status = st.empty()

            for j, (_, row) in enumerate(valid.iterrows(), start=1):
                status.write(
                    f"Running {j}/{len(valid)}: "
                    f"{row.get('Player 1')} vs {row.get('Player 2')}"
                )
                try:
                    results.append(_batch_one_match(row, ratings_by_tour, summary, sims))
                except Exception as exc:
                    results.append({
                        "Status":"ERROR",
                        "Player 1":row.get("Player 1"),
                        "Player 2":row.get("Player 2"),
                        "Note":str(exc),
                    })
                progress.progress(j / len(valid))

            status.empty()
            progress.empty()
            board = pd.DataFrame(results)
            st.session_state["v5_daily_results"] = board

    board = st.session_state.get("v5_daily_results")

    if board is not None and not board.empty:
        st.markdown("### Daily Board Results")

        # Compute one consolidated best signal per match.
        signal_cols = [c for c in board.columns if c.endswith("Signal")]
        ev_cols = [c for c in board.columns if c.endswith("EV")]

        if signal_cols:
            priority = {"BET":0,"LEAN":1,"REVIEW":2,"PASS":3,"NO PRICE":4}
            best_signals = []
            for _, r in board.iterrows():
                vals = [(c, r.get(c)) for c in signal_cols if pd.notna(r.get(c))]
                if not vals:
                    best_signals.append("")
                    continue
                vals.sort(key=lambda x: priority.get(x[1], 9))
                best_signals.append(vals[0][1])
            board["Best Signal"] = best_signals

        display_cols = [
            c for c in [
                "Status","Tour","Surface","Player 1","Player 2",
                "P1 V5 %","P1 Fair","P2 V5 %","P2 Fair",
                "Expected Margin","Expected Total","Agreement","Model Gap",
                "P1 ML EV","P1 ML Signal","P2 ML EV","P2 ML Signal",
                "P1 Spread EV","P1 Spread Signal","P2 Spread EV","P2 Spread Signal",
                "Over EV","Over Signal","Under EV","Under Signal",
                "Best Signal","Note"
            ] if c in board.columns
        ]

        shown = board[display_cols].copy()

        fmt = {}
        for c in shown.columns:
            if c.endswith("%") or c.endswith("EV") or c == "Model Gap":
                fmt[c] = "{:.1%}"
            elif c in ("P1 Fair","P2 Fair"):
                fmt[c] = lambda x: f"{int(x):+d}" if pd.notna(x) else ""

        st.dataframe(
            shown.style.format(fmt),
            use_container_width=True,
            hide_index=True
        )

        # Actionable shortlists
        for signal, title in [("BET","BET Shortlist"),("LEAN","LEAN Shortlist"),("REVIEW","REVIEW Queue")]:
            if "Best Signal" in board.columns:
                subset = board[board["Best Signal"] == signal]
                if not subset.empty:
                    st.markdown(f"#### {title}")
                    shortlist_cols = [
                        c for c in [
                            "Player 1","Player 2","P1 V5 %","P2 V5 %",
                            "Expected Margin","Expected Total","Agreement",
                            "P1 ML EV","P1 ML Signal","P2 ML EV","P2 ML Signal",
                            "P1 Spread EV","P1 Spread Signal",
                            "P2 Spread EV","P2 Spread Signal",
                            "Over EV","Over Signal","Under EV","Under Signal",
                        ] if c in subset.columns
                    ]
                    st.dataframe(
                        subset[shortlist_cols].style.format({
                            c:"{:.1%}" for c in shortlist_cols if c.endswith("EV") or c.endswith("%")
                        }),
                        use_container_width=True,
                        hide_index=True
                    )

        csv = board.to_csv(index=False).encode("utf-8")
        st.download_button(
            "Download Daily Board Results",
            csv,
            file_name="v5_daily_board_results.csv",
            mime="text/csv"
        )

        st.caption(
            "Workflow: batch the slate here first, then move only BET/LEAN/REVIEW matches "
            "into Matchup Lab when you want the full spread/total ladder and detailed diagnostics."
        )


def app():
    st.set_page_config(page_title="Tennis Quant Lab V5", layout="wide", page_icon="🎾")
    mode = st.sidebar.radio(
        "V5 Mode",
        ["Daily Board", "Matchup Lab"],
        index=0,
        help="Daily Board batches the slate. Matchup Lab keeps the detailed one-on-one feature."
    )

    if mode == "Daily Board":
        daily_board()
    else:
        matchup_lab()


if __name__ == "__main__":
    app()
