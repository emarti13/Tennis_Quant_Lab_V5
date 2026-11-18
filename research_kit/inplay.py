"""Fair in-play match-win probability from the score (point-level Markov model).

Each player wins a point on their own serve with a fixed probability (pA for A, pB for B). From any
score (sets, games in the set, points in the game or tie-break, who serves) the chance that A wins
the match follows exactly: games, tie-breaks, sets and the match are chained recursively.

The two serve probabilities come from the PRE-MATCH price, not from player profiles. The pre-match
price already carries surface, indoor/outdoor, altitude, court speed, form and fitness. Given the
typical share of serve points won at that kind of event (`level`, the average of pA and pB), we solve
for the gap pA - pB that reproduces the pre-match price. The level mainly sets how much one break
moves the price; the gap is set by the market.

Formats: sets to 6 with a 7-point tie-break at 6-6; best of 3 or 5; the deciding set may use a
10-point tie-break at 6-6 (`final_set_tb=10`, Grand Slams since 2022) or a 10-point match tie-break in
place of the whole deciding set (`match_tb=True`, e.g. some doubles; not used for singles here).

Scores are always given from A's side: (sets_a, sets_b), (games_a, games_b), (points_a, points_b),
and `a_serves` for who serves the current point (in a tie-break: the current point's server).
Points in a game are counted 0, 1, 2, 3, 4... (0/15/30/40/game); "A" (advantage) is 4 against 3.
"""
from __future__ import annotations

from functools import lru_cache

# share of serve points won, 2022-2025 TennisMyLife (research_tests/inplay_model/README); WTA not in
# the stats files: a published-average value, not measured here
SERVE_LEVEL = {
    ("ATP", "Clay", "O"): 0.6188, ("ATP", "Grass", "O"): 0.6597, ("ATP", "Hard", "I"): 0.6553, ("ATP", "Hard", "O"): 0.6409,
    ("CH", "Clay", "O"): 0.5980, ("CH", "Grass", "O"): 0.6419, ("CH", "Hard", "I"): 0.6325, ("CH", "Hard", "O"): 0.6165,
}
WTA_LEVEL = 0.56


def serve_level(tour: str, surface: str | None, indoor: bool | None) -> float:
    """Typical serve-point win share for the event type (fails closed to the tour's hard-court value
    only when the surface is unknown)."""
    if tour == "WTA":
        return WTA_LEVEL
    key = (tour, (surface or "Hard").title(), "I" if indoor else "O")
    if key in SERVE_LEVEL:
        return SERVE_LEVEL[key]
    return SERVE_LEVEL[(tour, "Hard", "O")]


# ----------------------------------------------------------------- game
def p_game(p: float, a: int = 0, b: int = 0) -> float:
    """Chance the server wins the game from points (a, b), server's point-win probability p."""
    return _game(round(p, 10), a, b)


@lru_cache(maxsize=None)
def _game(p: float, a: int, b: int) -> float:
    q = 1 - p
    if a >= 4 and a - b >= 2:
        return 1.0
    if b >= 4 and b - a >= 2:
        return 0.0
    if a >= 3 and b >= 3:
        deuce = p * p / (p * p + q * q)
        if a == b:
            return deuce
        return p + q * deuce if a > b else p * deuce
    return p * _game(p, a + 1, b) + q * _game(p, a, b + 1)


