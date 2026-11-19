# Retirement risk: the market prices a recent retirement or walkover

Date: 2026-11-03. Research, 2016-2025 odds. Script: `research_tests/retirement/run_retirement.py`;
output: `research_tests/retirement/results.json`.

## Question and method (pre-registered in the script)

Does the price miss a player who recently retired hurt or gave a walkover? From the history file,
each player's matches are ordered by tournament date, then round (never file order). Two flags:

- **Retired recently:** retired in one of the previous two matches, within 30 days. 3.6% of matches.
- **Walkover recently:** gave a walkover within 30 days. 0.7%.

84,956 matches. All checks pass: swap-source, planted edge (−0.0024 found, −0.0024 expected),
market null, known answers.

## Results

- **PRIMARY:** both flags on top of Betfair's close, 2022-2025: +0.00005 log loss (−0.00001 to
  +0.00012). Nothing.
- **Retired recently:** the flagged player won 0.3 points less than the close (−1.9 to +1.3), and
  retired again in 2.6% of these matches. **Correction (audit, 2026-11-03):** the first version of
  this note compared 2.6% with 3.3%, but 3.3% is the share of matches that end in any retirement.
  The right comparison is one given player retiring, which happens in 1.6% of matches. Recently
  retired players retire again about **1.6 times as often** (79 cases against about 50 expected,
  z ≈ 4.2); walkover-flagged players 1.4 times as often.
- **Walkover recently:** +1.4 points (−2.3 to +5.0). 2016-2021 alone was +4.3, which triggered the
  pre-registered money test; backing the flagged player in 2022-2025 then lost 7.9% (−19% to +4%).
  That is noise.

## What it means

The price residual rules out a bias above about 2 points for recently retired players (the
minimum detectable effect was 2.3 points). But they **are** more likely to retire again (1.6×).
That matters wherever a retirement voids a bet or settles differently (some bookmakers, Kalshi).
Whether the price already allows for it there is untested. Verdict: **price bias ruled out above
about 2 pts; retire-again risk confirmed; settlement effect untested.** Walkover flag: inconclusive
below about 5 points.
