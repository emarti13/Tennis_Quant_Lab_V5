# Total games and game spreads: does the point model beat the books?

Status: research result, 2026-10-20 (the user's spreads/totals request; court pace was
expected to matter here). Script: `scripts/measure_totals_spreads.py`; numbers:
`docs/experiments/data/totals_spreads.json`. Nothing from the sealed period.

## Setup
The point model of `scripts/measure_court_pace.py` (serve/return skill, court pace, leak-free
ordering) gives each match a full distribution of total games and game margin, so it prices
any book's line. 5,678 fixtures in 2026 with both players on 18+ rated matches; Pinnacle's
main line (one per fixture); retirements and walkovers void; integer-line pushes dropped.
Fit January–June, test July to October 12 (about 1,150 lines per market).

## Results
**Total games** (log loss on over/under; lower is better):

| | Log loss |
|---|---|
| Pinnacle open | 0.6900 |
| Pinnacle close | 0.6917 (no better than the open) |
| Point model alone | 0.7229 (worse than the open by 0.033, 95% range 0.018 to 0.049) |
| Open + model | 0.6899 (same as the open) |
| Open + model + pace | 0.6899 |

- The model's average total is 24.9 games; matches averaged 23.4 and Pinnacle's lines 21.8
  (lines sit near the median; 3-set matches make the mean higher). The model is biased high
  by about 1.5 games: shrinking unknown skill toward the average makes matches look more even
  than they are, so it expects too many long matches.
- It does predict the line move: Pinnacle's over price moves toward the model's side by 0.86
  points of probability (95% range 0.71 to 1.03), with or without pace.
- Taking the model's side at execution books' closing lines and prices (their own lines,
  margins included): BetRivers +11% on 98 bets with a 2%+ edge (range −8% to +29%), −6% at a
  5%+ edge; DraftKings and Bet365 similar or worse. No reliable edge.

**Game spreads:** open 0.6937, close 0.6936; model alone 0.7658 (much worse); open + model no
better than the open; the move toward the model's side is not distinguishable from zero.
Execution books: no reliable edge (BetRivers −0% to +5%, DraftKings −9% to −18%).

## What it means
- As built, the point model is not good enough to price totals or spreads: its level is off
  (biased toward long matches) and it knows less than the books' lines.
- Two things worth noting: Pinnacle's total-games close is no better than its open (the
  market learns little before the start on totals), and the model reads the direction of
  totals moves (about 0.9 points). Both say totals are less settled than moneylines.
- What would have to change before a retest: opponent-adjusted serve/return ratings (raw
  shares ignore who the points were won against), calibrating the spread of match lengths to
  real results (the 1.5-game bias), and using the moneyline (Pinnacle's or ours) to set who
  is favoured, so the point model only has to explain how long the match runs.
