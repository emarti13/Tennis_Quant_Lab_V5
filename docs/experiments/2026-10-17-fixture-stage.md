# Fixture stage: main draw or qualifying (2026-10-17)

`v5_fixture_stage.py`; measured by `scripts/check_fixture_stage.py` (output
`docs/experiments/data/fixture_stage.json`). User decision 2026-10-17: the stage is a
**label, not a filter**. Every fixture is priced; qualifying fixtures stay out of official
recommendations until the model has been measured on qualifying results.

## Why it is needed

OddsPapi lists qualifying and main-draw matches under the same tournament with no round
field (its fixture records were checked: no round or stage). TennisMyLife publishes main
draws only for Challengers and the WTA, so on 2026 data a Challenger or WTA fixture with a
TennisMyLife result is main draw, and one without is (almost always) qualifying. That gives
an answer key.

## What the first idea would have cost

Leaving the whole start day unpriced (the first proposal) would have dropped about 475
Challenger and 240 WTA main-draw matches in January–August (user: "you give up a lot of
matches"). Main-draw share on the start day: Challenger 38%, WTA 72%.

## The calendar differs by level (WTA, 2026; share of fixtures that are main draw)

| Day vs listed start | Grand Slam | WTA 1000 | WTA 500 | WTA 250 |
|---|---|---|---|---|
| day before | 100% | 64% | 17% | 9% |
| start day | 99% | 35% | 81% | 89% |
| day after | 99% | 57% | 97% | 99% |

## The rule (see the module docstring)

1. Kalshi's round text when Kalshi lists the match ("Qualification Round 1", "Round Of 32").
2. The calendar: Grand Slams are main draw from the Sunday before the listed start; 1000s
   mix qualifying and main draw on the day before, the start day and the day after; other
   events mix on the start day only.
3. On a mixed day:
   - qualifying if the players already played in this edition. At tour level both of them
     must have (one who already played is a qualifier meeting a direct entrant). At
     Challengers and WTA 125 either is enough (OddsPapi often misses a qualifier's first
     match; requiring both let 9.5% qualifying through as main);
   - else main draw if the edition had earlier matches;
   - else unknown.

## Result (January–September 2026 fixtures in the price store)

| | Challenger | WTA |
|---|---|---|
| Main-draw fixtures labelled main | **4,268 of 4,290 (99.5%)** | **1,609 of 1,649 (97.6%)** |
| Qualifying labelled main (share of "main") | 188 (4.2%) | 33 (2.0%) |
| Labelled unknown | 104 | 89 |

Steps taken to get there: the start-day rule alone gave Challenger 99.5% / 4.2% and WTA
90% / 4.3%; the per-level calendar raised WTA to 92% / 1.2%; "both players" at tour level
to 97.6% / 2.0%.

## Limits

- ATP tour-level fixtures use the same rule but are not measured here (TennisMyLife
  includes ATP qualifying, so it is no answer key for them); a later check can use its
  round column.
- The Kalshi override is not yet measured: the price store has no August 10 to September
  fixtures until the gap backfill reaches them.
- A label only: a mislabelled main-draw match is still priced and shown, just not an
  official recommendation until qualifying is validated.
