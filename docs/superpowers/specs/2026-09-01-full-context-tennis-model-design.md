# Full-Context Tennis Prediction Architecture

Date: 2026-09-01
Status: Design approved in chat; formal spec pending user review
Repository: Tennis_Quant_Lab_V5

## 1. Objective

Build a modular pre-match tennis prediction platform that estimates each player's state at match time from prior match statistics, workload, travel, environment, court conditions, trajectory, uncertainty, and matchup interactions. The system must improve future-match prediction without using sportsbook prices to shape the underlying tennis probabilities.

The target is not a balanced recommendation mix. Favorites, underdogs, Overs, and Unders may appear in any proportion. A feature or model survives only if it improves unseen predictive performance and, later, market-edge performance under strict walk-forward validation.

## 2. Non-Negotiable Modeling Rules

1. **No lookahead.** Every feature for a match must be computable using information available before scheduled first serve.
2. **Independent tennis prediction first.** Bookmaker odds, no-vig probabilities, lines, or recommendation-side labels may not enter player-state estimation, model fitting, or score-distribution calibration.
3. **Market comparison last.** Odds enter only after independent probabilities/distributions are frozen for that prediction timestamp.
4. **Chronological validation.** Earlier data trains/calibrates; later data validates. 2025 is the primary development/calibration period and 2026 remains a later holdout wherever feasible.
5. **Incremental proof.** New subsystems must beat the prior accepted baseline on unseen data before entering production.
6. **No aesthetic balancing.** Never cap or rebalance favorite/underdog or Over/Under output shares.
7. **Modular provenance.** Every feature must have a documented source, as-of timestamp, transformation, and missing-value policy.
8. **Uncertainty is explicit.** Sparse or unstable player histories produce wider uncertainty, not fake precision.
9. **Production and historical logic share interfaces.** Historical replay and live prediction must use the same feature/model contracts to minimize train-serving skew.
10. **Forward-only integration.** Existing working refresh, odds, frozen-ledger, settlement, and market systems are preserved unless a tested interface change is required.

## 3. High-Level Architecture

The platform consists of eleven stages grouped into five major layers.

### Layer A — Context Data Platform

- Stage 1: Canonical Match & Context Warehouse
- Stage 2: Rest / Fatigue / Travel / Environment Features
- Stage 3: Advanced Rolling Match-Stat / Player-State Features

### Layer B — Matchup Representation

- Stage 4: Archetypes & Interaction Features

### Layer C — Independent Prediction Engines

- Stage 5: Direct Statistical / ML Match-Winner Model
- Stage 6: Dedicated Score-Distribution Model
- Stage 7: Residual Error-Correction Model
- Stage 8: Ensemble & Model-Disagreement Model

### Layer D — Scientific Validation

- Stage 9: Full Walk-Forward Validation
- Stage 10: Historical Odds / ROI / CLV Evaluation

### Layer E — Production Integration

- Stage 11: Promote Only Validated Improvements into Live V5

## 4. Stage 1 — Canonical Match & Context Warehouse

### Purpose
Create one durable, auditable historical record for every player-match observation, suitable for strict chronological replay.

### Grain
One row per `fixture x player` with a stable internal `match_id` and `player_id`. A two-player matchup is represented by two player-state rows plus a derived matchup row.

### Core match fields
- internal match_id
- provider fixture IDs, including permanent OddsPapi fixture ID when available
- tour (MEN/WTA)
- event/tournament ID and canonical name
- round
- scheduled/actual start timestamp where available
- event date
- surface
- indoor/outdoor
- best-of
- player IDs and canonical names
- winner/loser labels for post-match outcome tables only
- actual score, games, sets, tiebreaks
- retirement/walkover/abandonment flags

### Player metadata
- hand
- birth date / age as of match
- height where reliable
- ranking and ranking points as of match
- seed / qualifier / wildcard / lucky loser status when available

### Data sources
Initial free/public sources should include existing TennisMyLife data, current V5 state inputs, the permanent OddsPapi fixture registry, and public historical tennis repositories such as Jeff Sackmann datasets where their licensing and field coverage are suitable. Source adapters must be replaceable.

### Output contracts
- `context_warehouse/matches.parquet`
- `context_warehouse/player_match_rows.parquet`
- `context_warehouse/source_manifest.json`
- `context_warehouse/schema.json`

CSV may be emitted for audit/debugging, but Parquet is preferred for scale and typed columns.

