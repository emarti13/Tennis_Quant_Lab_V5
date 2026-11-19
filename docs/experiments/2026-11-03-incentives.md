# Incentives from the rankings calendar: an end-of-season effect

Date: 2026-11-03. Research, 2016-2025 odds (the Kaggle join with Betfair and bet365). Script:
`research_tests/incentives/run_incentives.py`; output: `research_tests/incentives/results.json`.

## Question

Ratings-based prices treat every week the same; players do not. Do the market's prices miss
how much a player has to play for? Seven flags were set before any result was read, each from
information public before the match (rank and points at the event, the calendar, entry type):

- **Slam main-draw bubble:** ranked 95-125 within 42 days of a Slam entry deadline.
- **Slam qualifying bubble:** ranked 220-260 in the same window.
- **Defending:** reached the semi-final or better at the same event last year.
- **Pre-Slam:** top 30 in an event starting 15 days or less before a Slam.
- **Season end:** ranked 31-90 after October 20.
- **Wildcard.**
- **Qualifier or lucky loser.**

## Data and checks

84,956 matches: Challenger 41,062, ATP main 22,599, WTA main 21,295. The ranking history comes
from `.v5_history_cache`, joined on event, round and both names. All checks pass:

- **Swap-source:** the first run failed it because only the odds file's sides were swapped, not
  the history file's. That was an error in the check, now fixed.
- **Planted edge:** −0.0024 found against −0.0024 expected.
- **Market null:** +0.00007.
- **Known answers:** Betfair close log loss 0.608.

## Results

- **PRIMARY:** the seven flags on top of Betfair's close, 2022-2025, log loss −0.00015 (−0.00031
  to 0.0000, 39,684 matches). It is tiny and at the edge of significance.
- **Season end:** the flagged player won 4.1 points less than the close said (−6.4 to −1.6,
  1,301 matches, 2016-2025); 2016-2021 alone −2.5 (−5.8 to +0.9). That crossed the
  pre-registered 2-point bar for a money test on 2022-2025:
  - **back the opponent at Betfair close after the 2% commission: +12.3% (+0.6% to +25.0%, 678 bets);**
  - at bet365 close: +11.1% (−0.4% to +23.3%).
  - By level: ATP main −4.4 (−7.5 to −1.1), Challenger −5.6 (−10.2 to −1.2), WTA −1.7
    (−6.6 to +3.2). By year: negative in 7 of 10 seasons; 2020 and 2021 (COVID calendars)
    positive. The flagged players' average closing chance was 52%, so this is not the
    long-shot pattern.
- **Qualifiers and lucky losers** beat the close by 1.2 points (0.3 to 2.1); 2016-2021 alone
  1.0 (−0.2 to 2.3). Below the 2-point bar, so no money test.
- **The other flags** (main and qualifying bubbles, defending, pre-Slam, wildcard): within about
  ±1.5 points of the close, ranges including zero.

## Reading it

A plausible mechanism: late in the season, players ranked 31-90 often have nothing left to
qualify for and are tired, while their opponents (often lower-ranked, chasing points before the
cut-offs) are motivated. The market prices them on their ranking as usual. The ROI is above the
toolkit's 10% "too good" alarm. The audit found no leak: the flag uses only the rank at the event
and the date. But the selection is one flag of seven, and the range nearly touches zero, so this
is a candidate, not a finding.

## Next

A registered forward test on executable prices: this season's run from now to the end of the
2026 season, then 2027's from October 20, at Kalshi (the venue) with the fee. It needs a live
rank per Kalshi player. Few matches qualify each season (about 130 a year with odds here), so
reaching the 300-match minimum needs more than one season.
