# Totals from the winner price, and what it exposed: sets carry over (2026-11-21)

**Status:** exploratory. Historical data, before 2026-11-01.

**Test:** `research_tests/totals_model/run_totals_model.py`, design pushed (`e896855`) before the run.

**Data:** Kaggle / tennisexplorer bet365 winner odds and total-games lines with over/under prices, 2016–2025:
- 88,370 matches;
- test years 2022–25: 40,683 matches (Challenger 19,007, WTA main 11,852, ATP main 9,824).

## Result as registered: VOID (the model is mis-specified)

**The serve-level fit failed.** In 8 of 9 tour × surface groups, the fit hit the bottom of its grid (0.52). Even there, the independent-points model predicted more games than were played.

On 2022–25:

| | games |
|---|---|
| model mean | 24.2 |
| actual mean | 23.3 |
| line mean | 22.2 (a median-style line) |

**PRIMARY:** log loss, book plus model minus book alone: −0.00011 (−0.00023 to +0.00001).

| level | change in log loss | range |
|---|---|---|
| Challenger | −0.00034 | −0.00048 to −0.00020 |
| ATP main | −0.00022 | n.s. |
| WTA main | +0.00035 | +0.00016 to +0.00054 |

**Money:** the model's bias made it bet the over 99% of the time. It lost 9.7% (edge ≥ 3 points, n = 20,845). That is the bias, not a property of the market.

The results JSON is saved as `research_tests/totals_model/results_v1_void.json`.

## Why: sets carry over far more than independent points allow

**Diagnosis**, run after the result. ATP main, hard, best of 3, 2016–21: 39.7% of matches went to three sets. The model says 45.7% at every serve level, 0.50 to 0.68.

**The player who won set 1 also won set 2** (best of 3, 2016–21, 3,000 matches per level):

| | actual | independent-points model at the pre-match price |
|---|---|---|
| ATP main | **62.3%** | 54.3% |
| ATP Challenger | **64.7%** | 54.1% |
| WTA main | **67.2%** | 55.2% |

The pre-match price cannot know who is in form on the day; the score reveals it. Treating points as independent at pre-match strength underrates whoever is ahead.

## Consequences

1. **The totals question is still open.** It needs a model with form on the day before it can be tested.
2. **The registered in-play `fade` rule** (`docs/registrations/2026-11-18-inplay-rules.md`) compares Kalshi with this same independent-points fair price. A leader priced above it may be priced correctly.
   - The rule stays as registered: no rule is changed in its window.
   - It is likely to fail for this reason, and this note was written before its result.
   - The `serve_out` and `breaker` rules do not use the fair price.
3. **Next:** a "form on the day" model. Each player gets a match-specific shift to their serve probability, centred on the pre-match price, with its spread fitted on 2016–21 to reproduce the set carryover. In play, the shift is updated from the score.
   - It replaces the independent-points fair price for new research and for future registrations.
   - It is the basis for rerunning the totals test.