## 5. Stage 2 — Rest, Fatigue, Travel, and Environment

### Rest & workload features
Derived entirely from matches prior to the target match:
- rest_days
- hours_since_last_match where timestamps permit
- matches_last_3d / 7d / 14d / 30d
- sets_last_3d / 7d / 14d / 30d
- games_last_3d / 7d / 14d / 30d
- minutes_last_3d / 7d / 14d / 30d where reliable duration exists
- consecutive_play_days
- matches_this_event
- qualifying_matches_this_event
- five_set_matches_last_7d / 14d / 30d
- previous_match_sets
- previous_match_games
- previous_match_duration
- prior_match_retirement flag
- cumulative tournament workload
- workload acceleration versus player's normal workload

Duration is used only where reliable; absence of duration must not silently become zero workload.

### Travel features
Maintain a canonical tournament-location registry:
- event city / venue
- latitude / longitude
- country / continent
- timezone
- altitude

Derived features:
- travel_km_from_previous_event
- timezone_change_hours
- eastward/westward travel
- continent_change
- days_since_arrival proxy
- days_since_timezone_change
- km_per_recovery_day
- altitude_change_meters
- surface_change
- indoor_outdoor_change
- travel + rest interaction terms

When exact player travel itinerary is unknown, use previous known competition location to current event location and mark the feature as an inferred proxy.

### Weather/environment features
Use historical/current weather APIs with persistent caching keyed by location/time:
- temperature
- apparent temperature
- humidity
- dew point
- wind speed
- wind gusts
- precipitation
- pressure
- cloud cover if useful

Weather quality fields must distinguish exact event-hour observations from day-level or location proxies.

### Dynamic court-speed features
Do not rely only on surface labels. Infer event/day environment from matches already completed before the target match, opponent-adjusted where possible:
- hold-rate residual
- ace-rate residual
- break-rate residual
- tiebreak-rate residual
- first-serve points won residual
- second-serve points won residual
- average games/set residual

Produce:
- court_speed_index_event
- court_speed_index_day
- court_speed_sample_size
- court_speed_uncertainty

No later matches from the same tournament day may leak backward.

## 6. Stage 3 — Advanced Rolling Match Statistics & Player State

### Raw / opponent-adjusted statistics
Where available:
- first serve in %
- first serve points won %
- second serve points won %
- ace rate
- double-fault rate
- service points won
- return points won
- break points saved
- break points converted
- hold rate
- break rate
- tiebreak win rate
- set win rate
- game win rate

Each stat should support:
- all-surface baseline
- surface-specific baseline
- rolling windows
- exponentially weighted versions
- opponent-strength adjusted versions
- uncertainty / effective sample size

### Trajectory features
Estimate not only recent level but direction:
- serve-performance slope
- return-performance slope
- Elo slope
- opponent-adjusted game-share slope
- acceleration / second-order trend where stable
- recent level minus long-term level
- recent uncertainty

Trajectory models must be regularized and validated for persistence; noisy trends are not promoted merely because they fit history.

### Player-state vector
For each player immediately pre-match, produce a structured state containing:
- base ability
- serve ability
- return ability
- surface ability
- recent trajectory
- fatigue/workload state
- travel/acclimation state
- environmental fit state
- player uncertainty
- data quality flags

The state vector becomes the common input contract for downstream models.

## 7. Stage 4 — Archetypes & Interaction Features

### Archetype representation
Prefer continuous dimensions over brittle human labels. Candidate dimensions include:
- serve dominance
- return dominance
- first-serve dependence
- second-serve vulnerability
- ace dependence
- break-generation tendency
- tiebreak reliance
- rally / return orientation proxies
- surface specialization
- volatility / consistency

Clustering may be used for exploratory archetypes, but production models should retain continuous features whenever possible.

### Explicit interaction features
Initial tested interactions include:
- big_server x slow_court
- big_server x fast_court
- big_server x altitude
- weak_second_serve x elite_returner
- high_workload x heat
- high_workload x humidity
- long_previous_match x short_rest
- timezone_shift x short_acclimation
- travel_km x rest_days
- altitude_change x short_acclimation
- surface_change x low_surface_experience
- indoor_outdoor_change x surface_profile
- serve_dependence x wind
- return_dominance x slow_court
- serve_dominance x fast_court
- qualifier_workload x tournament_round
- improving_trajectory x stale_ranking
- declining_trajectory x condensed_schedule
- player_uncertainty x ranking_gap
- archetype_A x archetype_B
- court_speed x hold_tendency
- court_speed x break_tendency

