# Surface / Environment / Court-Speed Simulation Controls Design

Date: 2026-09-13
Status: User-approved design pending written-spec review
Repository: Tennis_Quant_Lab_V5

## 1. Objective

Make the daily simulation controls represent the three distinct components that define match playing conditions:

1. **Surface type** — Hard / Clay / Grass
2. **Environment** — Indoor / Outdoor, with weather applicability governed by environment
3. **Court speed** — the model's dynamic court-speed estimate, with an editable numeric override and qualitative label

All three controls must affect the same canonical simulation/model path. They are not display-only metadata and must not create a second prediction path.

The change must preserve the V5 governing mandate: one source of truth, hands-off production, sportsbook-independent probabilities, strict pre-match information boundaries, historical auditability, and promotion of model behavior only through statistically defensible validation.

## 2. Governing Architecture

This design extends the approved full-context tennis architecture and court-speed amendment rather than replacing them.

The canonical match-condition representation becomes:

`surface_type + environment + court_speed_state + weather_state`

with weather_state conditionally active only when appropriate for the selected environment.

Examples:

- `Hard + Indoor + +1.25 Fast`
- `Hard + Outdoor + +1.25 Fast + outdoor weather context`
- `Clay + Outdoor + -0.80 Slow + outdoor weather context`

`Indoor Hard` is not a fourth surface. Surface and environment remain orthogonal dimensions.

## 3. User-Facing Controls

Inside the existing Simulation Precision / Slate Setup / Advanced workflow, expose these editable controls for each fixture:

### Surface Type
Allowed values:
- Hard
- Clay
- Grass

The existing inferred/default surface remains visible, and a user override replaces it only for that simulation run.

### Environment
Allowed values:
- Indoor
- Outdoor

The inferred/default environment remains visible with source/provenance when known. A user override replaces it only for that simulation run.

### Court Speed
Expose:
- the current model-estimated numeric court-speed index;
- a qualitative label derived from that value, such as Slow / Neutral / Fast;
- an editable numeric override.

The numeric value is the authoritative input. The qualitative label is presentation only.

If no override is supplied, the simulation uses the canonical dynamic court-speed estimate produced under the approved historical-prior/current-event blending architecture.

## 4. Model Behavior

### Surface Type
Surface selection must affect the same production calculations that currently use surface-specific state, including surface Elo / surface-conditioned serve-return state where applicable.

### Environment
Environment must affect model inputs through the existing full-context architecture rather than through an arbitrary fixed bonus/penalty.

The environment state should influence validated environment-related features including, where available:
- indoor/outdoor historical context;
- indoor/outdoor transition state;
- player environmental-fit state;
- environment interactions already present in the accepted feature contract.

Changing Indoor to Outdoor must therefore cause a genuine recomputation of the matchup context when the accepted model uses those features.

### Outdoor Weather
For Outdoor matches, weather inputs remain eligible to affect the model through the validated weather/environment feature pipeline, including temperature, apparent temperature, humidity, dew point, wind, gusts, precipitation, pressure, and other accepted fields.

### Indoor Weather
For Indoor matches, outdoor venue weather must not influence the match prediction as if play were exposed to it.

The canonical indoor state must suppress or neutralize outdoor-weather-derived model effects while preserving provenance that weather was intentionally inapplicable rather than missing.

Indoor handling must not silently convert weather fields to ordinary missing-data fallbacks if doing so would trigger unrelated missingness behavior. The context pipeline should carry an explicit environment/applicability state.

### Court Speed
Court speed must affect the model through the existing dynamic court-speed feature contract and accepted interactions, not via an unvalidated ad hoc probability shift.

A user court-speed override substitutes for the canonical blended court-speed value at the simulation cutoff and must propagate through any validated court-speed interactions used by the live model, such as serve-dominance and return-dominance interactions.

The override must not alter historical source artifacts or rewrite the persisted canonical court-speed estimate.

## 5. Override Semantics

Overrides are simulation inputs, not canonical data corrections.

For each fixture, preserve both:
- canonical inferred/model value;
- effective simulation value.

Recommended fields:
- `surface_inferred`
- `surface_effective`
- `surface_source`
- `environment_inferred`
- `environment_effective`
- `environment_source`
- `court_speed_model`
- `court_speed_effective`
- `court_speed_source`
- `court_speed_override_applied`

This preserves auditability and prevents manual simulation inputs from mutating historical context or future automated production runs.

## 6. Canonical Data Flow

The intended flow is:

`market fixture / tournament metadata`
→ `canonical context warehouse + tournament registry`
→ `inferred Surface / Environment / Court Speed / Weather`
→ `optional Simulation Precision overrides`
→ `effective pre-match context fixture`
→ `existing full-context feature builder`
→ `accepted winner + score models`
→ `frozen sportsbook-independent probabilities/distributions`
→ `market repricing`

There must be exactly one effective-context construction path shared by interactive/manual simulation and automated daily forecasting wherever practical.

The Streamlit layer may collect overrides but must not contain independent model mathematics.

## 7. Court-Speed Precision and Labels

The numeric court-speed index remains authoritative.

The UI should show a human-readable label beside the numeric value, for example:

- sufficiently negative: `Slow`
- near baseline: `Neutral`
- sufficiently positive: `Fast`

