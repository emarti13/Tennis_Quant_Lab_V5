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
  retired again in 2.6% of these matches, against a base rate of 3.3%.
- **Walkover recently:** +1.4 points (−2.3 to +5.0). 2016-2021 alone was +4.3, which triggered the
  pre-registered money test; backing the flagged player in 2022-2025 then lost 7.9% (−19% to +4%).
  That is noise.

## What it means

Recent injuries show up in the price. Players who retired recently are not more likely to retire
again, so there is no settlement edge either. **Closed.**