### Learned interactions
Tree/boosting models may discover nonlinear interactions not explicitly enumerated. Interpretation tooling must identify high-impact learned interactions and test whether their effect is stable across time segments.

## 8. Stage 5 — Direct Statistical / ML Winner Model

### Purpose
Provide an independent probability engine separate from the mechanistic tennis simulator.

### Candidate model family
Start with robust, auditable baselines before more complex models:
1. regularized logistic regression
2. gradient-boosted trees
3. calibrated ensemble if justified

Neural networks are not a default requirement. They enter only if they add out-of-sample value over simpler methods.

### Inputs
Player-state differences, matchup interactions, environment, workload, travel, uncertainty, and tournament context. No sportsbook information.

### Outputs
- P(player1 wins)
- calibrated probability
- uncertainty / confidence
- feature attribution for diagnostics

### Acceptance
Must improve Brier/log loss and calibration on untouched future periods versus the currently accepted serve/return + Elo baseline.

## 9. Stage 6 — Dedicated Score-Distribution Model

### Purpose
Stop forcing moneyline strength, game margin, total games, sets, and tiebreaks through one scalar serve-strength representation.

### Structure
Estimate at least three latent dimensions:
1. matchup strength — who should win
2. serve/scoring environment — how easy holding is for both players
3. dominance geometry — how the stronger player's advantage manifests

### Outputs
- distribution of game margin
- total-games distribution
- set-score probabilities
- tiebreak probabilities
- match-win probability consistency check

### Candidate methods
- conditioned mechanistic simulation
- distributional regression / gradient boosting for margins and totals
- hybrid simulator whose parameters are predicted by ML from pre-match context

### Acceptance
Use proper distribution scoring on unseen results: margin-CDF and total-CDF Brier/CRPS-style metrics, plus bias and RMSE. Market lines are not used to calibrate the distribution.

## 10. Stage 7 — Residual Error-Correction Model

### Purpose
Learn systematic situations where accepted base models are wrong.

### Training target
Residuals from strictly out-of-fold / walk-forward base predictions only. Never train residual models on in-sample base-model fitted values.

Targets may include:
- winner logit residual
- game-margin residual
- total-games residual

### Inputs
Original features plus base-model predictions, model disagreement, uncertainty, archetypes, transitions, workload, and environment.

### Acceptance
Must improve untouched future-period metrics after accounting for added complexity. If it simply memorizes player/event identity, reject or constrain it.

## 11. Stage 8 — Ensemble & Model Disagreement

### Candidate engines
- mechanistic V5 serve/return simulation
- surface Elo / rating model
- direct contextual ML winner model
- score-distribution model
- residual model

### Ensemble rule
Weights or meta-models are learned using historical out-of-fold predictions only.

### Disagreement features
Measure:
- probability range across models
- standard deviation / entropy
- mechanistic vs ML disagreement
- Elo vs contextual-model disagreement
- residual correction magnitude

Disagreement is treated as epistemic uncertainty and may affect confidence or minimum-edge requirements only if historical validation shows that it improves realized performance.

## 12. Stage 9 — Full Walk-Forward Validation

### Validation design
All models are evaluated chronologically. The framework must support expanding-window and rolling-window experiments.

Primary development structure:
- historical years through 2024: broad model development
- 2025: calibration / model selection where already established
- 2026: untouched validation for claims whenever possible

Once 2026 is used to select among candidate designs, it is no longer a pristine holdout for that decision. The framework must record this and reserve later live data as the next true holdout.

### Metrics
Winner models:
- log loss
- Brier score
- calibration error
- calibration curves
- accuracy
- favorite/underdog bucket performance
- probability-bin performance

Score models:
- margin CDF Brier / CRPS-style score
- total CDF Brier / CRPS-style score
- margin bias / RMSE / MAE
- total bias / RMSE / MAE
- set-score calibration
- tiebreak calibration

Segment diagnostics:
- tour
- surface
- tournament level
- ranking bucket
- favorite probability bucket
- workload bucket
- travel bucket
- weather bucket
- court-speed bucket
- player uncertainty bucket
- archetype matchup

### Promotion rule
No subsystem is production-promoted unless it improves the accepted baseline overall or in a pre-specified, stable segment without materially degrading aggregate calibration.

## 13. Stage 10 — Historical Odds, ROI, and CLV

