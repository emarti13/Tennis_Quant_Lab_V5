# Are Kalshi's prices right during matches? (and a pre-registered test)

Status: research result, 2026-10-20, asked by the user ("I buy at 70c and lose way too often";
"an underdog wins the first set and the odds flip"). Script:
`scripts/measure_inplay_calibration.py`; numbers: `docs/experiments/data/inplay_calibration.json`.
Kalshi tennis markets, August 10 to October 12 (2,798 markets, 66,908 in-play samples: the mid
every 5 minutes from the true start until 2c/98c). Ranges resample whole matches. Returns are
buying at the ask and holding, Kalshi's taker fee included.

## Results
**Pre-match (one minute before the start):** about right; favourites win slightly more than
priced (70–80c: priced 74.6%, won 78.7%), as in the Pinnacle band study.

**In play:**

| Price | Matches | Priced | Won (95% range) | Buy at the ask and hold |
|---|---|---|---|---|
| 10–20c | 1,391 | 15.3% | 19.5% (13.9–26.2) | +11% (−21 to +45) |
| 20–30c | 1,476 | 24.9% | 30.6% (22.7–38.8) | +13% (−15 to +42) |
| 30–40c | 1,570 | 35.0% | 35.4% | −5% |
| 40–60c | ~1,575 | 45–55% | about right | −1% to −8% |
| 60–70c | 1,573 | 65.1% | 64.7% | −4% |
| **70–80c** | 1,477 | **75.2%** | **69.4% (61.3–76.6)** | **−10% (−19.5 to −0.8)** |
| 80–90c | 1,392 | 85.0% | 81.7% (76.2–86.9) | −6% (−12 to −0.5) |

In-play favourites at 70–90c won less often than their price, in ATP and WTA markets most
(70–80c: ATP won 55% of the time, WTA 70%; Challenger 80%, about right). Underdogs at 10–30c
won more often than priced, but those ranges include the price.

**The user's two cases:**
- *Underdog before the match, now the favourite* (e.g. won the first set), at 50–70c: won 54% and
  61% against prices of 57.5% and 65% (buying them: about −10%). The flip is slightly overdone.
- *Favourite before the match, now the underdog*, at 30–50c: won 40% and 46% against 35% and 42.5%
  (buying them: +7% and +2%, ranges include zero).

## Caveats
- One ten-week window, and ten price bands were looked at: some of this is chance.
- 1-minute bars; a real order in play meets a moving book and a delay.
- "Hold to the end" is the simplest trade; nothing here was tuned.

## Pre-registered (locked 2026-10-20, before looking at any sealed-period in-play data)
On Kalshi ATP and WTA match markets in play, sampled the same way, from 2026-10-13 on:
- **H1:** sides priced 70–90c (mid) win less often than their price (95% range of won − price
  entirely below zero).
- **H2 (money):** buying the other side at its ask at those moments and holding returns more
  than zero after the taker fee (95% range entirely above zero).
Evaluated once, when at least 1,000 matches have in-play samples in that band, with
`scripts/measure_inplay_calibration.py` restricted to those dates and tours. Nothing else
about the rule changes.
