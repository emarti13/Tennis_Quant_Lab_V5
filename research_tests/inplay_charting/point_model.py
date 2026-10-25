"""Exact iid point model for in-play win probability, from any point of a match.

Player A wins a point on serve with probability pa, B with pb. State: sets, games in the
current set, point score of the current game (server's points first), who serves. Handles
best of 3 or 5, 7-point tiebreaks at 6-6, and the final-set rule: "tb7" (tiebreak at 6-6),
"tb10" (10-point tiebreak at 6-6) or "adv" (no tiebreak, win by two games).
Serving order: games alternate; a tiebreak counts as one game for the order; in a tiebreak
the first server serves one point, then two each.
"""
from __future__ import annotations

from functools import lru_cache


def _game_from(i: int, j: int, p: float) -> float:
    """P(server wins the game) from server i points, returner j points (0, 1, 2, 3 = 40; deuce
    handled in closed form)."""
    q = 1 - p
    deuce = p * p / (p * p + q * q)

    @lru_cache(None)
    def g(i, j):
        if i >= 4 and i - j >= 2:
            return 1.0
        if j >= 4 and j - i >= 2:
            return 0.0
        if i >= 3 and j >= 3:
            if i == j:
                return deuce
            return p + q * deuce if i > j else p * deuce
        return p * g(i + 1, j) + q * g(i, j + 1)
    return g(i, j)


def _tb_from(a: int, b: int, a_first: bool, pa: float, pb: float, target: int) -> float:
    """P(A wins a tiebreak to `target`) from A a points, B b points; a_first: A served point 1."""
    @lru_cache(None)
    def t(a, b):
        if a >= target and a - b >= 2:
            return 1.0
        if b >= target and b - a >= 2:
            return 0.0
        n = a + b
        if a >= target - 1 and b >= target - 1 and a == b and n % 2 == 0:
            # tied at an even count: the next two points are one each, then the same state recurs
            first_serves = (n == 0) or ((n - 1) // 2) % 2 == 1
            p1 = pa if first_serves == a_first else 1 - pb      # A wins point n
            p2 = pa if (not first_serves) == a_first else 1 - pb  # A wins point n+1 (other server)
            return p1 * p2 / (p1 * p2 + (1 - p1) * (1 - p2))
        first_serves = (n == 0) or ((n - 1) // 2) % 2 == 1
        a_srv = first_serves == a_first
        p = pa if a_srv else 1 - pb
        return p * t(a + 1, b) + (1 - p) * t(a, b + 1)
    return t(a, b)


class Match:
    """Win probabilities for one (pa, pb, best_of, final_rule)."""

    def __init__(self, pa: float, pb: float, best_of: int = 3, final_rule: str = "tb7"):
        self.pa, self.pb, self.need, self.final_rule = pa, pb, best_of // 2 + 1, final_rule
        self.ha, self.hb = _game_from(0, 0, pa), _game_from(0, 0, pb)
        self._m = lru_cache(None)(self._match)

    def _final(self, sa, sb):
        return sa == sb == self.need - 1

    def _set_rule(self, sa, sb):
        return self.final_rule if self._final(sa, sb) else "tb7"

    def _is_tb(self, sa, sb, ga, gb):
        return ga == gb == 6 and self._set_rule(sa, sb) != "adv"

    def _after_game(self, sa, sb, ga, gb, a_srv, a_won):
        """Match probability after the current game (A won it or not)."""
        ga2, gb2 = (ga + 1, gb) if a_won else (ga, gb + 1)
        rule = self._set_rule(sa, sb)
        tb_game = ga == gb == 6 and rule != "adv"
        done_a = tb_game and a_won or (ga2 >= 6 and ga2 - gb2 >= 2)
        done_b = tb_game and not a_won or (gb2 >= 6 and gb2 - ga2 >= 2)
        nxt = not a_srv
        if done_a:
            return self._m(sa + 1, sb, 0, 0, nxt)
        if done_b:
            return self._m(sa, sb + 1, 0, 0, nxt)
        return self._m(sa, sb, ga2, gb2, nxt)

    def _game_prob(self, sa, sb, ga, gb, a_srv, i=0, j=0):
        """P(A wins the current game) from point score i (server) - j (returner); in a tiebreak
        i, j are A's and B's points and a_srv says whether A served the tiebreak's first point."""
        if self._is_tb(sa, sb, ga, gb):
            target = 10 if self._final(sa, sb) and self.final_rule == "tb10" else 7
            return _tb_from(i, j, a_srv, self.pa, self.pb, target)
        return _game_from(i, j, self.pa) if a_srv else 1 - _game_from(i, j, self.pb)

    def _match(self, sa, sb, ga, gb, a_srv):
        if sa == self.need:
            return 1.0
        if sb == self.need:
            return 0.0
        if self._set_rule(sa, sb) == "adv" and ga == gb >= 6:
            # final set, tied from 6-6 on: A must win both games of a pair (hold and break, in
            # either order), so the answer does not depend on who serves first
            x, y = self.ha * (1 - self.hb), (1 - self.ha) * self.hb
            return x / (x + y)
        g = self._game_prob(sa, sb, ga, gb, a_srv)
        return g * self._after_game(sa, sb, ga, gb, a_srv, True) + (1 - g) * self._after_game(sa, sb, ga, gb, a_srv, False)

    def prob(self, sa, sb, ga, gb, a_srv, i=0, j=0) -> float:
        """P(A wins the match). i, j: point score of the current game (server's points first;
        in a tiebreak A's points first, and a_srv = A served the tiebreak's first point)."""
        if sa == self.need:
            return 1.0
        if sb == self.need:
            return 0.0
        if i == 0 and j == 0:
            return self._m(sa, sb, ga, gb, a_srv)
        g = self._game_prob(sa, sb, ga, gb, a_srv, i, j)
        return g * self._after_game(sa, sb, ga, gb, a_srv, True) + (1 - g) * self._after_game(sa, sb, ga, gb, a_srv, False)

    def pre(self) -> float:
        """Before the first point, first server unknown (toss): average of both."""
        return 0.5 * (self._m(0, 0, 0, 0, True) + self._m(0, 0, 0, 0, False))
