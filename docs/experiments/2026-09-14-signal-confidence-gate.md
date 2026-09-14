# State-confidence gate audit — 2026-09-14

## Decision

**Keep the production confidence threshold at 45% for now.**

This audit used frozen, settled V5 history only. No production signal rule was changed.

The current-model scope contained 2,182 settled market rows across 111 fixtures. State confidence was populated on 100% of those rows. The 45% gate downgraded only 5 otherwise actionable BET/LEAN-priced rows across 5 fixtures.

## Current-model threshold comparison

| Confidence gate | Bets | W-L-P | Net units | ROI | Max DD | Units / fixture |
|---:|---:|---:|---:|---:|---:|---:|
| 0% | 72 | 30-42-0 | +17.735 | +24.6% | 7.000 | +0.160 |
| 30% | 70 | 29-41-0 | +16.125 | +23.0% | 7.000 | +0.145 |
| 35% | 69 | 28-41-0 | +13.755 | +19.9% | 7.000 | +0.124 |
| 40% | 68 | 28-40-0 | +14.755 | +21.7% | 7.000 | +0.133 |
| **45%** | **67** | **28-39-0** | **+15.755** | **+23.5%** | **7.000** | **+0.142** |
| 50% | 64 | 26-38-0 | +12.825 | +20.0% | 7.000 | +0.116 |
| 55% | 61 | 25-36-0 | +12.955 | +21.2% | 7.000 | +0.117 |
| 60% | 61 | 25-36-0 | +12.955 | +21.2% | 7.000 | +0.117 |

The no-gate version produced +1.980 more units than the 45% gate over the full current-model sample, but the paired fixture-bootstrap interval for the incremental result crossed zero: **-0.045 to +0.093 units per fixture**. That is not statistically strong enough to promote a change.

## Chronological validation

A 70/30 chronological development/holdout split was used. The development period selected a 0% threshold (no confidence gate) on units per available fixture, subject to minimum volume. However, the untouched holdout contained only 11 actionable bets at both 0% and 45%; the policies were identical there because none of the holdout selections fell below 45% confidence.

Therefore the alternative did not have enough independent holdout observations to establish superiority. The predeclared decision is **KEEP_45_INSUFFICIENT_HOLDOUT**.

## Broader frozen-history check

Across all 4,832 settled market rows / 251 fixtures, removing the confidence gate did not improve results: fixture-capped no-gate performance was -3.750 units (-2.0% ROI) versus -1.930 units (-1.1% ROI) at 45%. The paired bootstrap difference again included zero. The broader-history chronological holdout also failed to show a significant advantage to removing the gate.

## Implication for the all-REVIEW slate

The historical evidence does **not** support the idea that a 45% gate normally turns most of the board into REVIEW. In the current-model history it affected only 5 of 72 otherwise actionable fixture selections. State-confidence distribution was generally high: median 86.9%, 25th percentile 67.0%, and 10th percentile 50.9%.

If a current slate is showing state confidence values such as 6-12% across many matches and nearly everything is REVIEW, that is statistically abnormal relative to the frozen current-model history and should be investigated as a current context/confidence-input issue rather than solved by lowering the threshold.

## Promotion rule used

A non-45 threshold is eligible for production promotion only if it is selected on the development period, both candidate and 45% policies have at least 20 holdout bets, the paired fixture-bootstrap 95% interval for incremental units per fixture is entirely above zero, holdout ROI is higher, and incremental units are positive in at least two of three chronological holdout blocks.

No candidate met that standard in this audit.
