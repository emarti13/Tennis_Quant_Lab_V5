"""Long table of book lines: one row per match x book x market (totals, game handicap) with
line, de-vigged chance and both sides' prices at the open and the close, and the outcome.

Filters (all pre-match / line-shape only, never the result):
- totals: best of 3 lines in [12.5, 33.5], best of 5 in [25.5, 50.5] (Ladbrokes' 2.5 / 4.5 rows
  are total-sets lines); Ladbrokes/Unibet lines more than 3 games from bet365's are dropped.
- handicap: Ladbrokes/Unibet +-1.5 rows mix set handicaps in (their odds spread is ~10x
  bet365's): dropped; other Ladbrokes/Unibet lines kept only within 1 game of bet365's.
- prices both > 1.01 and < 10.
Handicap orientation: side A is the favourite by that book's own moneyline (clear favourite,
>= 55%, same at open and close), giving the line's magnitude.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from prep import devig

BOOKS = ("b365", "lb", "ub")


def _ok(x):
    return (x > 1.01) & (x < 10)


def build_lines(d: pd.DataFrame) -> pd.DataFrame:
    rows = []
    b365_tl = d["b365_total_games_line"]
    b365_h = d["b365_handicap"]
    for b in BOOKS:
        # ---------------- totals
        L = d[f"{b}_total_games_line"]
        rng_ok = np.where(d["bo"] == 5, (L >= 25.5) & (L <= 50.5), (L >= 12.5) & (L <= 33.5))
        agree = (b == "b365") | b365_tl.isna() | ((L - b365_tl).abs() <= 3)
        oc, uc, oo, uo = d[f"{b}_over"], d[f"{b}_under"], d[f"{b}_over_opening"], d[f"{b}_under_opening"]
        keep = L.notna() & rng_ok & agree & _ok(oc) & _ok(uc)
        t = pd.DataFrame({"idx": d.index[keep], "book": b, "market": "tot", "line": L[keep].values,
                          "a_close": oc[keep].values, "b_close": uc[keep].values,
                          "a_open": oo[keep].where(_ok(oo[keep]) & _ok(uo[keep])).values,
                          "b_open": uo[keep].where(_ok(oo[keep]) & _ok(uo[keep])).values})
        t["A_is_w"] = np.nan
        rows.append(t)
        # ---------------- game handicap. The file's sign is NOT the winner's side (it is independent
        # of who is favoured: checked); the magnitude is the favourite's line and the two prices
        # are the winner's and the loser's (devig slope 1.06 on the favourite's cover under this
        # reading; the other reading gives slope 2.0, the signature of outcome orientation).
        H = d[f"{b}_handicap"].abs()
        hw, hl, hwo, hlo = d[f"{b}_hcp_odds_w"], d[f"{b}_hcp_odds_l"], d[f"{b}_hcp_odds_w_opening"], d[f"{b}_hcp_odds_l_opening"]
        mlc = devig(d[f"{b}_w"], d[f"{b}_l"]); mlo = devig(d[f"{b}_w_opening"], d[f"{b}_l_opening"])
        mlc = np.where(np.isfinite(mlc), mlc, d["pw_close"]); mlo = np.where(np.isfinite(mlo), mlo, d["pw_open"])
        fav_w_c, fav_w_o = mlc > 0.5, mlo > 0.5
        clear = (np.abs(mlc - 0.5) >= 0.05) & (fav_w_c == fav_w_o)       # same clear favourite at open and close
        if b == "b365":
            agree = (H >= 0.5) & (H <= 12.5)
        else:
            agree = (H != 1.5) & d["b365_handicap"].notna() & ((H - d["b365_handicap"].abs()).abs() <= 1)
        keep = (H.notna() & agree & _ok(hw) & _ok(hl)).values & clear
        A_is_w = fav_w_c[keep]
        h = pd.DataFrame({"idx": d.index[keep], "book": b, "market": "hcp", "line": -H[keep].values,
                          "a_close": np.where(A_is_w, hw[keep], hl[keep]), "b_close": np.where(A_is_w, hl[keep], hw[keep])})
        okO = (_ok(hwo) & _ok(hlo))[keep].values
        h["a_open"] = np.where(okO, np.where(A_is_w, hwo[keep], hlo[keep]), np.nan)
        h["b_open"] = np.where(okO, np.where(A_is_w, hlo[keep], hwo[keep]), np.nan)
        h["A_is_w"] = A_is_w
        rows.append(h)
    out = pd.concat(rows, ignore_index=True)
    for t in ("close", "open"):
        a, b_ = out[f"a_{t}"], out[f"b_{t}"]
        out[f"p_{t}"] = (1 / a) / (1 / a + 1 / b_)
        out[f"over_{t}"] = 1 / a + 1 / b_
    T = d.loc[out["idx"], "T"].values
    Mw = d.loc[out["idx"], "Mw"].values
    is_tot = out["market"].values == "tot"
    mA = np.where(out["A_is_w"].fillna(False).astype(bool), Mw, -Mw)
    out["y"] = np.where(is_tot, (T > out["line"].values).astype(float), (mA + out["line"].values > 0).astype(float))
    out["void"] = d.loc[out["idx"], "void"].values
    for c in ("year", "odds_level", "bo", "gender", "surface", "level"):
        out[c] = d.loc[out["idx"], c].values
    return out
