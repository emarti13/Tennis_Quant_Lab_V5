# Can they serve it out? Pressure on serve, women and men (2026-11-18)

**Status:** exploratory. Historical data, all from before 2026-11-01.

**Hypothesis (user):** "women can't serve out when the pressure rises".

**Test:** `research_tests/pressure/run_serve_out.py`, pre-registered and pushed (`0083325`) before the run. The fix after that commit (duplicate match ids in the match list) is mechanical.

**Data:** the Match Charting Project (github.com/JeffSackmann/tennis_MatchChartingProject, CC BY-NC-SA 4.0, research use, last commit 2026-09-18), point by point:

| tour | matches | service games |
|---|---|---|
| WTA | 4,239 | 89,187 |
| ATP | 7,519 | 201,694 |

Tie-breaks are excluded.

**Method:**
- **Expected hold:** the server's own share of serve points won in that match, leaving out the game, converted to a hold chance with points treated as independent.
- **Control:** "leading" games (ahead 3-x or 4-x, not yet serving for the set), because players who lead have usually been serving above their level.
- **Ranges:** resample matches.

## Results (deviation = held minus expected, in points)

| state | WTA games | WTA held / expected | WTA deviation | ATP games | ATP held / expected | ATP deviation |
|---|---|---|---|---|---|---|
| serving for the match | 3,226 | 72.9% / 77.2% | **−4.3 (−5.8, −2.8)** | 5,247 | 85.6% / 87.7% | −2.1 (−3.1, −1.2) |
| serving for the set | 7,294 | 72.3% / 74.8% | −2.5 (−3.5, −1.5) | 14,103 | 84.7% / 85.5% | −0.9 (−1.5, −0.3) |
| leading (control) | 12,365 | 72.0% / 74.1% | −2.1 (−2.8, −1.3) | 22,589 | 83.9% / 84.9% | −1.1 (−1.5, −0.6) |
| 5-5 | 1,911 | 68.8% / 67.5% | +1.3 (−0.7, +3.4) | 5,762 | 79.7% / 82.0% | −2.3 (−3.3, −1.3) |
| serving to stay in the set | 8,635 | 60.9% / 58.1% | **+2.8 (+1.8, +3.8)** | 21,304 | 77.4% / 76.1% | +1.2 (+0.7, +1.8) |
| other | 58,982 | 64.9% / 64.0% | +0.9 | 137,936 | 79.2% / 78.7% | +0.5 |

**Pressure effect** (state minus the leading control):

| | WTA | ATP |
|---|---|---|
| **PRIMARY:** serving for the set | −0.4 (−1.7, +0.9) | +0.2 (−0.6, +1.0) |
| serving for the match | **−2.2 (−3.8, −0.4)** | −1.1 (−2.2, 0.0) |

**PRIMARY, women minus men (serving for the set):** −0.6 (−2.1, +0.9).

## Labels

- **Serving for the set, beyond the "leading" dip: ruled out above about 2 points,** for women and men. The pre-registered primary does not support "women can't serve out the set".
- **Serving for the match: a real shortfall for women.** They hold 72.9% against 77.2% expected, 2.2 points below even the leading control. For men it is half that and borderline. This was a secondary measure; it is a **candidate**.
- **Leaders under-hold and trailers over-hold, in both tours:**
  - players serving to stay in the set hold more than their serve predicts (WTA +2.8, ATP +1.2);
  - leaders hold less (WTA −2.1, ATP −1.1).

  Part of this is selection (a leader's own in-match serve rate is flattered), but the trailing side's over-performance is not explained by that. Matches come back more often than in-match serve rates suggest, especially on the WTA. This fits the measured overpricing of in-play favourites at 70–90¢ on Kalshi.

## What it means for money

- The tennis effect exists at the match-point stage, mainly for women. Whether Kalshi already prices it is a separate question.
- A failed hold at serving-for-the-match moves the match price only a few points, because the server usually stays a strong favourite. The money test therefore needs Kalshi's in-play prices at those moments.
- The fair-price model (`research_kit.inplay`) uses the pre-match price, not in-match serve rates, so it does not share the selection problem.
- **Next:** a registered forward test on the server's live logs. At the start of a WTA (and, separately, ATP) serving-for-the-match game, compare Kalshi's price with the fair price and buy the receiver. Score it on the price after the game and on the result, after the taker fee. Volume returns with the January swing.


## Robustness check, 2026-11-19 (added after the results; see `docs/experiments/2026-11-19-set-length.md`)

The expected values above use the server's serve rate over the whole match. When a set reaches 5-x, that rate is flattered by the same set. Redone with each player's serve rate from their **other sets only** (matches with at least two sets):

| | WTA | ATP |
|---|---|---|
| serving for the match: held / expected | **65.4% / 69.3%: −3.9 (−6.2, −1.5)**, n = 1,702; survives | 83.1% / 84.0%: −1.0 (−2.2, +0.3) |
| serving for the set, all | +4.2 (+2.8, +5.6): players serving for a set are in a good spell | +2.3 |
| after a failed serve-out, breaker holds next | 66.9% / 65.1%: +1.8 (−1.0, +4.6); **the earlier +6.7 was mostly selection** | −0.4 |
| after a failed serve-out, broken server wins the set | **61.6% / 65.4%: −3.8 (−6.8, −0.8)**, n = 1,250; survives | −0.2 |

**Labels after the check:**
- the WTA serving-for-the-match shortfall is a candidate; it is robust, and it backs the registered `serve_out` rule;
- the WTA broken server losing the set more than expected is a candidate; it is robust, and it backs the registered `breaker` rule;
- the breaker's "solid hold" boost is not supported;
- ATP: none of these.
