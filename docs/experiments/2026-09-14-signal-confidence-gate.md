# State-confidence gate audit — 2026-09-14

This is a frozen-history diagnostic. It does **not** alter the production signal policy.

Primary scope: **current_model_version**; 2,182 settled market rows across 111 fixtures.
Current production confidence threshold: **45%**.

## Threshold comparison — primary scope

| Confidence gate | Bets | W-L-P | Net units | ROI | Max DD | Units / fixture | ROI 95% bootstrap CI |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 0% | 72 | 30-42-0 | +17.735 | +24.6% | 7.000 | +0.160 | [-14.5%, +63.0%] |
| 30% | 70 | 29-41-0 | +16.125 | +23.0% | 7.000 | +0.145 | [-15.4%, +64.8%] |
| 35% | 69 | 28-41-0 | +13.755 | +19.9% | 7.000 | +0.124 | [-18.2%, +58.8%] |
| 40% | 68 | 28-40-0 | +14.755 | +21.7% | 7.000 | +0.133 | [-17.0%, +61.4%] |
| 45% | 67 | 28-39-0 | +15.755 | +23.5% | 7.000 | +0.142 | [-17.5%, +64.3%] |
| 50% | 64 | 26-38-0 | +12.825 | +20.0% | 7.000 | +0.116 | [-20.4%, +63.4%] |
| 55% | 61 | 25-36-0 | +12.955 | +21.2% | 7.000 | +0.117 | [-20.5%, +65.5%] |
| 60% | 61 | 25-36-0 | +12.955 | +21.2% | 7.000 | +0.117 | [-20.5%, +65.5%] |

## What the 45% gate is doing

It downgraded 5 otherwise BET/LEAN-priced market rows across 5 fixtures in the primary settled scope.
Fixture-capped no-confidence-gate result: 72 bets, +17.735 units, +24.6% ROI.
Fixture-capped 45% result: 67 bets, +15.755 units, +23.5% ROI.

## Chronological validation

Development-selected threshold: **0%**.
Holdout paired incremental units/fixture vs 45%: +0.000; 95% CI [0.0, 0.0].
Decision under the predeclared promotion rule: **KEEP_45_INSUFFICIENT_HOLDOUT**.

The threshold is changed only if the development-selected alternative survives the untouched chronological holdout with a positive paired fixture-bootstrap interval, higher holdout ROI, adequate sample size, and time-block stability.
