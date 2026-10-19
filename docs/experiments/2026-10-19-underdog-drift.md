# Does the underdog's price rise before the match? (research)

Status: research result, 2026-10-19, asked by the user ("if an underdog starts at 46c, is
there profit assuming it rises to 50 or above?"). Script: `scripts/measure_underdog_drift.py`;
numbers: `docs/experiments/data/underdog_drift.json`. Nothing from the sealed period.

## 1. Pinnacle, open to close (12,099 matches, January to October 12)
| Underdog at the open | n | Mean move to close | Rose in |
|---|---|---|---|
| under 30% | 4,968 | +0.64 points (0.50 to 0.79) | 50% |
| 30–40% | 3,523 | +0.24 (0.07 to 0.40) | 51% |
| 40–46% | 2,248 | −0.01 (−0.23 to +0.21) | 46% |
| 46–50% | 1,279 | −0.17 (−0.47 to +0.14) | 45% |

Long shots drift up a little (the public backs them as the start nears); near-even underdogs
do not move on average, and fall slightly more often than they rise.

## 2. Kalshi, the trade itself (1,374 markets, August 10 to October 12)
Buy the underdog at the best ask standing 12, 6 or 2 hours before the start; sell at the best
bid just before the start, or with a resting sell 4c above the entry; or hold. Taker fees
(7% × P × (1 − P)) included. Return per dollar staked, T-6h entry:

| Underdog at entry | n | Mid move to the start | +4c sell filled | Sell at the start | Resting sell +4c | Hold to result |
|---|---|---|---|---|---|---|
| under 30c | 456 | +0.2c | 11% | −17.2% | −14.4% | −22.2% |
| 30–40c | 408 | 0.0c | 9% | −12.7% | −11.6% | −4.4% |
| 40–46c | 298 | −0.3c | 11% | −11.6% | −10.7% | −14.9% |
| 46–50c | 162 | −0.3c | 9% | −10.4% | −9.7% | −6.1% |

T-12h and T-2h entries are the same picture (every version loses 10–15%; ranges in the json).
ATP, WTA and Challenger all lose by about the same amount.

## What it means
- The underdog does not rise on average before the start (Kalshi mid move about 0c; Pinnacle
  flat for 40–50% underdogs). A +4c rise happens in only 6–16% of markets.
- The round trip costs more than any move: two taker fees (about 1.7c each at 40c) plus the
  spread is roughly 10–13% of the stake. A pre-match swing would need to average about 4–5c
  in our favour just to break even, and it averages zero.
- Holding to the result loses too (long shots are overpriced, the earlier band study).
- Not pursued further. Of the ideas so far, only a maker (who earns the spread instead of
  paying it, and pays no taker fee) showed a positive result (2026-10-19 Kalshi simulation).
