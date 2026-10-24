# Data and result audit (2026-10-23)

Why: the intransitivity bugs on 2026-10-23 were caught only because the paper gave a reference
number. This audit adds checks that do not depend on luck and re-derives the results the Gate 1
report rests on. Code and numbers are on the research branch `claude/clever-fermi-hv34lk`.

## 1. Built-in checks (`research_tests/qa.py`)
Each research script now checks its own data against ranges known independently of the result,
stops when one fails, and saves `qa_<name>.json` next to its results.
- **Kaggle join:**
  - source winner-first: 100%;
  - join rate: 81.3%;
  - duplicate keys: 0;
  - A win share after re-orientation: 0.498;
  - odds in range: ≥ 99.93% per book;
  - Bet365 close log loss: 0.601.
- **Market models:**
  - rows: 97,175;
  - A win share: 0.499;
  - consensus close log loss: 0.595;
  - close beats open: 0.0093;
  - odds rows found in the feature table: 99.4%. This guards against mixing caches built on
    different days.
- **Betting:** backing every side loses about the margin (Bet365 −9.1%, three-book average −8.0%).
- **Intransitivity:**
  - 99.4% of target matches scored;
  - no NaN;
  - 36.7% with a prior meeting (paper 42%);
  - no negative values.

All pass on the current data.

## 2. Known-answer tests
`research_tests/intransitivity/test_intrans.py`, 5 tests, all pass:
- a pure three-way cycle has no transitive part;
- a transitive triangle has no cyclic part;
- the two-player case;
- no history gives zero;
- the visibility rule (a match never sees its own event or an unfinished one).

The first-server module already had 6 such tests.

## 3. Reconciliation with the other session's Kaggle join
- **Overlap:** on the 100,695 matches both joins found, Bet365 winner odds and match dates
  agree 100%.
- **Their extras:** the other join finds 6,069 more, mostly name variants ours misses (for
  example "Granollers-Pujol", "Kate Makarova"). Ours is more conservative; spelling does not
  depend on the result, so no bias.
- **Our extras:** the 728 only ours found are the same matches under an older key format.
- **Key format:** some TennisMyLife ids were written as `216133.0` in the 2026-10-21 load and as
  `216133` now. Player ids are normalised before ratings (`normalize_tml_id`), so no player's
  history was split; only match-key text differed. Lesson: research caches must be rebuilt
  together (now checked).

## 4. Blind replications (fresh agents, written spec, no access to our code or results)
**Base facts: agree.**

| Fact | Ours | Blind replication |
|---|---|---|
| Bet365 underdogs [2.2, 4.0), 2014-19 / 2020-25 | −7.9% / −5.4% | −8.9% / −7.1% (all non-ITF rows, not only joined) |
| Bet365 overround | about 6.7% | 6.76% |
| Pinnacle close beats open, 2026 | 0.0055 | 0.0056 (0.0036, 0.0076) |
| First server inferable, ATP / Challenger / WTA | 46.5 / 45.8 / 45.1% | 48.1 / 46.3 / 47.6% |
| Winner served first, among inferable | 64 / 62 / 61% | 65.5 / 61.9 / 63.4% |

The replication found 3.5% of ATP and WTA matches whose service-game counts fit neither
hypothesis. They are concentrated in Grand Slams 2017-18 (statistics coded 0, tiebreaks counted
as service games). Our pipeline marks these as no data or uses break counts, so no conclusion
used them; it is a known data-quality pocket.

**DraftKings opener: does not replicate with a simpler model.**
- **Model:** Elo plus DraftKings' opener, logistic blend fitted Jan-Mar, evaluated Apr-Aug.
- **Log loss:** the gain over the opener is 0.0012 (−0.0005, +0.0030).
- **EV > 0, 683 bets:** closing-line value −2.0% (−2.8, −1.1), negative every month and on every tour.
- **EV > 5%:** only 23 bets, driven by two Geneva fixtures whose DraftKings openers were far from
  Pinnacle's close (0.75 vs 0.34; 0.48 vs 0.80).
- **Data fact:** DraftKings prices stop on 2026-08-09, so "Jun-Oct" in our earlier split is
  really Jun-Aug.

## 5. Audit of our own DraftKings-opener bets (633 bets, ensemble, EV > 5%)
- **Data:** prices and outcomes re-read from the raw files and from `v5_market_results`
  (the official route) agree 100% (ROI +7.8% with official winners vs +8.0%).
- **Null test:** under Pinnacle's no-vig close the same bets return +2.3% on average (the
  closing-line value). The observed +8.0% exceeds that only at p = 0.05. The rest is
  consistent with luck.
- **Concentration:** 82% of the total closing-line value comes from the top 5% of bets, where
  DraftKings' opener is far from Pinnacle's close. Our bets include both Geneva fixtures.

  | Bets kept (gap between DraftKings' opener and Pinnacle's close) | n | Closing-line value | ROI |
  |---|---|---|---|
  | All | 633 | +2.3% (1.3, 3.4) | +8.0% |
  | Gap < 0.15 | 624 | +1.5% (0.7, 2.2) | +7.2% |
  | Gap < 0.10 | 586 | +1.0% (0.3, 1.7) | +6.5% |

- **By month, closing-line value:** Mar +1.6%, Apr +3.0%, May +6.3%, Jun +2.1%, Jul +0.6%, Aug +0.4%.

**Reading:** much of the DraftKings "edge" is catching openers far from the market (stale or
erroneous prices). Books can void those under palpable-error rules, so they may not stand.
On normal prices the closing-line value is about +1%, it fades through the summer, it is
before fees, and it needs the richer feature model (the Elo-based model finds none). Also, **DraftKings is not an execution book** (CLAUDE.md), and the collector requests
Pinnacle, Bet365 and BetRivers from September on, so this result is not executable as it stands.
C1 survives only as a shadow test at Bet365's and BetRivers' openers, with a pre-declared cap
on the price gap.

## Found after the audit (2026-10-24)
Research comparisons used multiplicatively de-vigged market prices, while production uses
`v5_devig` with each book's measured λ. The multiplicative split makes the market look about
0.001 log loss worse than it is, so model gains were overstated. Corrected numbers:
`2026-10-24-gate1-gaps.md`.

## What this audit does not cover
- The market-model ensemble itself has not been re-implemented blind (heavy).
- The post-toss handicap estimate (model-implied, not measured) and Pinnacle's partial
  repricing of the toss have one implementation each.
