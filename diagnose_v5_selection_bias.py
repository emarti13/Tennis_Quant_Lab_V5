from __future__ import annotations

import csv
import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

BOARD = Path("v5_daily_ready/latest_board.csv")
OUT = Path("v5_daily_ready/model_bias_diagnostic.json")


def canon(value: object) -> str:
    s = "" if value is None else str(value).strip()
    if "," in s:
        a, b = [x.strip() for x in s.split(",", 1)]
        if a and b:
            s = f"{b} {a}"
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", s).split())


def num(value):
    try:
        x = float(value)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def truthy(value) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def pct(x):
    return None if x is None else round(100.0 * x, 3)


def load_rows():
    with BOARD.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def classify_moneyline(row):
    q = num(row.get("consensus_no_vig_prob"))
    if q is None:
        return "unknown"
    if q < 0.5:
        return "underdog"
    if q > 0.5:
        return "favorite"
    return "pickem"


def grand_slam_men(tournament: str, tour: str) -> bool:
    if str(tour).upper() not in {"MEN", "ATP"}:
        return False
    t = str(tournament).lower()
    return any(x in t for x in ("australian open", "french open", "roland garros", "wimbledon", "us open"))


def main():
    rows = load_rows()
    signals = {"BET", "LEAN"}
    actionable = [r for r in rows if r.get("signal") in signals]
    bets = [r for r in rows if r.get("signal") == "BET"]

    # Selection-specific market ML probability for spread-side classification.
    ml_q = {}
    for r in rows:
        if r.get("market_group") != "moneyline":
            continue
        q = num(r.get("consensus_no_vig_prob"))
        if q is not None:
            ml_q[(r.get("fixture_id"), canon(r.get("selection")))] = q

    ml_rows = [r for r in rows if r.get("market_group") == "moneyline" and num(r.get("model_probability")) is not None and num(r.get("consensus_no_vig_prob")) is not None]
    ml_bets = [r for r in bets if r.get("market_group") == "moneyline"]
    ml_actionable = [r for r in actionable if r.get("market_group") == "moneyline"]

    side_counts_bet = Counter(classify_moneyline(r) for r in ml_bets)
    side_counts_actionable = Counter(classify_moneyline(r) for r in ml_actionable)

    compression = []
    dog_delta = []
    fav_delta = []
    extreme_dog_ratio = []
    extreme_dog_delta = []
    sub10_ratio = []
    for r in ml_rows:
        p = num(r.get("model_probability"))
        q = num(r.get("consensus_no_vig_prob"))
        compression.append(abs(q - 0.5) - abs(p - 0.5))  # positive => model closer to 50/50
        if q < 0.5:
            dog_delta.append(p - q)
        elif q > 0.5:
            fav_delta.append(p - q)
        if q < 0.20 and q > 0:
            extreme_dog_ratio.append(p / q)
            extreme_dog_delta.append(p - q)
        if q < 0.10 and q > 0:
            sub10_ratio.append(p / q)

    # Compare raw simulation to Elo on ML selections. Elo is currently only a diagnostic gate.
    elo_deltas_extreme_dog = []
    elo_vs_market_extreme_dog = []
    for r in ml_rows:
        q = num(r.get("consensus_no_vig_prob"))
        p = num(r.get("model_probability"))
        elo_p1 = num(r.get("elo_probability_p1"))
        if q is None or p is None or elo_p1 is None or q >= 0.20:
            continue
        sel = canon(r.get("selection"))
        p1 = canon(r.get("player1"))
        p2 = canon(r.get("player2"))
        elo_sel = elo_p1 if sel == p1 else (1.0 - elo_p1 if sel == p2 else None)
        if elo_sel is not None:
            elo_deltas_extreme_dog.append(p - elo_sel)
            elo_vs_market_extreme_dog.append(elo_sel - q)

    # Spread selections, labeled using the fixture ML market rather than spread sign.
    spread_bet_side = Counter()
    for r in bets:
        if r.get("market_group") != "game_spread":
            continue
        q = ml_q.get((r.get("fixture_id"), canon(r.get("selection"))))
        side = "unknown" if q is None else ("underdog" if q < 0.5 else ("favorite" if q > 0.5 else "pickem"))
        spread_bet_side[side] += 1

    total_rows = [r for r in rows if r.get("market_group") == "total_games" and num(r.get("model_probability")) is not None and num(r.get("consensus_no_vig_prob")) is not None]
    total_bets = [r for r in bets if r.get("market_group") == "total_games"]
    total_actionable = [r for r in actionable if r.get("market_group") == "total_games"]
    total_bet_side = Counter(str(r.get("selection", "")).strip().lower() for r in total_bets)
    total_actionable_side = Counter(str(r.get("selection", "")).strip().lower() for r in total_actionable)

    over_edges = []
    under_edges = []
    main_over_edges = []
    main_under_edges = []
    for r in total_rows:
        p = num(r.get("model_probability"))
        q = num(r.get("consensus_no_vig_prob"))
        edge = p - q
        side = str(r.get("selection", "")).strip().lower()
        if side == "over":
            over_edges.append(edge)
            if truthy(r.get("main_line")):
                main_over_edges.append(edge)
        elif side == "under":
            under_edges.append(edge)
            if truthy(r.get("main_line")):
                main_under_edges.append(edge)

    # One expected-total delta per fixture/main line.
    total_line_delta = []
    seen_total_key = set()
    for r in total_rows:
        if not truthy(r.get("main_line")):
            continue
        line = num(r.get("line"))
        exp = num(r.get("expected_total"))
        if line is None or exp is None:
            continue
        key = (r.get("fixture_id"), line)
        if key in seen_total_key:
            continue
        seen_total_key.add(key)
        total_line_delta.append(exp - line)

    # Hard-coded BO3 risk: men's Slam fixtures are currently simulated as BO3 in v5_daily_batch.py.
    slam_men_rows = [r for r in rows if grand_slam_men(r.get("tournament", ""), r.get("tour_v5") or r.get("tour", ""))]
    slam_men_fixtures = {r.get("fixture_id") for r in slam_men_rows}
    slam_priced_ml_spread = {
        r.get("fixture_id") for r in slam_men_rows
        if r.get("market_group") in {"moneyline", "game_spread"} and num(r.get("model_probability")) is not None
    }
    slam_unpriced_high_totals = [
        r for r in slam_men_rows
        if r.get("market_group") == "total_games"
        and (num(r.get("line")) or 0) > 26.5
        and num(r.get("model_probability")) is None
    ]

    # The existing BET rule has a side-dependent effective edge hurdle because EV >= 5%.
    # At fair decimal ~= 1/q, EV >= .05 implies p-q >= .05*q, in addition to edge >= .025.
    threshold_grid = []
    for q in (0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90):
        min_edge = max(0.025, 0.05 * q)
        threshold_grid.append({
            "market_probability": q,
            "minimum_absolute_edge_for_BET_approx": min_edge,
            "minimum_edge_pp": round(100 * min_edge, 2),
        })

    by_market_bets = Counter(r.get("market_group") for r in bets)
    by_market_actionable = Counter(r.get("market_group") for r in actionable)

    result = {
        "board_rows": len(rows),
        "bet_rows": len(bets),
        "actionable_rows_bet_or_lean": len(actionable),
        "bet_market_counts": dict(by_market_bets),
        "actionable_market_counts": dict(by_market_actionable),
        "moneyline": {
            "priced_rows": len(ml_rows),
            "bet_side_counts": dict(side_counts_bet),
            "actionable_side_counts": dict(side_counts_actionable),
            "mean_compression_toward_50_pp": pct(mean(compression)),
            "share_rows_model_closer_to_50_than_market": (sum(x > 0 for x in compression) / len(compression)) if compression else None,
            "mean_model_minus_market_underdog_pp": pct(mean(dog_delta)),
            "mean_model_minus_market_favorite_pp": pct(mean(fav_delta)),
            "market_prob_below_20pct_mean_model_market_ratio": mean(extreme_dog_ratio),
            "market_prob_below_20pct_mean_model_minus_market_pp": pct(mean(extreme_dog_delta)),
            "market_prob_below_10pct_mean_model_market_ratio": mean(sub10_ratio),
            "below_20pct_mean_model_minus_elo_pp": pct(mean(elo_deltas_extreme_dog)),
            "below_20pct_mean_elo_minus_market_pp": pct(mean(elo_vs_market_extreme_dog)),
        },
        "spreads": {
            "bet_side_counts_via_moneyline_market": dict(spread_bet_side),
        },
        "totals": {
            "priced_rows": len(total_rows),
            "bet_side_counts": dict(total_bet_side),
            "actionable_side_counts": dict(total_actionable_side),
            "mean_over_edge_pp_all_lines": pct(mean(over_edges)),
            "mean_under_edge_pp_all_lines": pct(mean(under_edges)),
            "mean_over_edge_pp_main_line": pct(mean(main_over_edges)),
            "mean_under_edge_pp_main_line": pct(mean(main_under_edges)),
            "mean_expected_total_minus_main_line_games": mean(total_line_delta),
            "main_line_fixture_count": len(total_line_delta),
        },
        "format_integrity": {
            "mens_grand_slam_fixtures_on_board": len(slam_men_fixtures),
            "mens_grand_slam_fixtures_with_bo3_priced_ml_or_spread": len(slam_priced_ml_spread),
            "mens_grand_slam_total_rows_above_26_5_unpriced": len(slam_unpriced_high_totals),
            "current_batch_best_of_value": 3,
        },
        "signal_rule_effective_edge_hurdle": threshold_grid,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
