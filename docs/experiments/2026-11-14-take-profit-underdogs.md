# Buy the underdog before the match, sell when its price rises (2026-11-14)

**Status:** exploratory. Only matches that started before 2026-11-01 are used; November is kept for registered tests.

**Question (user):** "The underdog starts at $0.30, we buy pre-match and set an ask for $0.50 and it fills, or something similar."

**Test:** `research_tests/inplay_model/run_take_profit.py`, design committed before running (`e9c99da`).

**Data:** Kalshi 1-minute best bid and ask (market-raw releases) for 4,967 underdogs, Aug 9 – Oct 31:
- Challenger 2,597;
- WTA 845;
- ATP 831;
- WTA 125 694.

**Rules:**
- **Entry:** buy at the ask one minute before the true start, taker fee included.
- **Exit:** a resting sell at a target, counted as filled when the in-play best bid reaches it. The maker fee is charged on ATP and WTA match winners only.
- **Otherwise:** held to the result.
- **Ranges:** resample matches.

## How often the underdog rose enough (in-play bid ever reached)

| pre-match price | matches | won | +10¢ | +20¢ | +30¢ |
|---|---|---|---|---|---|
| 10–20¢ | 661 | 13.2% | 53% | 37% | 28% |
| 20–30¢ | 1,089 | 24.7% | 63% | 47% | 40% |
| 30–40¢ | 1,607 | 35.7% | 68% | 58% | 50% |
| 40–50¢ | 1,610 | 44.9% | 73% | 63% | 55% |

The swings the user sees are real and common. Half of all 30–40¢ underdogs were bid at least 30¢ higher at some point in the match.

## P&L per contract (cents; mean, 95% range)

| pre-match price | hold to the end | sell +10¢ | sell +20¢ | sell +30¢ | sell at 50¢ | sell at 60¢ | sell at double |
|---|---|---|---|---|---|---|---|
| 10–20¢ | −4.0 (−6.5, −1.3) | −3.3 | −3.6 | −4.2 | −4.2 | −4.1 | −3.8 |
| 20–30¢ | −2.6 (−5.2, −0.1) | −4.6 | −5.3 | −4.4 | −5.1 | −4.9 | −4.7 |
| 30–40¢ | −1.9 (−4.1, +0.5) | −6.0 | −5.0 | −4.3 | −5.7 | −4.3 | −4.6 |
| 40–50¢ | −2.2 (−4.6, +0.3) | −6.7 | −5.7 | −4.2 | −5.6 | −6.5 | −3.3 |

Fill rates for each target are in the results JSON (for example, 30–40¢ selling at +20¢ filled 58% of the time).

## Why the frequent fills do not add up to a profit

1. **When the order fills you win a little; when it does not you usually lose everything.** For example, 30–40¢ underdogs selling at +20¢:
   - 58% fill and make about +20¢;
   - the other 42% mostly go to 0, a loss of about 36¢.

   With a fair price, every exit rule has the same average as holding. The swings change how the results are spread, not their average.
2. **The entry costs the spread and the taker fee.** That is why holding loses 2–4¢. Pre-match long shots (10–20¢) are also overpriced: they won 13.2% when priced 16.2%.
3. **A resting sell order gets jumped.** Tennis prices move in steps: a break moves the price several cents at once. In the minute a +20¢ order filled, the mid was on average **3.5¢ above** the order (median bid 2¢ above; 16% of fills 5¢ or more). The order sells at its price while the market has already moved past it. That costs about 2¢ per contract on average, and it is why selling early does worse than holding.

## What it means

- Buying the underdog and parking a take-profit order is the **taker** side of the swings. It pays the spread at entry and gets jumped at exit.
- The 2–6¢ it loses per contract is what the other side of the trade earns: whoever posts the bids and asks, and moves them when the score changes.
- So the swings are where the money is, but it goes to the **maker who reprices with the score**. That is the in-play maker test (fair price from `research_kit.inplay`, quotes moved after every point, Challenger and WTA 125 with no maker fee). It is not a better exit target.
- An exit that sells **after** the jump (at the bid once the price has moved through the target) avoids being jumped, but pays half the spread again. Exits like this should be built on the fair price, not on fixed targets.
