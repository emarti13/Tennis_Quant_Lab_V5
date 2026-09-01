from __future__ import annotations

from v5_core import DynamicServeReturn, SurfaceElo

SURFACES = {"Hard", "Clay", "Grass"}


def _surface(row) -> str:
    surf = str(row.get("surface") or "Hard").title()
    return surf if surf in SURFACES else "Hard"


class V5ReplayEngine:
    """V5 adapter for ReplayStateStore.

    Uses the same DynamicServeReturn and SurfaceElo update sequence as build_v5_states,
    but exposes a pre-match snapshot before the target match is incorporated.
    """

    def __init__(self, baseline: dict):
        self.sr = DynamicServeReturn(baseline)
        self.elo = SurfaceElo()
        self.match_index = 0

    def snapshot(self, row) -> dict:
        surf = _surface(row)
        p1 = str(row.get("winner_name") or row.get("winner"))
        p2 = str(row.get("loser_name") or row.get("loser"))

        p1_serve = self.sr.point_prob(p1, p2, surf, self.match_index)
        p2_serve = self.sr.point_prob(p2, p1, surf, self.match_index)
        elo_p1 = self.elo.probability(p1, p2, surf)

        def state(player: str):
            ss = self.sr.s[(player, surf)]
            gs = self.sr.g[player]
            return {
                "player": player,
                "surface": surf,
                "serve_global": gs.serve,
                "return_global": gs.ret,
                "global_points": gs.n_points,
                "serve_surface": ss.serve,
                "return_surface": ss.ret,
                "surface_points": ss.n_points,
                **self.sr.current_state(player, surf),
                **self.elo.snapshot(player, surf),
            }

        return {
            "surface": surf,
            "player1": p1,
            "player2": p2,
            "player1_serve_p": p1_serve,
            "player2_serve_p": p2_serve,
            "elo_player1_p": elo_p1,
            "player1_state": state(p1),
            "player2_state": state(p2),
            "matches_seen": self.match_index,
        }

    def update(self, row) -> None:
        surf = _surface(row)
        winner = str(row.get("winner_name") or row.get("winner"))
        loser = str(row.get("loser_name") or row.get("loser"))
        self.sr.update_match(row, self.match_index)
        self.elo.update(winner, loser, surf)
        self.match_index += 1
