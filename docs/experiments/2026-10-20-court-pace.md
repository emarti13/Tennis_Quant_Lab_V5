# Court pace and serve/return: do they beat or predict Pinnacle's opener?

Status: research result, 2026-10-20, asked by the user (court speed: Brussels, Almaty, Lyon).
Script: `scripts/measure_court_pace.py`; numbers: `docs/experiments/data/court_pace.json`.
Nothing from the sealed period.

## What was built (our own results only)
- Serve and return skill per player: share of service and return points won, one-year half
  life, shrunk toward the tour average (300 points), in log-odds.
- Court pace per event: service points won beyond what the players' skills predict, per point,
  from earlier editions of the same tournament (tour, level, name) and the rounds of this
  edition already played, qualifying included; shrunk toward zero (3,000 points).
- A point model: serve-point chances from tour average + serve skill − return skill (+ pace),
  turned into a match probability (games, tiebreak sets, best of 3 or 5).
Same visibility rules as the leak-free Elo.

## Results
1. **Court pace is real and stable.** An edition's own pace against what its earlier editions
   predicted: correlation 0.91 over 755 editions since 2015 (Grand Slams 0.95, Masters 0.92,
   250s 0.90, Challengers 0.91). The spread between courts is about ±0.04 log-odds on a
   service point (roughly ±1 point of serve percentage).
2. **It barely moves who wins.** On 10,213 matches in 2026 (both players with 18+ rated
   matches): Elo 0.6272 log loss; point model 0.6477 (worse than Elo by 0.020, 95% range
   0.016 to 0.026); pace adds −0.0001 (−0.0002 to +0.00004).
3. **Nothing on top of Pinnacle's opener** (fit January–June, test July to October 12, 1,280
   fixtures; open 0.6169, close 0.6127):

   | Model on top of the open | Log loss | vs open | Close moves toward its side |
   |---|---|---|---|
   | Elo + fatigue (before) | 0.6165 | −0.0004 (−0.0054 to +0.0042) | +0.69 points (0.47 to 0.91) |
   | + point model | 0.6165 | −0.0004 | +0.68 |
   | + point model + pace | 0.6172 | +0.0003 | +0.64 |

   Pace adds nothing to the lean (−0.05 points, −0.17 to +0.06).

## What it means
- Court speed changes how matches are played much more than who wins. A faster court gives
  both players more holds; the better player's edge shrinks only slightly (the point model:
  a 2-point serve edge is a 60% favourite on a slow court, 58% on a fast one). The market
  already prices this, or it is too small to matter for the winner.
- Where pace should matter is **totals and spreads** (more holds = more games and tiebreaks).
  The price store holds book total-games and game-spread lines (about 100,000 rows). That is
  the natural next test, and the start of the spreads/totals work the user asked for.
- The point model needs opponent adjustment before it can compete with Elo on winners
  (raw serve/return shares ignore who the points were won against).
