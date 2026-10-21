"""Per-match table for the first-server tests (2010 to 2026-10-12, sealed period excluded).

Joins the match warehouse rows (scores, service-game and break counts, via
research_tests/features/build_features.load) to the leak-free pre-match features
(research_tests/features/features.pkl: Barnett-Clarke serve-point probabilities bc_fab/bc_fba
from exponentially weighted serve/return shares, Elo, ranks), orients every match A/B by the
stable key hash used there (not winner-first), and infers the first server.

Run: python research_tests/first_server/build_fs_table.py  -> fs_table.pkl in the scratchpad.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "research_tests", "features"))
sys.path.insert(0, HERE)
import build_features as bf  # noqa: E402
import fs_core as fc  # noqa: E402

SCRATCH = os.environ.get("FS_SCRATCH", "/tmp/claude-0/-home-user-Tennis-Quant-Lab-V5/a0609b44-84ba-59ef-a5f1-f66b68d375ec/scratchpad")


def main():
    m = bf.load()
    F = pd.read_pickle(os.path.join(ROOT, "research_tests", "features", "features.pkl"))
    keep = ["key", "a_key", "b_key", "y", "group", "year", "bc_fab", "bc_fba", "elo_p", "a_rank", "b_rank",
            "a_home", "b_home", "stage", "round_rank", "surface_c", "level_ord", "n_min", "a_spw_h20", "b_spw_h20",
            "a_rpw_h20", "b_rpw_h20", "a_entry_Q", "b_entry_Q"]
    F = F[keep]
    cols = ["key", "tourney_name", "level", "surface", "round", "date", "score", "best_of", "retired", "walkover",
            "w_SvGms", "l_SvGms", "w_bpFaced", "w_bpSaved", "l_bpFaced", "l_bpSaved",
            "w_svpt", "w_1stWon", "w_2ndWon", "l_svpt", "l_1stWon", "l_2ndWon"]
    t = F.merge(m[cols], on="key", how="inner")
    t = t[~t.retired.astype(bool) & ~t.walkover.astype(bool)].copy()
    t["sets_w"] = [fc.parse_sets(s, b) for s, b in zip(t.score, t.best_of)]
    t = t[t.sets_w.notna()].copy()
    who, how = [], []
    num = lambda c: pd.to_numeric(t[c], errors="coerce").to_numpy(float)
    wsv, lsv, wbf, wbs, lbf, lbs = (num(c) for c in ("w_SvGms", "l_SvGms", "w_bpFaced", "w_bpSaved", "l_bpFaced", "l_bpSaved"))
    for i, s in enumerate(t.sets_w):
        a, b = fc.infer_first_server(s, wsv[i], lsv[i], wbf[i], wbs[i], lbf[i], lbs[i])
        who.append(a); how.append(b)
    t["first_wl"], t["method"] = who, how
    a_w = t.y.to_numpy() == 1
    t["sets_a"] = [s if aw else [(b, a, tb) for a, b, tb in s] for s, aw in zip(t.sets_w, a_w)]
    fw = t.first_wl.to_numpy()
    t["first_a"] = np.where(pd.isna(fw), np.nan, np.where((fw == "W") == a_w, 1.0, 0.0))
    t["T"] = [sum(a + b for a, b, _ in s) for s in t.sets_a]
    t["H"] = [sum(a - b for a, b, _ in s) for s in t.sets_a]                 # A games minus B games
    t["n_tb"] = [sum(tb for _, _, tb in s) for s in t.sets_a]
    t["rule"] = [fc.final_set_rule(l, n, d.year, b) for l, n, d, b in zip(t.level, t.tourney_name, t.date, t.best_of)]
    # in-match serve-point shares (the paper's P_W, P_L; NOT pre-match, only for the replication)
    wsp = (num("w_1stWon") + num("w_2ndWon")) / num("w_svpt")
    lsp = (num("l_1stWon") + num("l_2ndWon")) / num("l_svpt")
    t["pa_in"] = np.where(a_w, wsp, lsp)
    t["pb_in"] = np.where(a_w, lsp, wsp)
    t["pa_pre"] = np.clip(t.bc_fab.to_numpy(float), 0.40, 0.90)
    t["pb_pre"] = np.clip(t.bc_fba.to_numpy(float), 0.40, 0.90)
    t = t.drop(columns=["sets_w"]).reset_index(drop=True)
    out = os.path.join(SCRATCH, "fs_table.pkl")
    t.to_pickle(out)
    print("rows", len(t), "->", out)
    print(t.groupby("group").method.value_counts().unstack().fillna(0).astype(int))


if __name__ == "__main__":
    main()
