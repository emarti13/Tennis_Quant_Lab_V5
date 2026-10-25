# In-play point model, checked point by point on charted matches

Run 2026-10-25. Code: `research_tests/inplay_charting/` on the research branch
`claude/clever-fermi-hv34lk`. Every QA check passes, and the 7 known-answer tests pass,
including exact values and Monte Carlo agreement.

**Data:** the Tennis Abstract Match Charting Project (github.com/JeffSackmann/tennis_MatchChartingProject),
CC BY-NC-SA 4.0: attribution required, non-commercial use only. The raw points are not copied
into this repository; the scripts read a local clone.
- 7,877 charted matches from 2011 to 2026, 1.21M points.
- Each match is linked by player names and date to our production Elo, computed before the
  match (91% of charted matches since 2011 link).
- 99% of matches pass a score-consistency check: each point's score follows from the previous
  point's winner. Retirements are excluded.

**Split:** s0 (each tour's server point-win rate) and k (the update weight) were chosen on
2011-19 (2,859 matches). The test is 2020-26 (5,018 matches, 777k points), with nothing tuned
on it.

## The models
- **V0:** pre-match Elo only; ignores the score.
- **V1:** exact iid point model from the current score. Serve rates are s0 ± d, with d set so
  the model's pre-match probability equals Elo's.
- **V2:** V1, with each player's serve rate updated by the serve points played so far:
  (k·p0 + won) / (k + played), k = 200 (best of 25 to 800 on the training matches).

## Results (test 2020-26; log loss averaged over points; ranges resample whole matches)

| Model | Log loss | Calibration slope (1 = calibrated) |
|---|---|---|
| V0, Elo only | 0.622 | 0.77 (0.70, 0.83) |
| V1, point model | 0.481 | **1.02 (0.97, 1.08)** |
| V2, with in-match updating | **0.474** | 0.95 (0.91, 0.99) |

- **V2 vs V1:** V2 improves log loss by +0.0075 (0.0048, 0.0103). It is better on both tours:
  ATP +0.0055, WTA +0.0105.
- **Calibration by band:** from the favourite's side, V1's observed win rate is within about
  1 point of its prediction in every band from 50% to 98%. All ranges include zero.
- **V2 is slightly overconfident,** by about 1 point, which matches its slope of 0.95.

**"Momentum" is information about form, not a bias.** V1 keeps serve rates fixed. Right after
a player breaks serve or wins a set, that player does better than V1 predicts:
- +1.9 points after a break (0.7, 3.0);
- +3.7 points after winning a set (2.3, 4.9);
- −4.7 points after losing a set.

V2 updates serve rates from the points played, and with it these gaps shrink to between −1.4
and +0.7 points, all ranges including zero. A match that is going one way says something about
the players' level on the day. Point-by-point counting captures that; it doesn't need a
separate momentum term.

**Side finding:** on charted matches, mostly top events, the production pre-match Elo is
overconfident (slope 0.77; ATP 0.80, WTA 0.72). That fits Gate 2's finding that Elo adds
nothing beyond Pinnacle.

## Against Kalshi
The charted points have no timestamps. Only 39 charted matches overlap our Kalshi price
history, all WTA from 10 Aug to 9 Sep 2026. Lining points up with prices would mean fitting the
model's path to Kalshi's path, which builds in agreement, so no point-level comparison was
made. What can be compared is the calibration curves, on different matches.

| Favourite price band | Kalshi in play, won vs priced (2026-10-20 study, 2,798 markets) | V1 point model, won vs predicted |
|---|---|---|
| 60-70% | 64.7 vs 65.1 | 64.5 vs 65.0 |
| 70-80% | 69.4 vs 75.2 (range 61.3 to 76.6) | 75.0 vs 75.0 |
| 80-90% | 81.7 vs 85.0 (76.2 to 86.9) | 85.8 vs 85.0 |

- **The model is calibrated in exactly the bands where Kalshi looked overpriced.** But Kalshi's
  70-80% range includes its own price.
- **The populations differ.** The charted matches are mostly top-level events from 2020-26;
  the Kalshi markets are ten weeks in 2026 and include Challengers.
- **The simple rule already failed.** Taking the other side of 70-90c favourites lost after
  fees (−11%, `research_tests/README.md`).

**Verdict:** this is a lead, not an edge. The test that settles it is pre-registered on
2026-10-20: H1/H2 on sealed in-play data, evaluated once at 1,000 matches. A model-versus-Kalshi
test needs live points with timestamps (a licensed feed), run in shadow with no money: the model
at each point against Kalshi's bid and ask, acting only when the gap is bigger than the
roughly 4c round-trip cost (spread plus fees).
