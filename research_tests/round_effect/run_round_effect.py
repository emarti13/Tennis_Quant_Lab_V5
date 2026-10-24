"""Replication of a 2026-10-22 Pinnacle blog claim ("Nishikori", FavOrDog.io data): ATP 250/500/1000
main draw, best of 3, 2017-2026, favourite and underdog by Pinnacle's close.
  first round: favourites -1.7%, underdogs -5.9%; second round to final: -3.8% / 0.0%;
  second round with the favourite coming off a bye: favourites -6.5%, underdogs +3.5%;
  the pattern is absent in 2010-2016.

Our data is independent of theirs:
  * 2014-2025: Kaggle odds (no Pinnacle). Favourite by the de-vigged four-book consensus close.
    Returns at the consensus fair price (margin removed, so only the favourite/underdog split
    matters) and at Bet365's actual close.
  * 2026 (before the seal): OddsPapi Pinnacle close, returns at Pinnacle's actual price.

First round = the event's earliest main-draw round. Bye = a player with no earlier main-draw
match in the event, playing after the first round. Retired matches and walkovers are excluded.
Run: python research_tests/round_effect/run_round_effect.py -> results.json
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "research_tests"))
sys.path.insert(0, os.path.join(ROOT, "research_tests", "kaggle_odds"))
import v5_baseline_elo as be  # noqa: E402
from qa import QA  # noqa: E402
import run_market_models as rm  # noqa: E402

LEVELS = {"250", "500", "M"}
DEPTH = {"R128": 7, "R64": 6, "R32": 5, "R16": 4, "QF": 3, "SF": 2, "F": 1}
RNG = np.random.default_rng(22)


def match_context():
    """Per match key: first-round flag, and whether each player arrives off a bye."""
    m = be.load_matches(ROOT)
    m = m[(m.tour == "MEN") & m.level.astype(str).isin(LEVELS) & m["round"].isin(DEPTH)].copy()
    m["depth"] = m["round"].map(DEPTH)
    first = m.groupby("tid").depth.transform("max")
    m["first_round"] = m.depth == first
    long = pd.concat([m[["tid", "depth", "key", "winner_key"]].rename(columns={"winner_key": "p"}),
                      m[["tid", "depth", "key", "loser_key"]].rename(columns={"loser_key": "p"})])
    earlier = long.groupby(["tid", "p"]).depth.transform("max")         # the player's first (deepest-number) round
    long["bye"] = (long.depth == earlier) & (long.depth < long.groupby("tid").depth.transform("max"))
    bye = long.groupby(["key", "p"]).bye.first()
    return m.set_index("key"), bye


def boot(r, reps=2000):
    r = np.asarray(r, float)
    i = RNG.integers(0, len(r), (reps, len(r)))
    mm = r[i].mean(1)
    return {"n": int(len(r)), "roi": round(float(r.mean()), 4), "lo": round(float(np.percentile(mm, 2.5)), 4),
            "hi": round(float(np.percentile(mm, 97.5)), 4)}


def gap_boot(fav, dog, reps=2000):
    """Underdog ROI minus favourite ROI, resampling matches (one fav and one dog bet per match)."""
    fav, dog = np.asarray(fav, float), np.asarray(dog, float)
    i = RNG.integers(0, len(fav), (reps, len(fav)))
    g = dog[i].mean(1) - fav[i].mean(1)
    return {"gap_dog_minus_fav": round(float(dog.mean() - fav.mean()), 4),
            "lo": round(float(np.percentile(g, 2.5)), 4), "hi": round(float(np.percentile(g, 97.5)), 4)}


def table(df, price_fav, price_dog):
    """df: one row per match with fav_won, segment columns; returns ROI rows."""
    fav = np.where(df.fav_won, df[price_fav] - 1, -1.0)
    dog = np.where(~df.fav_won, df[price_dog] - 1, -1.0)
    out = {}
    segs = {"all": np.ones(len(df), bool), "first_round": df.first_round.to_numpy(),
            "later_rounds": ~df.first_round.to_numpy(),
            "second_round_fav_bye": (df.depth_from_first == 1).to_numpy() & df.fav_bye.to_numpy(),
            "second_round_fav_played_r1": (df.depth_from_first == 1).to_numpy() & ~df.fav_bye.to_numpy(),
            "third_round_on": (df.depth_from_first >= 2).to_numpy()}
    for k, s in segs.items():
        if s.sum() < 30:
            continue
        out[k] = {"fav": boot(fav[s]), "dog": boot(dog[s]), **gap_boot(fav[s], dog[s]),
                  "median_fav_odds": round(float(np.median(df[price_fav][s])), 2),
                  "median_dog_odds": round(float(np.median(df[price_dog][s])), 2)}
    # the article's key contrast: (dog - fav) later minus (dog - fav) first round
    f, l = segs["first_round"], segs["later_rounds"]
    reps = 2000
    i1 = RNG.integers(0, f.sum(), (reps, f.sum())); i2 = RNG.integers(0, l.sum(), (reps, l.sum()))
    d1 = dog[f][i1].mean(1) - fav[f][i1].mean(1); d2 = dog[l][i2].mean(1) - fav[l][i2].mean(1)
    out["swing_later_minus_first"] = {"swing": round(float((dog[l].mean() - fav[l].mean()) - (dog[f].mean() - fav[f].mean())), 4),
                                      "lo": round(float(np.percentile(d2 - d1, 2.5)), 4),
                                      "hi": round(float(np.percentile(d2 - d1, 97.5)), 4)}
    return out


def kaggle_frame(ctx, bye):
    D = rm.load()
    D = D[D.key.isin(ctx.index)].copy()
    c = ctx.loc[D.key]
    D["first_round"] = c.first_round.to_numpy()
    D["depth_from_first"] = (c.groupby("tid").depth.transform("max").to_numpy() - c.depth.to_numpy())
    pa = rm.sig(D.mkt_close.to_numpy())
    a_fav = pa >= 0.5
    D["fav_won"] = np.where(a_fav, D.y == 1, D.y == 0)
    D["fair_fav"], D["fair_dog"] = 1 / np.where(a_fav, pa, 1 - pa), 1 / np.where(a_fav, 1 - pa, pa)
    D["b365_fav"] = np.where(a_fav, D.bet365_A, D.bet365_B); D["b365_dog"] = np.where(a_fav, D.bet365_B, D.bet365_A)
    fav_key = np.where(a_fav, D.a_key, D.b_key)
    D["fav_bye"] = [bool(bye.get((k, p), False)) for k, p in zip(D.key, fav_key)]
    return D


def pinnacle_2026(ctx, bye):
    mk = pd.read_pickle(os.path.join(rm.SCRATCH, "fs_market.pkl"))
    mk = mk[mk.key.isin(ctx.index)].copy()
    o1, o2 = mk.ml_close_pinnacle_p1.to_numpy(float), mk.ml_close_pinnacle_p2.to_numpy(float)
    ok = np.isfinite(o1) & np.isfinite(o2)
    mk = mk[ok].copy(); o1, o2 = o1[ok], o2[ok]
    c = ctx.loc[mk.key]
    mk["first_round"] = c.first_round.to_numpy()
    mk["depth_from_first"] = c.groupby("tid").depth.transform("max").to_numpy() - c.depth.to_numpy()
    p1_fav = o1 <= o2
    mk["fav_won"] = np.where(p1_fav, mk.y == 1, mk.y == 0)
    mk["pin_fav"], mk["pin_dog"] = np.where(p1_fav, o1, o2), np.where(p1_fav, o2, o1)
    fav_key = np.where(p1_fav, mk.a_key, mk.b_key)          # fs_market a_key is player1
    mk["fav_bye"] = [bool(bye.get((k, p), False)) for k, p in zip(mk.key, fav_key)]
    return mk


def main():
    ctx, bye = match_context()
    qa = QA("round_effect")
    qa.check("share of events whose first round is R32 or R64 or R128", ctx.groupby("tid").depth.max().isin([5, 6, 7]).mean(), 0.95, 1.0)
    qa.check("share of matches in the first round", ctx.first_round.mean(), 0.40, 0.55)
    D = kaggle_frame(ctx, bye)
    qa.count("Kaggle matches 2014-2025 in the universe", len(D))
    qa.check("favourite win rate (consensus close)", D.fav_won.mean(), 0.62, 0.72)
    qa.check("second-round favourites on a bye: share", D[D.depth_from_first == 1].fav_bye.mean(), 0.2, 0.7)
    R = {"source_claim": {"first_round": {"fav": -0.017, "dog": -0.059}, "later": {"fav": -0.038, "dog": 0.0},
                          "r2_fav_bye": {"fav": -0.065, "dog": 0.035}, "years": "2017-2026, Pinnacle close"}}
    for label, mask in (("2017_2025", D.kyear.between(2017, 2025)), ("2014_2016", D.kyear.between(2014, 2016)),
                        ("2022_2025", D.kyear.between(2022, 2025))):
        sub = D[mask.to_numpy()]
        R[f"kaggle_{label}_fair"] = table(sub, "fair_fav", "fair_dog")
        sb = sub[np.isfinite(sub.b365_fav) & np.isfinite(sub.b365_dog)]
        R[f"kaggle_{label}_bet365"] = table(sb, "b365_fav", "b365_dog")
    P = pinnacle_2026(ctx, bye)
    qa.count("2026 matches with a Pinnacle close", len(P))
    R["pinnacle_2026"] = table(P, "pin_fav", "pin_dog")
    qa.save(HERE)
    json.dump(R, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    for k, v in R.items():
        if k == "source_claim":
            continue
        print("==", k)
        for s, c in v.items():
            if s == "swing_later_minus_first":
                print(f"  swing later-first: {c}")
            else:
                print(f"  {s:28s} n={c['fav']['n']:6d} fav {c['fav']['roi']:+.3f} dog {c['dog']['roi']:+.3f} "
                      f"gap {c['gap_dog_minus_fav']:+.3f} [{c['lo']:+.3f},{c['hi']:+.3f}]")


if __name__ == "__main__":
    main()
