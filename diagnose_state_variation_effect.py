from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

from v5_core import simulate_match
from v5_daily_batch import (
    _base_probs_from_ratings,
    _confidence_for_market,
    _requested_market_lines,
    infer_best_of,
    resolve_fixture_surface,
)
from v5_live_market import add_model_pricing, canonical_name, signal_row

BASE = Path(__file__).resolve().parent
BOARD = BASE / "v5_daily_ready" / "latest_board.csv"
OUT = BASE / "v5_daily_ready" / "state_variation_diagnostic.json"
SCALES = (0.0, 0.25, 0.5, 0.75, 1.0)
SIMS = 1000


def num(value):
    try:
        x = float(value)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def mean(xs):
    xs = [x for x in xs if x is not None and math.isfinite(float(x))]
    return float(np.mean(xs)) if xs else None


def pct(x):
    return None if x is None else 100.0 * x


def tour_key(row):
    x = str(row.get("tour_v5") or row.get("tour") or "").upper()
    return "WTA" if x == "WTA" or "WOMEN" in x else "MEN"


def player_row(ratings, player, surface):
    x = ratings[(ratings.player == player) & (ratings.surface == surface)]
    if x.empty:
        return None
    return x.iloc[-1]


def summarize(priced_frames):
    d = pd.concat(priced_frames, ignore_index=True, sort=False) if priced_frames else pd.DataFrame()
    if d.empty:
        return {}
    bets = d[d.signal == "BET"] if "signal" in d.columns else d.iloc[0:0]

    ml = d[(d.market_group == "moneyline") & d.model_probability.notna() & d.consensus_no_vig_prob.notna()].copy()
    ml["q"] = pd.to_numeric(ml.consensus_no_vig_prob, errors="coerce")
    ml["p"] = pd.to_numeric(ml.model_probability, errors="coerce")
    ml = ml.dropna(subset=["p", "q"])
    ml["compression"] = (ml.q - 0.5).abs() - (ml.p - 0.5).abs()
    dogs = ml[ml.q < 0.5]
    favs = ml[ml.q > 0.5]
    extreme = ml[(ml.q > 0) & (ml.q < 0.20)]

    totals = d[(d.market_group == "total_games") & d.model_probability.notna()].copy()
    total_bets = bets[bets.market_group == "total_games"]
    ml_bets = bets[bets.market_group == "moneyline"]
    spread_bets = bets[bets.market_group == "game_spread"]

    ml_bet_side = Counter()
    for _, r in ml_bets.iterrows():
        q = num(r.get("consensus_no_vig_prob"))
        if q is None:
            ml_bet_side["unknown"] += 1
        elif q < 0.5:
            ml_bet_side["underdog"] += 1
        elif q > 0.5:
            ml_bet_side["favorite"] += 1
        else:
            ml_bet_side["pickem"] += 1

    total_bet_side = Counter(str(x).strip().lower() for x in total_bets.selection)

    # Map spread selections back to ML market side for the same fixture.
    ml_market = {}
    for _, r in ml.iterrows():
        ml_market[(str(r.fixture_id), canonical_name(r.selection))] = float(r.q)
    spread_bet_side = Counter()
    for _, r in spread_bets.iterrows():
        q = ml_market.get((str(r.fixture_id), canonical_name(r.selection)))
        if q is None:
            spread_bet_side["unknown"] += 1
        elif q < 0.5:
            spread_bet_side["underdog"] += 1
        elif q > 0.5:
            spread_bet_side["favorite"] += 1
        else:
            spread_bet_side["pickem"] += 1

    return {
        "priced_rows": int(d.model_probability.notna().sum()),
        "bet_rows": int(len(bets)),
        "moneyline": {
            "mean_compression_toward_50_pp": pct(mean(ml.compression.tolist())),
            "share_compressed_toward_50": mean((ml.compression > 0).astype(float).tolist()),
            "mean_model_minus_market_dog_pp": pct(mean((dogs.p - dogs.q).tolist())),
            "mean_model_minus_market_favorite_pp": pct(mean((favs.p - favs.q).tolist())),
            "extreme_dog_below_20pct_model_market_ratio": mean((extreme.p / extreme.q).tolist()),
            "bet_side_counts": dict(ml_bet_side),
        },
        "spread_bet_side_counts": dict(spread_bet_side),
        "total_bet_side_counts": dict(total_bet_side),
        "totals": {
            "mean_expected_total": mean(pd.to_numeric(totals.expected_total, errors="coerce").tolist()),
            "mean_edge_pp": pct(mean(pd.to_numeric(totals.edge_vs_consensus, errors="coerce").tolist())),
        },
    }


