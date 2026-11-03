# Pinnacle to Kalshi: Kalshi's tennis prices sit within a point of Pinnacle's

Date: 2026-11-03. Research on data before 2026-11-01. Script:
`research_tests/pinnacle_kalshi/run_pinnacle_kalshi.py`; output: `research_tests/pinnacle_kalshi/results.json`.

## Question

With Pinnacle as information and Kalshi as the only venue: when Pinnacle's de-vigged price is
away from what Kalshi lets you buy at, does buying on Kalshi make money after Kalshi's fee? And
does Kalshi follow Pinnacle late enough to act on?

## Data

Kalshi minute bid/ask candles (Aug to mid-Oct 2026) and the price store's Pinnacle moneyline
price standing at 12 h, 6 h and 1 h before the start and at the close, each with its quote time.
Only 187 matches have both: the Pinnacle store is thin for August and September (about 490
and 220 fixtures), and Kalshi's candles end mid-October. Kalshi quotes: latest candle at the
decision time, at most 30 minutes old, spread at most 5¢.

## Results

| Checkpoint | Matches | Mean gap, Pinnacle fair vs Kalshi mid | Bets with edge ≥ 2 pts after fee |
|---|---|---|---|
| 12 h | 105 | 0.85 pts | 0 |
| 6 h | 169 | 0.92 pts | 2 |
| **1 h (primary)** | **183** | **0.83 pts** | **0** |
| close | 72 | 0.89 pts | 1 |

With any positive edge at all (≥ 0 pts after the fee), there are only 8-23 bets per checkpoint,
and their returns are noise (for example 1 h: −0.8¢ per contract, −14 to +16, n = 21).
Between the checkpoint and the start, Kalshi's mid moves toward Pinnacle's fair by 20-45% of the
small gap.

The pre-registered checks (outcomes drawn from Kalshi's or Pinnacle's chance) could not run:
the primary cell had no bets.

## What it means

Kalshi's pre-match tennis prices sit within about one point of Pinnacle's fair price. Once the
spread and fee are paid, there is nothing to take. Kalshi looks priced off the sharp books. **Not
registered.**

This is consistent with the long-shot finding (`docs/experiments/2026-11-03-kalshi-taker-side.md`).
If Kalshi tracks Pinnacle, Kalshi carries Pinnacle's own long-shot bias. At a bookmaker that bias
is smaller than the margin, but Kalshi's fee is small at extreme prices. That is the one rule now
under a registered forward test.

The sample is small. The server's 5-minute Kalshi quotes, together with the live OddsPapi prices,
will cover it going forward if this needs revisiting.
