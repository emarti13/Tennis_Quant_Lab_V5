"""Independent checks of the 2026 DraftKings-opener bets saved by check_dk_open.py.

1. Prices and outcomes re-read from the raw files: price_points for DraftKings' open and
   Pinnacle's close, and winners from v5_market_results (the official route) instead of our
   match-table join.
2. Duplicates, price ranges, timing of DraftKings' open vs start and vs Pinnacle's open.
3. Null test: outcomes drawn from Pinnacle's no-vig close for the same bets (a world where the
   close is right). Its mean is the return the closing-line value alone explains; the p-value is
   how often that world matches the observed ROI. (Shuffling outcomes across bets is not a valid
   null here: the bets have different prices.)
"""
import glob
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "research_tests"))
import run_market_models as rm  # noqa: E402
from qa import QA  # noqa: E402
from v5_market_results import load_fixture_winners  # noqa: E402

bets = pd.read_pickle(os.path.join(rm.SCRATCH, "bets_draftkings_open_ens05.pkl"))
qa = QA("dk_open_bets")
qa.count("bets", len(bets))
qa.zero("duplicate fixtures among bets", bets.fixture_id.duplicated().sum())
fx = pd.concat([pd.read_csv(f) for f in sorted(glob.glob(os.path.join(ROOT, "market_history/fixtures/*.csv")))])
fx = fx[fx.resolution == "ok"].drop_duplicates("fixture_id", keep="last")
fx["start"] = pd.to_datetime(fx.cutoff_utc, utc=True)
qa.check("all bet fixtures start before the seal", (fx.set_index("fixture_id").loc[bets.fixture_id, "start"]
                                                    < pd.Timestamp("2026-10-13", tz="UTC")).mean(), 1.0, 1.0)
pp = pd.concat([pd.read_csv(f) for f in sorted(glob.glob(os.path.join(ROOT, "market_history/price_points/*.csv")))])
pp = pp[(pp.market_group == "moneyline") & pp.fixture_id.isin(bets.fixture_id)].drop_duplicates(
    ["fixture_id", "bookmaker", "side"], keep="last")
dk = pp[pp.bookmaker == "draftkings"].pivot(index="fixture_id", columns="side", values="open_price")
dkt = pp[pp.bookmaker == "draftkings"].drop_duplicates("fixture_id").set_index("fixture_id").open_utc
pin = pp[(pp.bookmaker == "pinnacle")].copy()
pin.loc[pin.close_stale.astype(str) == "True", "close_price"] = np.nan
pinc = pin.pivot(index="fixture_id", columns="side", values="close_price")
pino = pin.drop_duplicates("fixture_id").set_index("fixture_id").open_utc
# which fixture side was bet: model side A is p1 when a_is_p1
side = np.where(bets.side_a == bets.a_is_p1, "p1", "p2")
raw_price = np.array([dk.at[f, s] for f, s in zip(bets.fixture_id, side)])
qa.check("bet price equals raw DraftKings open price", np.isclose(raw_price, bets.price).mean(), 0.999, 1.0)
o1, o2 = pinc.loc[bets.fixture_id, "p1"].to_numpy(), pinc.loc[bets.fixture_id, "p2"].to_numpy()
f1 = (1 / o1) / (1 / o1 + 1 / o2)
pin_side = np.where(side == "p1", f1, 1 - f1)
qa.check("Pinnacle close fair equals raw recompute", np.isclose(pin_side, bets.pin_close).mean(), 0.999, 1.0)
w = load_fixture_winners(fx[fx.fixture_id.isin(bets.fixture_id)], base=ROOT)
w = w[~w.void_for_measurement].drop_duplicates("fixture_id").set_index("fixture_id")
have = bets.fixture_id.isin(w.index).to_numpy()
qa.check("bets with an official winner (v5_market_results)", have.mean(), 0.95, 1.0)
won_off = np.array([w.at[f, "winner_side"] == s for f, s in zip(bets.fixture_id[have], side[have])])
qa.check("our outcome agrees with the official winner", (won_off == bets.won.to_numpy()[have]).mean(), 0.995, 1.0)
ret = np.where(bets.won, bets.price - 1, -1.0)
ret_off = np.where(won_off, bets.price.to_numpy()[have] - 1, -1.0)
qa.check("bet prices within 1.01..30", ((bets.price > 1.01) & (bets.price < 30)).mean(), 1.0, 1.0)
lead = (pd.to_datetime(fx.set_index("fixture_id").loc[bets.fixture_id, "cutoff_utc"], utc=True).to_numpy()
        - pd.to_datetime(dkt.loc[bets.fixture_id], utc=True).to_numpy()) / np.timedelta64(1, "h")
dk_first = (pd.to_datetime(dkt.loc[bets.fixture_id], utc=True).to_numpy()
            < pd.to_datetime(pino.loc[bets.fixture_id], utc=True).to_numpy())
qa.check("DraftKings open is before the start", (lead > 0).mean(), 1.0, 1.0)
rng = np.random.default_rng(1)
# null with outcomes drawn from Pinnacle's close fair (what a no-edge world looks like for these prices)
null_pin = np.array([np.where(rng.random(len(bets)) < bets.pin_close, bets.price - 1, -1.0).mean() for _ in range(5000)])
R = {"qa": qa.rows, "roi_ours": round(float(ret.mean()), 4), "roi_official_winners": round(float(ret_off.mean()), 4),
     "n_official": int(have.sum()),
     "hours_dk_open_before_start_median": round(float(np.median(lead)), 1),
     "share_dk_open_before_pinnacle_open": round(float(np.mean(dk_first)), 3),
     "null_pinnacle_fair_mean": round(float(null_pin.mean()), 4),
     "null_pinnacle_fair_p_value": round(float(np.mean(null_pin >= ret.mean())), 4),
     "win_rate": round(float(bets.won.mean()), 4), "mean_pinnacle_close_prob": round(float(bets.pin_close.mean()), 4),
     "mean_model_prob": round(float(bets.p_model.mean()), 4), "mean_price": round(float(bets.price.mean()), 3)}
qa.save(HERE)
json.dump(R, open(os.path.join(HERE, "results_qa_dk_open.json"), "w"), indent=1)
print(json.dumps({k: v for k, v in R.items() if k != "qa"}, indent=1))