def main():
    board = pd.read_csv(BOARD, low_memory=False)
    ratings = {
        "MEN": pd.read_csv(BASE / "v5_men_ratings.csv", low_memory=False),
        "WTA": pd.read_csv(BASE / "v5_wta_ratings.csv", low_memory=False),
    }
    summary = json.loads((BASE / "v5_build_summary.json").read_text(encoding="utf-8"))

    frames_by_scale = {scale: [] for scale in SCALES}
    fixture_effects = {scale: [] for scale in SCALES}
    failures = []

    for fixture_id, g in board.groupby("fixture_id", sort=False):
        first = g.iloc[0]
        tour = tour_key(first)
        surface = str(first.get("surface") or resolve_fixture_surface(
            first.get("tournament"), start_time_utc=first.get("start_time_utc"), tour=str(first.get("tour") or ""))[0])
        best_of = infer_best_of(first.get("tournament"), tour)
        p1 = first.get("resolved_player1")
        p2 = first.get("resolved_player2")
        if not p1 or not p2:
            failures.append({"fixture_id": str(fixture_id), "error": "missing resolved player"})
            continue
        try:
            baseline = summary.get(tour, {}).get("baseline", {"Hard": .62, "Clay": .60, "Grass": .65})
            p1_serve, p2_serve, a, b = _base_probs_from_ratings(ratings[tour], p1, p2, surface, baseline)
            elo_a = 0.35 * float(a.elo) + 0.65 * float(a.surface_elo)
            elo_b = 0.35 * float(b.elo) + 0.65 * float(b.surface_elo)
            p_elo = 1 / (1 + 10 ** ((elo_b - elo_a) / 400))
            p1_conf = float(a.get("state_confidence", 0.0))
            p2_conf = float(b.get("state_confidence", 0.0))
            spread_lines = _requested_market_lines(g, "game_spread")
            total_lines = _requested_market_lines(g, "total_games")
            for scale in SCALES:
                result = simulate_match(
                    p1_serve,
                    p2_serve,
                    best_of=best_of,
                    n=SIMS,
                    seed=42,
                    formA=float(a.get("form_logit", 0.0)),
                    formB=float(b.get("form_logit", 0.0)),
                    volA=float(a.get("day_vol_logit", 0.06)) * scale,
                    volB=float(b.get("day_vol_logit", 0.06)) * scale,
                    state_variation=True,
                    spread_lines=spread_lines,
                    total_lines=total_lines,
                )
                p_match = float(result["pA_win"])
                gap = abs(p_match - p_elo)
                disagreement = "HIGH" if gap >= .12 else ("MODERATE" if gap >= .07 else "LOW")
                priced = add_model_pricing(g, result, p1, p2)
                priced["expected_total"] = float(result["expected_total"])
                priced["expected_margin"] = float(result["expected_margin"])
                priced["elo_probability_p1"] = p_elo
                priced["signal"] = [
                    signal_row(
                        r,
                        disagreement_level=disagreement,
                        state_confidence=_confidence_for_market(r, p1, p2, p1_conf, p2_conf),
                    )
                    for _, r in priced.iterrows()
                ]
                frames_by_scale[scale].append(priced)
                fixture_effects[scale].append({
                    "p_model": p_match,
                    "p_elo": p_elo,
                    "abs_model_elo_gap": gap,
                    "expected_total": float(result["expected_total"]),
                    "expected_margin_abs": abs(float(result["expected_margin"])),
                })
        except Exception as exc:
            failures.append({"fixture_id": str(fixture_id), "error": str(exc)})

    output = {
        "simulations_per_fixture_scale": SIMS,
        "fixtures_attempted": int(board.fixture_id.nunique()),
        "failures": failures,
        "scales": {},
    }
    for scale in SCALES:
        s = summarize(frames_by_scale[scale])
        effects = fixture_effects[scale]
        s["fixture_level"] = {
            "mean_abs_model_elo_gap_pp": pct(mean([x["abs_model_elo_gap"] for x in effects])),
            "mean_expected_total": mean([x["expected_total"] for x in effects]),
            "mean_abs_expected_margin": mean([x["expected_margin_abs"] for x in effects]),
        }
        output["scales"][str(scale)] = s

    OUT.write_text(json.dumps(output, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
