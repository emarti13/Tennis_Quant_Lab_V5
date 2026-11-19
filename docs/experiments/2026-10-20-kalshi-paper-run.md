# Kalshi Challenger paper market making: results of the live run

Status: research result, 2026-10-20. The planned 7-day run was stopped after about 31 hours
at the user's request (Claude usage); this note replaces the planned 2026-10-26 report.
Code: `scripts/paper_trade_kalshi.py`; logs: `market_history/kalshi/paper/`. No orders were sent.

## Coverage
- 2026-10-19 07:36Z to 2026-10-20 14:38Z, in 100-minute shifts with about 20-minute gaps:
  847 polls, 202 Challenger markets watched, 142 settled with results.
- One interruption: a container restart at about 04:00Z on 2026-10-20 (2 minutes lost).
- The first runs (before 07:36Z on 2026-10-19) were discarded: Kalshi's occurrence time is
  about 3 hours after the real start, so they quoted into live matches. The trader now stops at
  the event milestone's start and on Kalshi's live status.

## The books
- The spread was 1c at the median; 3c or wider 9.6% of the time, 5c or wider 2.6%.
- Contracts already waiting at the best price (the queue ahead of a new order): median 514 on
  the bid, 1,015 on the ask.
So professional quoting already sits at 1c with deep queues; the wide books of the August
replay (`docs/experiments/2026-10-19-kalshi-making-sim.md`) were rare in this run.

## Results (142 settled markets)
| Setting | Matches filled | Contracts | Marked at last pre-start mid | After maker fee | Held to result |
|---|---|---|---|---|---|
| 3c each side of mid | 7 | 282 | +$4.39 | +$3.34 | −$27.32 |
| 5c each side of mid | 3 | 54 | +$0.44 | +$0.22 | +$30.15 |
| Join the best price (queue-aware, from 2026-10-20 00:40Z) | 51 | 2,981 | +$3.79 | **−$6.38** | +$144.05 |

"Marked" is the spread earned net of being picked off; "held" adds the match results (luck at
this size). The maker fee is Kalshi's schedule (0.0175 × P × (1 − P)), not confirmed for tennis.

## Verdict
- Quoting 3–5c around the mid barely fills: those orders sit behind thousands of contracts.
- Joining the 1c queue fills, and earns about 0.1c a contract before the maker fee and less
  than nothing after it: what the spread pays is about what informed traders take.
- Copying Kalshi's mid is not an edge in these markets. Market making here needs a fair price
  that knows more than the book (the model lean, or an in-play model), which was not tested.