OddsPapi historical odds are joined only after independent model outputs are frozen.

Evaluate:
- model probability vs no-vig market probability
- edge by size bucket
- EV
- realized ROI / units
- closing-line value when sufficient snapshots exist
- performance by bookmaker
- performance by market type
- performance by confidence/disagreement state
- probability calibration conditional on market disagreement

Signal thresholds are selected empirically from historical/walk-forward evidence and then tested on later periods. They are not chosen to force a desired number or type of bets.

## 14. Stage 11 — Live Production Integration

### Live flow
1. refresh tennis results/player histories
2. refresh/cache tournament metadata
3. refresh weather/environment context
4. build pre-match player states
5. build matchup interactions
6. generate independent model predictions
7. generate score distributions
8. calculate ensemble/disagreement/uncertainty
9. freeze model outputs
10. join current sportsbook prices
11. calculate edge/EV/signals
12. freeze recommendation ledger
13. settle independently after results

### Failure behavior
Missing context must produce explicit feature-quality flags and fallback behavior. It must never silently substitute zeros or future data.

The system should degrade gracefully to the strongest validated subset of features available for that match.

## 15. External Data Strategy

Start with free/public sources and derived features. Create adapter interfaces and permanent caches so providers can change without rewriting model logic.

Initial external-source categories:
- historical tennis match/stat data
- tournament location metadata
- geocoding/timezone
- elevation
- historical/current weather
- optional later point-level or richer stat feeds

Any paid source is added only after a feasibility test demonstrates unique data value likely to improve predictions or reliability.

## 16. Data Provenance and Leakage Controls

Each engineered feature must carry or be traceable to:
- feature name/version
- source dataset/provider
- raw source timestamp/date
- calculation cutoff timestamp
- match prediction timestamp
- missingness indicator
- proxy/exact-quality indicator where relevant

Automated tests must include deliberate leakage traps: future-match rows, same-day later matches, post-match outcomes, future tournament court-speed data, and future rankings must not alter earlier feature rows.

## 17. Testing Strategy

Each module gets unit tests plus integration tests.

Required classes of tests:
- canonical identity resolution
- chronological ordering
- no-lookahead feature construction
- rolling window boundaries
- travel/location calculations
- timezone calculations
- weather-cache deterministic lookup
- court-speed as-of filtering
- missing-data behavior
- uncertainty shrinkage
- feature symmetry when players are swapped
- probability complement consistency
- score-distribution push handling
- walk-forward fold isolation
- residual-model out-of-fold enforcement
- ensemble train-serving consistency
- historical/live feature parity
- full pipeline smoke test

## 18. Model Governance / Experiment Registry

Every experiment records:
- experiment ID
- git SHA
- feature-set version
- training window
- validation window
- model hyperparameters
- random seeds where applicable
- metrics
- segment metrics
- promotion decision
- reason for acceptance/rejection

The repo must preserve rejected experiment summaries as evidence against repeatedly rediscovering failed ideas.

## 19. Implementation Order

1. canonical warehouse and feature provenance contracts
2. tournament-location registry and environment cache
3. workload/rest/travel features
4. rolling advanced match statistics
5. player-state vector and uncertainty
6. dynamic court-speed engine
7. explicit and learned matchup interactions
8. contextual winner-model baselines
9. score-distribution models
10. residual learner
11. ensemble/disagreement layer
12. unified walk-forward experiment runner
13. historical odds / ROI / CLV join
14. live-production adapters
15. UI/diagnostic exposure of validated context and model reasoning

Each major step must be independently testable and should not require the final system to exist before producing useful validation results.

## 20. Definition of Complete

This architecture is complete only when:

- live pre-match rows include validated historical statistics, workload, rest, travel, court/environment, trajectory, and uncertainty features;
- models generate independent match-win and score-distribution predictions without sportsbook inputs;
- multiple engines and their disagreement are evaluated under walk-forward validation;
- only features/models proven helpful on later data are active in production;
- historical odds are used after prediction for edge, ROI, and CLV analysis;
- the live daily board uses the same accepted feature/model code as historical replay;
- every production prediction can be traced to its input state, model version, and as-of timestamp;
- frozen predictions continue to settle automatically against actual results;
- there is a documented evidence trail showing which additions improved prediction quality and which were rejected.

The guiding standard is: build the richest tennis model we can justify scientifically, but allow evidence—not intuition, market aesthetics, or model complexity—to decide what survives.