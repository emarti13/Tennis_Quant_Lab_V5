# Fatigue shocks: the market reacts before the start, and the close prices most of it

Date: 2026-10-31. Research; 2014-2025 (the sealed period is untouched). No model is fitted: the
test asks whether the market's own price is right on one kind of match.
Script: `research_tests/info_speed/run_fatigue_shock.py`; output: `research_tests/info_speed/fatigue_results.json`.

## Question

Part of the "information speed" study the user asked for: which tennis information does the
market price slowly? First case: one player comes off a much longer previous match in the same
event than the other ("tired" = at least 45 minutes more, pre-registered).

## Data

The Kaggle odds join (bet365 open and close, Betfair close, best close) with the warehouse's
match durations; ATP and WTA main and Challenger; 40,994 matches where both players had a
previous match in the same event with known minutes, neither ended by walkover or retirement;
12,755 with a gap of 45+ minutes.

## Checks (research_kit)

All pass on the final run: swap-source, time-travel (previous match from an earlier round of
the same event), planted shift (−3 points planted, −3.4 found), market null (+0.3, range
includes 0), known answers (Betfair close log loss 0.600).
**The first run failed two checks**: 127 player-rounds were listed twice in one event (duplicate
rows or lucky losers), which made "previous match" ambiguous, in 53 cases not an earlier
round. Those players' events are now left out. The first run's numbers were not used.

## Results (tired player's side; residual = won − de-vigged price)

| | n | Residual (pts) | 95% range | Back the fresh player |
|---|---|---|---|---|
| **PRIMARY: gap ≥ 45 min, Betfair close** | 12,755 | **−0.6** | −1.4 to +0.2 | **−2.7%** (−4.5 to −1.0) after 2% commission |
| bet365 OPEN | 13,030 | **−2.2** | −3.0 to −1.4 | −2.5% (margin) |
| bet365 close | 13,019 | −0.9 | −1.7 to −0.1 | −4.7% |
| best price across books, close | 13,387 | −0.6 | −1.4 to +0.2 | +0.6% (−1.2 to +2.4) |
| Control: gap < 10 min, Betfair close | 6,898 | −0.6 | −1.7 to +0.5 | |

bet365's price moves **−1.25 points against the tired player between open and close** (range
−1.32 to −1.19). By gap at Betfair close: 0-15 −0.7, 15-30 −0.1, 30-45 −0.4, 45-60 +0.6, 60-90
−1.7 (−2.8 to −0.5), 90+ −0.6: no clean dose-response; the 60-90 bin is one of six.
By level (gap ≥ 45, Betfair close): ATP −0.4, WTA −0.8, Challenger −0.6, all ranges include 0.

## What it means

- **The opening price under-rates fatigue by about 2 points; the market corrects most of it
  before the start** (1.25 points of movement), and at Betfair's close nothing significant is
  left. This is information arriving and being priced: many openers are posted before the
  previous match is played, so they cannot know its length.
- Betting the fresh player at the close loses about the fee. At bet365's open it loses its
  margin (the 2-point mispricing is smaller than about 5% margin).
- The money question is the price **between** the end of the previous match and the start:
  how long the fatigue takes to get into the price. This data has no timestamps. Next: the 2026
  price store (timestamped checkpoints per book, true start times) with match end times
  (start + minutes), and Kalshi's price history, to measure the price at the first moment the
  previous match's length is known.
