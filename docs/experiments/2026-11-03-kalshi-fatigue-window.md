# Fatigue window on Kalshi: a small drift after listing, no money after costs

Date: 2026-11-03. Research on data before 2026-11-01. Script:
`research_tests/info_speed/run_kalshi_fatigue_window.py`; output: `research_tests/info_speed/kalshi_fatigue_results.json`.

## Question

The bookmaker test (`docs/experiments/2026-10-31-fatigue-shock.md`) found the market prices a
fatigue shock between the open and the close, but had no timestamps. Kalshi's minute candles
and market close times give the clock: a match market closes when the result is in, so a
player's previous market close is when the previous match's length becomes known (T0). How fast
does the next match's price move after that, and is anything left to take after costs?

## Data

Kalshi minute bid/ask candles and market list, Aug-Oct 2026. 485 matches where both players
had a previous Kalshi match in the 48 hours before (length 30-400 minutes) and the next market had
a real book (YES spread ≤ 0.05) before the start. 195 in the primary set (tired player's previous
match 45+ minutes longer), 85 controls (gap < 10 minutes).

## Design changes before any result was read (recorded in the script)

- v1 kept 37 matches: results were taken from the price file (a subset) and a quote was required
  15 minutes after T0. **Kalshi usually lists the next match after the previous one ends**
  (median 7.7 hours after T0 in the primary set), so that quote rarely exists.
- v2 entered on the first candle after listing: those are placeholder quotes (for example bid
  0.02 / ask 0.36). Backing the fresh player lost about 31¢ per contract in every set, control
  included, and the planted check failed. v2's numbers were not used.
- v3 (reported): entry at the first candle at or after T0 + 15 minutes with a YES spread of
  at most 0.05.

## Results (primary set, n = 195)

| | Result | 95% range |
|---|---|---|
| **Drift: last pre-start mid − entry mid** | **−1.3 points** against the tired player | −2.7 to −0.03 |
| Same, control (gap < 10) | +0.9 | −1.8 to +3.3 |
| Back the fresh player at entry, hold, after the taker fee | −2.1¢ per contract | −8.2 to +4.5 |
| Tired player won − entry mid | −0.8 points | −7.3 to +5.2 |
| Tired player won − last pre-start mid | +0.5 points | −5.7 to +6.2 |

Checks: market null passes (+0.5¢ found, −1.5¢ expected, range includes it). **The planted check
fails for power, not a bug**: a planted 3-point edge comes out as −0.5¢ (−6.9 to +5.8). With
195 matches the range is about ±6¢, so the test cannot resolve an edge of a few points.

## What it means

- Same picture as the bookmakers: fatigue keeps moving into the price before the start (about
  1.3 points after Kalshi lists the match), and the last pre-start price has it.
- Kalshi lists the next match hours after the previous one ends, so the early window where a
  marathon match is not yet priced is mostly not tradeable on Kalshi.
- The drift is smaller than the spread plus fee. No money, and the sample is too small to find a
  few-point edge. **Not registered.** The server's 5-minute quotes will show listing times and
  first prices going forward if this is revisited.
