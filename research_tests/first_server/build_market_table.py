"""2026 fixtures (true start before the 2026-10-13 seal) joined to fs_table rows and to stored
moneyline, total-games and game-handicap prices (OddsPapi price_points: Pinnacle plus the
execution books). One row per fixture with player1 as side A.

Prices per checkpoint (open, t24h, t12h, t6h, t1h, close; stale closes dropped). For totals and
handicaps the "main" line is the Pinnacle line whose de-vigged probability is closest to 50% at
that checkpoint. Execution-book prices are kept for every Pinnacle main line they quote.

Run after build_fs_table.py: python research_tests/first_server/build_market_table.py
"""
from __future__ import annotations

import glob
import os

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
SCRATCH = os.environ.get("FS_SCRATCH", "/tmp/claude-0/-home-user-Tennis-Quant-Lab-V5/a0609b44-84ba-59ef-a5f1-f66b68d375ec/scratchpad")
SEAL = pd.Timestamp("2026-10-13", tz="UTC")
CPS = ["open", "t24h", "t12h", "t6h", "t1h", "close"]
BOOKS = ["pinnacle", "betrivers", "draftkings", "bet365"]


def load_prices():
    fx = pd.concat([pd.read_csv(f) for f in sorted(glob.glob(os.path.join(ROOT, "market_history/fixtures/*.csv")))])
    fx = fx[fx.resolution == "ok"].drop_duplicates("fixture_id", keep="last")
    fx["start"] = pd.to_datetime(fx.cutoff_utc, utc=True)
    fx = fx[fx.start < SEAL]
    pp = pd.concat([pd.read_csv(f) for f in sorted(glob.glob(os.path.join(ROOT, "market_history/price_points/*.csv")))])
    pp = pp[pp.fixture_id.isin(fx.fixture_id) & pp.bookmaker.isin(BOOKS)]
    pp.loc[pp.close_stale.astype(str) == "True", "close_price"] = np.nan
    return fx, pp


def join_results(fx):
    t = pd.read_pickle(os.path.join(SCRATCH, "fs_table.pkl"))
    t = t[t.date >= "2025-12-01"]
    rows = []
    by_pair = {}
    for i, r in enumerate(t.itertuples()):
        by_pair.setdefault(frozenset((r.a_key, r.b_key)), []).append(i)
    for f in fx.itertuples():
        c = by_pair.get(frozenset((f.player1_id, f.player2_id)), [])
        st = f.start.tz_localize(None)
        hit = [i for i in c if pd.Timedelta(days=-3) <= st - t.date.iloc[i] <= pd.Timedelta(days=21)]
        if len(hit) == 1:
            rows.append((f.fixture_id, hit[0], t.a_key.iloc[hit[0]] == f.player1_id))
    j = pd.DataFrame(rows, columns=["fixture_id", "ti", "p1_is_a"])
    tt = t.iloc[j.ti].reset_index(drop=True)
    flip = ~j.p1_is_a.to_numpy()
    out = tt.copy()
    out["fixture_id"] = j.fixture_id.values
    # re-orient to p1 = A
    for a, b in (("pa_pre", "pb_pre"), ("pa_in", "pb_in"), ("a_rank", "b_rank"), ("a_key", "b_key"),
                 ("a_home", "b_home"), ("a_entry_Q", "b_entry_Q")):
        av, bv = out[a].to_numpy().copy(), out[b].to_numpy().copy()
        out[a], out[b] = np.where(flip, bv, av), np.where(flip, av, bv)
    out["elo_p"] = np.where(flip, 1 - out.elo_p, out.elo_p)
    out["y"] = np.where(flip, 1 - out.y, out.y)
    out["first_a"] = np.where(flip, 1 - out.first_a, out.first_a)
    out["H"] = np.where(flip, -out.H, out.H)
    out["sets_a"] = [s if not fl else [(b, a, tb) for a, b, tb in s] for s, fl in zip(out.sets_a, flip)]
    return out.merge(fx[["fixture_id", "start", "edition_key"]], on="fixture_id")


def wide(pp, market):
    m = pp[pp.market_group == market].copy()
    if market == "game_spread":
        m["mline"] = np.where(m.side == "p1", m.line, -m.line)     # p1's handicap
        m["s"] = m.side
    elif market == "total_games":
        m["mline"] = m.line
        m["s"] = m.side.str.lower()
    else:
        m["mline"] = 0.0
        m["s"] = m.side
    m = m.drop_duplicates(["fixture_id", "bookmaker", "mline", "s"], keep="last")
    return m


def main():
    fx, pp = load_prices()
    res = join_results(fx)
    print("fixtures before seal", len(fx), "joined to results", len(res))
    out = res.copy()
    a_side, b_side = {"moneyline": ("p1", "p2"), "total_games": ("over", "under"), "game_spread": ("p1", "p2")}, None
    for market, tag in (("moneyline", "ml"), ("total_games", "tot"), ("game_spread", "hc")):
        m = wide(pp, market)
        sa, sb = a_side[market]
        for cp in CPS:
            w = m.pivot_table(index=["fixture_id", "mline"], columns=["bookmaker", "s"], values=f"{cp}_price", aggfunc="first")
            if ("pinnacle", sa) not in w or ("pinnacle", sb) not in w:
                continue
            ia, ib = 1 / w[("pinnacle", sa)], 1 / w[("pinnacle", sb)]
            fair = (ia / (ia + ib)).rename("fair")
            d = fair.dropna().reset_index()
            d["dist"] = (d.fair - 0.5).abs()
            d = d.sort_values("dist").drop_duplicates("fixture_id")          # main line
            cols = {"fixture_id": d.fixture_id.values, f"{tag}_{cp}_line": d.mline.values, f"{tag}_{cp}_fair": d.fair.values,
                    f"{tag}_{cp}_over": None}
            cols.pop(f"{tag}_{cp}_over")
            frame = pd.DataFrame(cols)
            idx = pd.MultiIndex.from_arrays([d.fixture_id, d.mline])
            for bk in BOOKS:
                for s in (sa, sb):
                    if (bk, s) in w:
                        frame[f"{tag}_{cp}_{bk}_{s}"] = w[(bk, s)].reindex(idx).values
            if market == "moneyline":
                frame = frame.drop(columns=[f"{tag}_{cp}_line"])
            out = out.merge(frame, on="fixture_id", how="left")
    path = os.path.join(SCRATCH, "fs_market.pkl")
    out.to_pickle(path)
    print("rows", len(out), "with Pinnacle close total", int(out.tot_close_fair.notna().sum()),
          "handicap", int(out.hc_close_fair.notna().sum()), "->", path)


if __name__ == "__main__":
    main()
