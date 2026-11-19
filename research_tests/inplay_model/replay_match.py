"""Replay one logged match through the score-based fair price (mechanics check).

Usage:  python research_tests/inplay_model/replay_match.py LIVE_LOG_CSV_GZ EVENT_TICKER [TOUR SURFACE INDOOR]

Prints, at each change of games, the score, who serves, the fair chance for competitor 1
(research_kit.inplay, serve probabilities solved from the last pre-match quote) and Kalshi's
de-vigged mid. TOUR / SURFACE / INDOOR default to ATP Hard indoor; in a tracker they must come
from the master schedule (v5_fixture_resolution), never guessed.
"""
import sys, pandas as pd, numpy as np
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research_kit import inplay as ip
PT = {0: 0, 15: 1, 30: 2, 40: 3, 50: 4}
d = pd.read_csv(sys.argv[1]); ev = sys.argv[2]
m = d[d.event_ticker == ev].sort_values('polled_utc')
c1 = m.competitor_1.dropna().iloc[0]
inp = m[m.match_status.isin(['1st_set', '2nd_set', '3rd_set', '4th_set', '5th_set'])]
pre = m[(m.polled_utc < inp.polled_utc.iloc[0]) & m.bid_1.notna() & m.bid_2.notna()].iloc[-1]
mid = lambda r, s: (r[f'bid_{s}'] + r[f'ask_{s}']) / 2
p0 = mid(pre, 1) / (mid(pre, 1) + mid(pre, 2))
tour, surf, indoor = (sys.argv[3], sys.argv[4], sys.argv[5].lower() in ('1', 'true', 'i', 'indoor')) if len(sys.argv) > 5 else ('ATP', 'Hard', True)
pa, pb = ip.solve_serve(p0, ip.serve_level(tour, surf, indoor))
print(f"{ev}: pre-match {p0:.3f} -> serve pA {pa:.4f} pB {pb:.4f}")
last = None
for r in inp.itertuples():
    g1, g2 = int(r.games_1), int(r.games_2)
    tb = g1 == 6 and g2 == 6
    p1, p2 = (int(r.points_1), int(r.points_2)) if tb else (PT.get(int(r.points_1)), PT.get(int(r.points_2)))
    if p1 is None or p2 is None or pd.isna(r.server):
        continue
    key = (r.sets_1, r.sets_2, g1, g2)
    if key == last:
        continue
    last = key
    fair = ip.p_match(pa, pb, (int(r.sets_1), int(r.sets_2)), (g1, g2), (p1, p2), r.server == c1)
    mk = (r.bid_1 + r.ask_1) / 2 / ((r.bid_1 + r.ask_1) / 2 + (r.bid_2 + r.ask_2) / 2) if r.bid_1 == r.bid_1 and r.bid_2 == r.bid_2 else float('nan')
    print(f"{r.polled_utc[11:19]} sets {r.sets_1}-{r.sets_2} games {g1}-{g2} pts {p1}-{p2} srv {'A' if r.server == c1 else 'B'}  fair {fair:.3f}  kalshi {mk:.3f}  gap {100*(mk-fair):+.1f}")
