# Travel and body clock: jet lag points the right way, but it is too rare to bet

Date: 2026-11-03. Research, 2016-2025 odds. Scripts: `research_tests/travel/geocode_events.py`
(673 of 674 tournament names located with Open-Meteo's free geocoder; `research_tests/travel/events.csv`)
and `research_tests/travel/run_travel.py`; output: `research_tests/travel/results.json`.

## Question

The fatigue tests used match minutes. This one uses the clock. For each player, take the previous
match in the odds data that started before this one (real start times, so the ordering cannot leak
results), and the UTC offset of each match's location. Flags, set before any result was read:

- **Jet lag east / west:** moved 5+ hours east or west since a previous match 5 days ago or less.
- **Body night:** this match starts between 00:00 and 07:00 on the clock of the player's previous
  location (3+ hours of shift, 5 days or less).
- **Night × jet lag:** a match at 21:00 or later local time for a jet-lagged player.

## Checks

All pass. The first run failed swap-source because of an error in the check (it swapped the
recomputed flags a second time), now fixed. Planted edge −0.0023 against −0.0024 expected; market
null +0.00003; Betfair close log loss 0.608.

## Results (84,946 matches; flags are rare: 0.2-0.4% of matches each)

| Flag | Flagged player won − Betfair close, 2016-2025 | 2016-2021 only |
|---|---|---|
| Jet lag east | −3.2 pts (−8.1 to +1.6), n=361 | +2.0 (−4.7 to +8.6) |
| Jet lag west | −4.2 pts (−9.3 to +0.7), n=319 | −2.3 (−9.1 to +4.8) |
| Body night | −4.1 pts (−10.9 to +2.7), n=189 | −1.6 |
| Night × jet lag | −9.1 pts (−23 to +4.6), n=40 | −8.0 |

- **PRIMARY:** the flags on top of Betfair's close, 2022-2025: −0.00004 log loss (−0.00008 to +0.00001).
- Every flag points toward jet lag hurting, but none is significant, and jet lag east changes sign
  between periods. Its pre-registered money test (backing the flagged player, chosen by the
  2016-21 sign) lost 22% in 2022-25. The money tests for the other flags (backing the opponent)
  are noise on 20-170 bets.

## What it means

Jet lag probably costs a few points, as one would expect, but it affects about 1 match in 300 with
odds. The sample can neither prove it nor support a bet. **Not registered.** It may be worth
including as a small feature in a blended model, where its rarity costs little.