# ----------------------------------------------------------------- tie-break
def _tb_server_is_first(k: int) -> bool:
    """In a tie-break, point k (0-based) is served by the player who served point 0 when this is True."""
    return ((k + 1) // 2) % 2 == 0


def p_tiebreak(pa: float, pb: float, i: int, j: int, a_serves_now: bool, target: int = 7) -> float:
    """Chance A wins the tie-break from points (i, j), A serving the current point if a_serves_now."""
    k = i + j
    a_first = a_serves_now if _tb_server_is_first(k) else not a_serves_now
    return _tb(round(pa, 10), round(pb, 10), i, j, a_first, target)


@lru_cache(maxsize=None)
def _tb(pa: float, pb: float, i: int, j: int, a_first: bool, target: int) -> float:
    if i >= target and i - j >= 2:
        return 1.0
    if j >= target and j - i >= 2:
        return 0.0
    k = i + j

    def win_pt(kk: int) -> float:
        a_srv = a_first if _tb_server_is_first(kk) else not a_first
        return pa if a_srv else 1 - pb
    if i == j and i >= target - 1:
        x, y = win_pt(k), win_pt(k + 1)                         # the next two points have different servers
        return x * y / (x * y + (1 - x) * (1 - y))
    w = win_pt(k)
    return w * _tb(pa, pb, i + 1, j, a_first, target) + (1 - w) * _tb(pa, pb, i, j + 1, a_first, target)


# ----------------------------------------------------------------- set
@lru_cache(maxsize=None)
def _set_dist(pa: float, pb: float, ga: int, gb: int, a_serves: bool, tb_target: int) -> tuple[float, float, float, float]:
    """From the start of a game at (ga, gb) with A serving it if a_serves: probabilities of
    (A wins, next set A serves first), (A wins, B first), (B wins, A first), (B wins, B first)."""
    if (ga >= 6 and ga - gb >= 2) or ga == 7:
        return (1.0, 0.0, 0.0, 0.0) if a_serves else (0.0, 1.0, 0.0, 0.0)
    if (gb >= 6 and gb - ga >= 2) or gb == 7:
        return (0.0, 0.0, 1.0, 0.0) if a_serves else (0.0, 0.0, 0.0, 1.0)
    if ga == 6 and gb == 6:
        t = _tb(pa, pb, 0, 0, a_serves, tb_target)
        # the player who received first in the tie-break serves the next set's first game
        return (0.0, t, 0.0, 1 - t) if a_serves else (t, 0.0, 1 - t, 0.0)
    h = _game(pa, 0, 0) if a_serves else 1 - _game(pb, 0, 0)       # chance A wins this game
    w = _set_dist(pa, pb, ga + 1, gb, not a_serves, tb_target)
    lose = _set_dist(pa, pb, ga, gb + 1, not a_serves, tb_target)
    return tuple(h * x + (1 - h) * y for x, y in zip(w, lose))


# ----------------------------------------------------------------- match
@lru_cache(maxsize=None)
def _match(pa: float, pb: float, sa: int, sb: int, a_serves: bool, sets_to_win: int, final_set_tb: int) -> float:
    """From the start of a set at sets (sa, sb), A serving its first game if a_serves."""
    if sa == sets_to_win:
        return 1.0
    if sb == sets_to_win:
        return 0.0
    deciding = sa == sb == sets_to_win - 1
    d = _set_dist(pa, pb, 0, 0, a_serves, final_set_tb if deciding else 7)
    return (d[0] * _match(pa, pb, sa + 1, sb, True, sets_to_win, final_set_tb) + d[1] * _match(pa, pb, sa + 1, sb, False, sets_to_win, final_set_tb)
            + d[2] * _match(pa, pb, sa, sb + 1, True, sets_to_win, final_set_tb) + d[3] * _match(pa, pb, sa, sb + 1, False, sets_to_win, final_set_tb))


def p_match(pa: float, pb: float, sets: tuple[int, int] = (0, 0), games: tuple[int, int] = (0, 0),
            points: tuple[int, int] = (0, 0), a_serves: bool | None = None, best_of: int = 3, final_set_tb: int = 7) -> float:
    """Chance A wins the match from the given score. a_serves=None (match not started): the average
    over both possible first servers."""
    pa, pb = round(pa, 10), round(pb, 10)
    if a_serves is None:
        return 0.5 * (p_match(pa, pb, sets, games, points, True, best_of, final_set_tb)
                      + p_match(pa, pb, sets, games, points, False, best_of, final_set_tb))
    stw = (best_of + 1) // 2
    sa, sb = sets
    ga, gb = games
    i, j = points
    if sa >= stw or sb >= stw:
        return 1.0 if sa >= stw else 0.0
    deciding = sa == sb == stw - 1
    tb_target = final_set_tb if deciding else 7

    def after_set(a_won: bool, a_next: bool) -> float:
        return _match(pa, pb, sa + (1 if a_won else 0), sb + (0 if a_won else 1), a_next, stw, final_set_tb)
    if ga == 6 and gb == 6:                                          # in the tie-break
        t = p_tiebreak(pa, pb, i, j, a_serves, tb_target)
        k = i + j
        a_first = a_serves if _tb_server_is_first(k) else not a_serves
        nxt = not a_first
        return t * after_set(True, nxt) + (1 - t) * after_set(False, nxt)
    # in a game: A serving (points i for A) or B serving
    g = p_game(pa, i, j) if a_serves else 1 - p_game(pb, j, i)        # chance A wins this game
    w = _set_dist(pa, pb, ga + 1, gb, not a_serves, tb_target)
    lose = _set_dist(pa, pb, ga, gb + 1, not a_serves, tb_target)
    d = [g * x + (1 - g) * y for x, y in zip(w, lose)]
    return d[0] * after_set(True, True) + d[1] * after_set(True, False) + d[2] * after_set(False, True) + d[3] * after_set(False, False)


def solve_serve(p_pre: float, level: float, best_of: int = 3, final_set_tb: int = 7, tol: float = 1e-7) -> tuple[float, float]:
    """pA, pB with (pA + pB) / 2 = level such that A's pre-match chance (first server unknown) is p_pre."""
    if not 0.0 < p_pre < 1.0:
        raise ValueError(f"pre-match probability must be strictly between 0 and 1, got {p_pre}")
    lo, hi = -0.6, 0.6
    lo = max(lo, -2 * min(level, 1 - level) + 1e-6)
    hi = min(hi, 2 * min(level, 1 - level) - 1e-6)
    for _ in range(100):
        mid = (lo + hi) / 2
        v = p_match(level + mid / 2, level - mid / 2, best_of=best_of, final_set_tb=final_set_tb)
        if abs(v - p_pre) < tol:
            break
        if v < p_pre:
            lo = mid
        else:
            hi = mid
    return level + mid / 2, level - mid / 2
