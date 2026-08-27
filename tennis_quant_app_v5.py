
from pathlib import Path
import math, json
import numpy as np
import pandas as pd
import streamlit as st

from v5_core import logistic, logit, simulate_match, american_from_prob
from v5_live_market import load_market_board, find_match_rows, add_model_pricing, signal_row

BASE = Path(__file__).resolve().parent


def load_ratings(tour):
    return pd.read_csv(BASE / f"v5_{tour.lower()}_ratings.csv", low_memory=False)


def base_probs_from_ratings(df, p1, p2, surface, baseline):
    a = df[(df.player == p1) & (df.surface == surface)]
    b = df[(df.player == p2) & (df.surface == surface)]

    if a.empty or b.empty:
        raise ValueError("Player/surface not found in V5 ratings.")

    a = a.iloc[-1]
    b = b.iloc[-1]

    # Shrink surface-specific effects when either player has limited data.
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
    """Display a probability and its model-implied fair American odds together."""
    odds = american_from_prob(prob)
    return f"{prob:.1%}  |  {odds:+d}"


def app():
    st.set_page_config(
        page_title="Tennis Quant Lab V5",
        layout="wide",
        page_icon="🎾",
    )

    st.title("Tennis Quant Lab V5 — Bottom-Up Tennis Simulator")
    st.caption(
        "Opponent-adjusted serve/return ratings → point probabilities → "
        "real games → sets → matches."
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
    simulations = st.select_slider(
        "Simulations",
        options=[5000, 10000, 20000, 50000],
        value=20000,
    )

    baseline = summary.get(tour, {}).get(
        "baseline",
        {"Hard": 0.62, "Clay": 0.62, "Grass": 0.62},
    )

    if st.button("RUN V5 SIMULATION", type="primary"):
        try:
            p1_serve, p2_serve, a, b = base_probs_from_ratings(
                ratings, p1, p2, surface, baseline
            )

            # Surface Elo remains an independent diagnostic.
            elo_a = (1 - 0.65) * a.elo + 0.65 * a.surface_elo
            elo_b = (1 - 0.65) * b.elo + 0.65 * b.surface_elo
            p_elo = 1 / (1 + 10 ** ((elo_b - elo_a) / 400))

            result = simulate_match(
                p1_serve,
                p2_serve,
                best_of=best_of,
                n=simulations,
                seed=42,
            )

            p1_match = float(result["pA_win"])
            p2_match = 1.0 - p1_match

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
                "Fair odds are simply the V5 win probability translated into "
                "American odds. They are not a separate prediction."
            )

            st.subheader("Underlying Point Model")
            p1c, p2c, eloc = st.columns(3)

            p1c.metric(
                f"{p1} Serve-Point Win %",
                f"{p1_serve:.1%}",
            )

            p2c.metric(
                f"{p2} Serve-Point Win %",
                f"{p2_serve:.1%}",
            )

            eloc.metric(
                f"Surface Elo — {p1}",
                prob_odds_text(p_elo),
                help="Independent diagnostic model; not silently blended into V5.",
            )

            st.subheader("Exact Match Score Distribution")
            score_rows = []
            for score, probability in sorted(result["score_probs"].items()):
                score_rows.append(
                    {
                        "Score": score,
                        "Probability": probability,
                        "Fair Odds": american_from_prob(probability),
                    }
                )

            score_df = pd.DataFrame(score_rows)
            st.dataframe(
                score_df.style.format(
                    {
                        "Probability": "{:.1%}",
                        "Fair Odds": lambda x: f"{int(x):+d}",
                    }
                ),
                use_container_width=True,
            )

            st.subheader("Game Spread Probabilities")
            spread_rows = []
            for line, probability in result["spread"].items():
                spread_rows.append(
                    {
                        f"{p1} Spread": line,
                        "Cover Probability": probability,
                        "Fair Odds": american_from_prob(probability),
                    }
                )

            spread_df = pd.DataFrame(spread_rows)
            st.dataframe(
                spread_df.style.format(
                    {
                        "Cover Probability": "{:.1%}",
                        "Fair Odds": lambda x: f"{int(x):+d}",
                    }
                ),
                use_container_width=True,
            )

            st.subheader("Total Games Probabilities")
            total_rows = []
            for line, probability in result["over"].items():
                total_rows.append(
                    {
                        "Total": f"Over {line}",
                        "Over Probability": probability,
                        "Fair Odds": american_from_prob(probability),
                    }
                )

            total_df = pd.DataFrame(total_rows)
            st.dataframe(
                total_df.style.format(
                    {
                        "Over Probability": "{:.1%}",
                        "Fair Odds": lambda x: f"{int(x):+d}",
                    }
                ),
                use_container_width=True,
            )


            # ---------------- LIVE MARKET COMPARISON ----------------
            market_board = load_market_board()
            match_markets = find_match_rows(market_board, p1, p2)

            st.subheader("Live Market Comparison")

            if match_markets.empty:
                st.info(
                    "No OddsPapi market snapshot currently matches this matchup. "
                    "The V5 projection above remains fully independent of sportsbook odds."
                )
            else:
                priced = add_model_pricing(match_markets, result, p1, p2)
                priced["Signal"] = priced.apply(signal_row, axis=1)

                # Half-line markets + ML can be priced without unmodeled push risk.
                actionable = priced[priced["model_probability"].notna()].copy()

                if actionable.empty:
                    st.info(
                        "Market prices exist, but none of the available lines can be "
                        "priced safely from the current V5 simulation output."
                    )
                else:
                    actionable["Model Prob"] = actionable["model_probability"]
                    actionable["Consensus No-Vig"] = actionable["consensus_no_vig_prob"]
                    actionable["Edge"] = actionable["edge_vs_consensus"]
                    actionable["EV"] = actionable["expected_value"]
                    actionable["Fair Odds"] = actionable["model_fair_american"]
                    actionable["Best Odds"] = actionable["best_american_odds"]
                    actionable["Book"] = actionable["best_bookmaker"]
                    actionable["Market"] = actionable["market_group"]
                    actionable["Selection"] = actionable["selection"]
                    actionable["Line"] = actionable["line"]

                    show_cols = [
                        "Signal",
                        "Market",
                        "Selection",
                        "Line",
                        "Book",
                        "Best Odds",
                        "Model Prob",
                        "Fair Odds",
                        "Consensus No-Vig",
                        "Edge",
                        "EV",
                    ]

                    actionable = actionable.sort_values(
                        ["expected_value", "edge_vs_consensus"],
                        ascending=False,
                        na_position="last",
                    )

                    st.dataframe(
                        actionable[show_cols].style.format(
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
                    )

                    st.caption(
                        "V5 probabilities are generated first. Sportsbook odds are joined "
                        "after simulation only for no-vig comparison and EV. Integer game "
                        "spreads/totals are intentionally excluded from automated EV until "
                        "push probabilities are explicitly modeled."
                    )

            st.subheader("Additional Simulation Diagnostics")
            d1, d2 = st.columns(2)

            d1.metric(
                "Tiebreak Occurs",
                prob_odds_text(float(result["tiebreak_prob"])),
            )

            d2.write(
                {
                    "Margin SD": round(float(result["margin_sd"]), 2),
                    "Total SD": round(float(result["total_sd"]), 2),
                    "Simulations": simulations,
                }
            )

        except Exception as exc:
            st.error(str(exc))

    st.divider()
    st.caption(
        "V5 Alpha: genuine point → game → set → match simulation. "
        "Surface Elo remains independent until walk-forward validation proves "
        "an ensemble improves calibration and log loss."
    )


if __name__ == "__main__":
    app()
