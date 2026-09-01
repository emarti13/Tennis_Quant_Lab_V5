from __future__ import annotations

from historical_fixture_matcher import canonical_name


def grade_market(market_type: str, selection: str, line, result: dict) -> str:
    mt = str(market_type).lower()
    winner = canonical_name(result.get("winner"))
    loser = canonical_name(result.get("loser"))
    gw = float(result.get("games_winner", 0))
    gl = float(result.get("games_loser", 0))
    pick = canonical_name(selection)

    if mt == "moneyline":
        return "WIN" if pick == winner else ("LOSS" if pick == loser else "VOID")

    if mt == "game_spread":
        if pick == winner:
            margin = gw - gl
        elif pick == loser:
            margin = gl - gw
        else:
            return "VOID"
        graded = margin + float(line)
        return "WIN" if graded > 0 else ("LOSS" if graded < 0 else "PUSH")

    total = gw + gl
    if mt == "total_games_over":
        graded = total - float(line)
        return "WIN" if graded > 0 else ("LOSS" if graded < 0 else "PUSH")
    if mt == "total_games_under":
        graded = float(line) - total
        return "WIN" if graded > 0 else ("LOSS" if graded < 0 else "PUSH")

    return "VOID"


def profit_units(outcome: str, decimal_odds: float) -> float:
    outcome = str(outcome).upper()
    if outcome == "WIN":
        return float(decimal_odds) - 1.0
    if outcome == "LOSS":
        return -1.0
    return 0.0


def implied_probability(decimal_odds: float) -> float:
    d = float(decimal_odds)
    if d <= 1:
        raise ValueError("decimal odds must be > 1")
    return 1.0 / d


def expected_value(model_probability: float, decimal_odds: float) -> float:
    p = float(model_probability)
    d = float(decimal_odds)
    return p * (d - 1.0) - (1.0 - p)
