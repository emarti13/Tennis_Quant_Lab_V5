# De-vig measurement on our 2026 closes (2026-10-16)

`scripts/measure_devig.py`; full output in `docs/experiments/data/devig_measurement.json`.
Spec §2.5, rebuild plan Step 3 (user decision 2026-10-13).

## Data

- Price store (`market_history/`), moneyline closes for Pinnacle, BetRivers and
  DraftKings: the January–August backfill plus the first live pulls. Bet365 has only 70
  results before the sealed period so far.
- **Only fixtures that started before 2026-10-13** (sealed period; CLAUDE.md).
- Closes whose book stopped quoting more than 60 minutes before the start are left out
  (spec §5.4). Also measured 6 hours before the start.
- Winners joined through our ids (`v5_market_results`): same master-schedule edition and
  same two `player_id`s.

## Winner coverage: 8,589 of 12,366 resolved fixtures (69%)

First review (user, 2026-10-16: "makes me think there are some underlying errors"). Checked:

- **A real bug, fixed:** 74 TennisMyLife WTA rows have no player id (all of Eastbourne and
  Bad Homburg among them). The alias table keys such players as `name:<folded name>`, but
  the join looked them up by id only. It now uses the registry's own key
  (`v5_player_registry.tml_node`).
- **The join itself works where TennisMyLife has the match.** ATP: 2,577 of 2,582 (99.8%).
  For Challengers and WTA the missing ones are the qualifying days: missing share by day of
  the edition, Challenger: Saturday/Sunday 100%, Monday 62%, Tuesday 5%, later 0–1%; WTA:
  64% the day before, 32% the first day, 2–6% after.
- **TennisMyLife has no Challenger or WTA qualifying results** (its only qualifying file is
  ATP), **and no WTA 125 results at all** (1,092 fixtures).

So main-draw coverage is about 99%. Qualifying and WTA 125 need another results source
before Step 5 can re-simulate or settle them.

## The setting: lam per book on every pre-sealed close

| Book | Closes | Mean overround | Mean gap, additive vs multiplicative | **lam (95% CI)** | Favourite-longshot slope (95% CI) |
|---|---|---|---|---|---|
| Pinnacle | 7,717 | 3.4% | 0.55 pts | **1.5 [0.5, 4.25]** | 1.075 [1.012, 1.139] |
| BetRivers | 6,935 | 6.6% | 1.06 pts | **1.25 [0.75, 1.75]** | 1.123 [1.053, 1.192] |
| DraftKings | 6,858 | 6.1% | 0.95 pts | **1.0 [0.5, 1.75]** | 1.078 [1.011, 1.145] |

- **Multiplicative (lam 0) is outside every interval.** All three books show a
  favourite-longshot bias: regressing the outcome on logit(multiplicative probability)
  gives a slope above 1, so favourites win more often than "same share off each side"
  implies. Pinnacle's 1.5 agrees with vigged.com's Pinnacle-tennis estimate (about 2.0
  [1.5, 3.1]).
- **These are the settings now** (`v5_devig.BOOK_LAM`). Books not measured yet use
  additive (lam 1). The cautious edge rule still judges every edge against the least
  favourable of multiplicative, additive and power.

## The 60/40 test the spec asked for, and why it could not decide

Fit on the earliest 60% of closes by start time, test on the latest 40%:

| Book, point | n test | fitted lam | fitted | multiplicative | additive | power |
|---|---|---|---|---|---|---|
| Pinnacle, close | 3,087 | 5.0 | 0.6084 | 0.6072 | 0.6071 | 0.6073 |
| BetRivers, close | 2,774 | 1.40 | 0.6099 | 0.6103 | 0.6099 | 0.6100 |
| DraftKings, close | 2,744 | 1.00 | 0.6064 | 0.6067 | 0.6064 | 0.6065 |

(T-6h and by-family results are in the JSON.)

- The methods move a price by only about 0.5–1 percentage point, which changes log loss by
  well under 0.001 per match. With about 3,000 test matches the smallest detectable
  difference is about 0.0004–0.0008, so every 95% interval includes zero. **This test
  lacks the power to separate the methods; it is not evidence that they are equal.** The
  full-sample intervals above use all the data and do separate them.
- Fitted on the earliest 60% alone (January to about June), Pinnacle's lam runs to the top
  of the range (5.0); the full sample gives 1.5. The bias may be stronger early in the
  season. Re-measure as September–October results and Bet365 arrive, and add
  tennis-data.co.uk (Pinnacle and Bet365 closes) once that domain is allowed.

## Benchmark for the model (Phase 1)

The market's log loss on these main-draw fixtures is about 0.607 at the close (latest 40%).
Pinnacle's close is calibrated within noise in every probability bucket, apart from the
favourite-longshot tilt above.
