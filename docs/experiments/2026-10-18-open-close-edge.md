# Can our information beat Pinnacle's opening price? (edge search 1)

Status: research result, 2026-10-18. Script: `scripts/measure_open_close_edge.py`; numbers:
`docs/experiments/data/open_close_edge.json`.

## Question
Tennis lines open a median 16h before the start, soon after the previous round. If the
opener has not yet priced the previous round's load (minutes, sets, a deciding set,
retirements), our leak-free Elo plus the leak-free fatigue features
(`v5_fatigue_features.py`) should beat the opener, or at least predict which way it moves.

## Data
2026 fixtures with a Pinnacle moneyline open and close (de-vigged, Pinnacle lam), joined to
results; both players with at least 18 rated matches (the pricing minimum). Fit January-June
(4,596 fixtures), test July to 2026-10-12 (1,280). Nothing from the sealed period.
Model: logistic regression on top of the open (open as a fixed offset) with the Elo gap and
11 fatigue differences, each with a missing flag.

## Results (test set)
| Log loss | Value |
|---|---|
| Pinnacle open | 0.6169 |
| Pinnacle close | 0.6127 |
| Our Elo alone | 0.6306 |
| Open + Elo + fatigue | 0.6165 (open minus 0.0004, 95% CI -0.0050 to +0.0042) |

1. The opener is already nearly as good as the close: the market learns only 0.004 between
   open and close. Our model does not beat the opener.
2. Our information does predict the move. The close moves toward the side our model
   favours by 0.7 probability points on average (95% CI 0.5 to 0.9); 1.0 points when the
   model differs from the open by 2 points or more. Strongest on Challenger (1.0 to 1.4
   points, CI clear of zero); ATP 0.5 to 0.7; WTA not distinguishable from zero.
3. That move is smaller than the spread a taker pays. Taking the model's side at the
   opening price, measured against the de-vigged Pinnacle close (fees and spread included):
   | Book | Open overround | Model side CLV | Random side CLV |
   |---|---|---|---|
   | Pinnacle | 3.7% | -3.2% | -4.3% |
   | BetRivers | 6.0% | -7.3% | -7.4% |
   | DraftKings | 6.0% | -6.6% | -6.9% |
   So no taker edge at the open.

## What it means
- Fatigue and Elo carry real information the opener has not priced, worth about 1 point of
  probability, mostly on Challengers. A taker cannot use it: the spread is 3.7 to 6 points.
- A market maker does not pay the spread, it earns it. Our signal is the kind a maker uses
  to lean quotes: quote tighter on the side the line will move toward, wider on the other.
  Whether that pays depends on Kalshi spreads, fills and fees, measured next
  (`market_history/kalshi/`).
- Not a production change. Nothing here feeds pricing.
