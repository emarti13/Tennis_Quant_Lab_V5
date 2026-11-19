# Registration: three in-play rules on Kalshi tennis (fade the favourite, WTA serve-out, WTA breaker)

Registered 2026-11-18 under `docs/superpowers/specs/2026-11-01-rolling-forward-test-amendment.md`.
This file is never edited; a changed rule is a new registration.

## Hypotheses and the decision they would change

The user watches in-play favourites lose from strong positions, and sets turn after a failed serve-out, much more often than the prices suggest.

- **If a rule passes:** it joins the candidates for small real stakes (after the research_kit checks and a second forward window). It would also feed the in-play market maker, which would quote around a fair price that includes the effect.
- **If a rule fails:** it is dropped on Kalshi.

## Where it came from (data before 2026-11-01)

- `docs/experiments/2026-10-20-inplay-calibration.md`: Kalshi, Aug–Oct.
  - In-play favourites at 70–90¢ won less often than priced: 70–80¢ won 69.4% against a price of 75.2%; ATP 70–80¢ won 55%.
  - That file also holds a separate, earlier registration (H1/H2). It is unaffected and is scored on its own at 1,000 matches; 632 so far.
- `docs/experiments/2026-11-18-serve-out-pressure.md`, Match Charting Project: WTA servers serving for the match hold 72.9% against 77.2% expected, 2.2 points below even the "leading" control.
- `docs/experiments/2026-11-18-five-zone.md`, after a WTA failed serve-out:
  - the breaker holds the next game 63.9% against 57.2% expected;
  - the broken server wins the set 66.8% against 70.7% (−4.0, range −5.8 to −2.0);
  - in a deciding set, a fair price drops a median 24 points (WTA) / 33 points (ATP).
- `research_kit/inplay.py` (branch `research/kit`, commit `cd2e843`): the score-based fair price.

## The rules (scored by `scripts/track_inplay_rules.py` at commit `6a8d7b60a2a2c0a4e7dcc99bf78e88edb35c8097`, branch `feat/vm-runner`)

**Common to all three rules:**
- **Data:** the server's live log (`market_history/kalshi/live_scores/`): the score and both players' best bid and ask every 10 seconds, logged since 2026-11-03 with the quote read right after the score.
- **Window:** matches whose first in-play row is after **2026-11-19T00:00:00Z**.
- **Decision rows:** only the first row of a game, with points 0-0 and both markets showing a bid and an ask. Each rule makes at most one decision per match.
- **Fair price:** `research_kit.inplay`.
  - Serve probabilities are solved from the last quote before the match starts, de-vigged as mid / sum of mids.
  - Serve level is fixed by tour: ATP 0.64, Challenger 0.62, WTA 0.56. No surface is inferred.
  - Best of 3 or 5 comes from Kalshi's milestone.
  - The deciding set ends in a 10-point tie-break at the Grand Slams, 7 elsewhere.
- **Buying a player:**
  - price: the cheaper of YES on them (the ask) and NO on the opponent (1 − the opponent's bid);
  - fee: the Kalshi taker fee rounded up to the cent on 100 contracts: ceil(0.07 × 100 × P × (1 − P) × 100) / 100 dollars;
  - size: 100 contracts (paper).
- **Result:** the backed player's market result. `yes` or `no` count; anything else is void.

**The three rules:**

1. **fade** (ATP, WTA and Challenger match winners): a player's de-vigged mid is 70–90¢ **and** at least 3 points above the fair price → buy the other player.
2. **serve_out** (WTA match winners): a player starts a game serving for the match (5-x with x ≤ 4, or 6-5, in the set that would win the match) → buy the receiver.
3. **breaker** (WTA match winners): the game right after a failed serve-out (the server serving for the set or the match was broken) → buy the breaker.

**Reported, not scored:**
- ATP and Challenger decisions under `serve_out` and `breaker`;
- the backed player's mid at the end of the set;
- the fair price at the decision.

## Metric, pass rule, sample, end (each rule separately)

- **Metric:** P&L per contract at settlement, after the fee.
- **Pass:** the 95% range (2,000 resamples of decisions, seed 20261118) is wholly above zero.
- **Minimum sample:** 300 scored decisions.
- **Ends:**
  - fade: at 300 decisions or 2027-06-30;
  - serve_out and breaker: at 300 or 2027-12-31.

  Each is then scored once. If it ends with fewer than 300, it is recorded as inconclusive.
- **Timing:** the WTA is mostly in its off-season until January, so the WTA rules will build slowly until the Australian swing.

**A dry run** on the Nov 10–12 logs (before this registration, not counted) checked the mechanics: 93 / 77 / 33 decisions. No rule was changed after it.

## Not allowed during the window

Changing any of these:
- the price bands, the 3-point gap, or the serve levels;
- the decision rows or the one-per-match limit;
- the tours scored;
- the size, the fee model or the void rule.

Watching the running numbers is allowed; acting on them is not.

## Not in this registration

The in-play market maker (quotes around the fair price on Challenger and WTA 125, re-posted after every point) needs a fill simulation on the order-book logs. It will be a separate registration.
