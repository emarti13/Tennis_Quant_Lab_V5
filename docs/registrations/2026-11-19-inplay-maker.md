# Registration: a market-following in-play market maker on Kalshi tennis (calm points only)

Registered 2026-11-19 under `docs/superpowers/specs/2026-11-01-rolling-forward-test-amendment.md`.
This file is never edited; a changed rule is a new registration.

## Hypothesis and the decision it would change

The money in in-play swings goes to whoever provides the bids and asks, if they get out of the way when the score is about to move the price. The test: a maker that sits 1¢ inside Kalshi's market on both sides, only on calm points, earns more spread than it loses to being picked off. It is scored on Challenger and WTA 125 matches, where makers pay no fee.

- **If it passes:** small real stakes, after the research_kit checks and a second forward window.
- **If it fails:** in-play making from this score feed is dropped.

## Where it came from, and what shaped it

- `docs/experiments/2026-11-14-take-profit-underdogs.md` (data before 2026-11-01): a resting order gets jumped. In the minute a take-profit filled, the mid was 3.5¢ past the order.
- **A first design, quoting around the score-based fair price, was dropped before registration.** On a dry run on Nov 16–18 (after 2026-11-01, so not evidence) it lost through one-sided fills: it was betting the model against the market. That observation is why this design follows the market instead. This registration's window starts after this commit, so the score stays clean.
- **The user's two points (2026-11-19):**
  - the price moves with every point and often reverses within a game (0-30, then two aces, 30-30), so this rule quotes only on calm points;
  - faster traders and feeds see points first, so this rule reports the feed lag.
- **The feed lag on the Nov 17–18 dry run** (mechanics only, not counted): 34% of a point's price move happened before this score feed showed the point (10,092 points). The dry run printed only mechanics (fills and feed lag), no profit or loss.

## The rule (scored by `scripts/track_inplay_maker.py` at commit `c749b650613777b1070480e2fcb766972fe8b7b6`, branch `feat/vm-runner`)

**Markets:**
- **Scored:** Challenger (KXATPCHALLENGERMATCH) and WTA 125 (KXWTACHALLENGERMATCH) match winners, no maker fee. The live logger follows WTA 125 from the same commit series (`34ec10b`).
- **Reported, not scored:** ATP and WTA match winners, with the maker fee of 0.0175 × P × (1 − P) per contract.

**Window:** matches whose first in-play row is after **2026-11-20T00:00:00Z**.

**When to quote.** At an in-play row of the server's live log (every 10 seconds), on each of the two markets, only when all of these hold:
1. both markets are quoted;
2. the market's spread is at least 3¢;
3. the point score is unchanged since the previous row;
4. the next point is calm: the score-based fair price (`research_kit.inplay`, serve probabilities from the last pre-match quote at a fixed level per tour) moves by at most 4 points between winning and losing it.

**What to quote:**
- a bid at the market's best bid + 1¢ and an ask at its best ask − 1¢;
- 10 contracts each;
- only while the market's net position stays within ±50 contracts.

Quotes live from that row until the next one, at most 30 seconds.

**Fills:**
- A public Kalshi trade in that interval with the taker selling YES at or below our bid fills our bid.
- A taker buying YES at or above our ask fills our ask.
- Fills are at our price, up to the trade's size.

**Result:** positions are held to settlement (yes = 1, no = 0; anything else is void).

## Metric, pass rule, sample, end

- **Metric:** P&L per match, in dollars and in cents per contract filled.
- **Pass:** the 95% range of the mean P&L per match (2,000 resamples of matches, seed 20261119) is wholly above zero.
- **Minimum sample:** 300 scored matches with at least one fill.
- **Ends:** at 300, or on 2027-06-30 if fewer, then scored once. If it ends with fewer than 300, it is recorded as inconclusive.
- **Reported alongside (not part of the pass rule):**
  - fills;
  - the 60-second mark-out;
  - ATP and WTA with the maker fee;
  - the feed lag.

## Not allowed during the window

Changing any of these:
- the spread minimum, the 1¢ improvement, the calm-point rule or the 4-point swing limit;
- the size, the position cap or the fill rule;
- the series scored;
- the serve levels.

Watching the running numbers is allowed; acting on them is not.