Exact label thresholds should be derived from the existing court-speed scale or historical distribution, not invented independently by the UI.

If the current model scale is standardized, labels should use stable distribution-aware cut points. If the scale is not standardized, implementation must first identify the production range before setting labels.

The labels must not affect calculations.

## 8. Validation and Statistical Guardrails

This feature has two distinct parts:

### A. Control Plumbing
It is valid to expose and propagate existing approved context dimensions immediately, provided the controls use already-accepted model behavior and do not introduce new coefficients or new probability adjustments.

### B. New Predictive Effects
Any new environment-specific or court-speed-specific coefficient, feature transformation, weighting rule, or player split that is not already part of the accepted production model is Research / Model Profitability work and must earn promotion through chronological out-of-sample validation.

Required evaluation for newly introduced predictive behavior includes, as applicable:
- chronological / walk-forward validation;
- calibration;
- Brier score;
- log loss;
- winner accuracy where meaningful;
- score-distribution accuracy for margin/total outputs;
- stability across seasons and tours;
- indoor vs outdoor hard-court subsets;
- interaction stability with court speed;
- sufficient sample size and uncertainty reporting.

No indoor-season tuning may be promoted merely because the calendar is moving into indoor tournaments.

## 9. Historical / Live Parity

Historical replay and live prediction must use the same effective-context contract.

A historical target row must be reproducible strictly from information available before that match:
- historical environment label;
- pre-match weather where applicable;
- historical court-speed prior;
- current-event evidence completed before the target match only;
- no later same-day or future-event leakage.

Manual override support is primarily an interactive simulation capability and must not contaminate historical replay datasets unless an explicit scenario-analysis mode is invoked.

## 10. Error Handling and Missingness

### Missing Environment
If environment cannot be inferred reliably:
- expose `Unknown`/unresolved provenance internally;
- require an explicit safe fallback policy in automated production;
- do not silently guess Indoor solely because a tournament is occurring during indoor season.

### Missing Court Speed
Use the existing hierarchical fallback defined by the court-speed architecture:
- same-event historical prior;
- venue / comparable-event prior;
- surface / tour baseline;
- uncertainty/source-quality fields preserved.

### Missing Outdoor Weather
Follow the approved weather-source quality and fallback contract. Missing weather must not masquerade as Indoor.

### Indoor Weather
Mark outdoor weather as not applicable to exposed-play effects rather than as a failed weather fetch.

## 11. UI / UX Requirements

The controls remain in the collapsed Advanced / Simulation Precision area so the default customer-facing Today experience stays decision-first.

For each fixture, show concise effective conditions such as:

`Hard · Indoor · +1.2 Fast`

or

`Hard · Outdoor · +0.4 Neutral · Weather active`

When an override is applied, make that visible without overwhelming the main matchup card.

The customer-facing Today page should continue to consume frozen canonical production outputs. Manual interactive overrides are analysis/simulation controls and must not silently replace the official daily forecast ledger.

## 12. Testing Contract

Automated tests must prove at minimum:

- Surface, Environment, and Court Speed are independently editable inputs.
- Surface values remain limited to Hard / Clay / Grass.
- Indoor / Outdoor is not encoded as a synthetic surface type.
- Override values propagate from UI/input rows into the effective context fixture.
- Changing Surface changes the surface-conditioned model path.
- Changing Environment changes environment/applicability state used by context construction.
- Indoor suppresses outdoor-weather effects without presenting them as ordinary missing data.
- Outdoor keeps weather effects eligible.
- Court-speed override changes the effective court-speed features/interactions used by simulation.
- Court-speed override does not mutate the persisted canonical court-speed artifact.
- Qualitative speed labels do not affect model math.
- Interactive/manual simulation still uses the same accepted model functions rather than a duplicate calculator.
- Automated production behavior remains unchanged when no overrides are provided.
- Historical replay remains leakage-safe.

Where deterministic model fixtures permit it, include a sensitivity test showing that changing each of the three dimensions independently can alter downstream model inputs/output when the accepted model has nonzero sensitivity to that dimension.

## 13. Scope / Non-Goals

This design does not:
- create `Indoor Hard` as a new surface category;
- introduce sportsbook prices into model formation;
- invent an arbitrary indoor adjustment;
- invent a new court-speed coefficient without validation;
- rewrite historical predictions;
- make manual overrides part of official settled performance;
- create a second interactive-only prediction engine;
- alter recommendation thresholds simply because indoor season is approaching.

## 14. Mandate Alignment

This design preserves the four anti-drift requirements:

1. **Low manual intervention:** automated production continues to infer conditions normally; overrides are optional analysis controls.
2. **One source of truth:** Surface, Environment, Court Speed, and Weather enter through one effective-context contract feeding the accepted production model.
3. **Statistical validity:** existing accepted effects can be exposed immediately; new predictive behavior requires chronological out-of-sample proof.
4. **Sellable MVP:** the product represents real tennis playing conditions more faithfully while preserving a clean customer-facing interface and auditable official forecast path.

The intended result is a model in which playing conditions are represented by their actual components — surface material, environment, and court speed — and each component is independently observable, editable for simulation, auditable, and capable of affecting the accepted model through validated feature logic.
