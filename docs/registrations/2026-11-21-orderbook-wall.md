# Registration: back the side a dominant resting order ("wall") is holding on Kalshi tennis, before the start

Registered 2026-11-21 under `docs/superpowers/specs/2026-11-01-rolling-forward-test-amendment.md`.
This file is never edited; a changed rule is a new registration.

## Hypothesis and the decision it would change

A large resting order that dominates one side of a market's book is informed money. The price moves toward it before the start.

The idea comes from an r/algobetting post the user shared on 2026-11-05: exchange walls on Novig and ProphetX, backed at sportsbooks priced no worse than the wall. That post reported 2,095 paper bets and 81% beating the close. Totals and spreads carried the edge; moneylines did not.

- **If it passes:** small real stakes on the signal, after the research_kit checks and a second forward window.
- **If it fails:** the wall signal is dropped for Kalshi tennis.

## Where it came from

- `docs/experiments/2026-11-06-orderbook-walls-first-look.md`: the October top-of-book logs could not measure it (void).
- Full order books have been logged every 5 minutes since 2026-11-06 (`scripts/log_kalshi_live.py`, the 10 levels nearest the best price on each side).
- A dry run on Nov 17–19 checked the mechanics only: 32 bets. No results were looked at, and those bets are not counted.
- **Adaptation (set before any result):**
  - On Kalshi the side totals are dominated by orders resting at 1–2¢, so a side's size is taken over its 10 logged levels.
  - Buying below the wall's own bid is impossible on the same exchange, so the post's "no worse than the wall's price" becomes "at most 3¢ above the wall's price".

## The rule (scored by `scripts/track_wall_rule.py` at commit `09aab63d489443fbdcb3805e26c82ed0827b1129`, branch `feat/vm-runner`)

**Markets:** every logged Kalshi tennis market:
- match winners (ATP, WTA, Challenger, WTA 125);
- ATP game spreads;
- ATP and WTA total games;
- ATP and WTA set winners.

**Window:** book rows after **2026-11-22T00:00:00Z** and at least 60 minutes before the match's scheduled start. The start is the Kalshi milestone `start_date` of the match-winner event with the same match code.

**A wall exists** on one side (YES bids or NO bids) when, over the 10 logged levels of that side:
1. the largest level is at least 55% of the side's size;
2. it is at least 3 times the next largest level;
3. the side's size is at least twice the other side's;
4. the wall is worth at least $600 (contracts × its price).

**The wall's side:** a YES-bid wall wants YES; a NO-bid wall wants NO.

**Bet (paper):**
- at the first row with a wall, per market; one decision per market, and a first wall that fails the price check means no bet;
- buy the wall's side at its ask (YES ask = 1 − best NO bid; NO ask = 1 − best YES bid), only if that ask is at most 3¢ above the wall's price;
- Kalshi taker fee, rounded up to the cent on 100 contracts;
- 100 contracts.

**Close:** the last book row before the scheduled start. p_close of the side is the mid of the two best prices.

## Metric, pass rule, sample, end

- **Primary metric:** CLV per contract = p_close − price − fee.
- **Pass:** the 95% range (2,000 resamples of matches, seed 20261121) is wholly above zero.
- **Minimum sample:** 300 bets.
- **Ends:** at 300 bets, or on 2027-06-30 if fewer, then scored once. If it ends with fewer than 300, it is recorded as inconclusive.
- **Reported alongside (not part of the pass rule):**
  - P&L at settlement;
  - the share of bets that beat the close;
  - results by market type.

## Not allowed during the window

Changing any of these:
- the wall thresholds, the 10-level window or the 3¢ cap;
- the 60-minute lead or the one-per-market limit;
- the markets, the size, the fee model or the void rule.

Watching the running numbers is allowed; acting on them is not.
