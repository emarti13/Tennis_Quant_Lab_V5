# Full-Context Tennis Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and validate a full-context pre-match tennis prediction platform using prior match statistics, rest, fatigue, travel, environment, historical/current court speed, trajectory, uncertainty, matchup interactions, independent ML engines, residual learning, ensembles, and strict walk-forward validation.

**Architecture:** Extend V5 with a canonical as-of-match context warehouse feeding modular feature builders, player-state vectors, matchup interactions, independent winner/score models, residual and ensemble layers, and a single walk-forward experiment runner. Keep sportsbook data completely outside model fitting; odds join only after model outputs are frozen.

**Tech Stack:** Python 3.12, pandas, numpy, scikit-learn, pyarrow/parquet, requests/curl_cffi, existing V5 modules and GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-01-full-context-tennis-model-design.md` plus `docs/superpowers/specs/2026-09-01-court-speed-amendment.md`

## Global Constraints

- No lookahead: every feature is computed strictly from information available before first serve.
- No sportsbook prices in player-state construction, model training, model calibration, score-distribution calibration, or model selection.
- 2025 may be used for development/calibration; 2026 remains later validation where not already consumed by a design choice.
- No favorite/underdog or Over/Under balancing.
- Historical and live paths must share feature/model interfaces.
- Missing context never silently becomes zero.
- Every promoted feature/model must beat the accepted baseline on later unseen data or a pre-specified stable segment without materially degrading aggregate calibration.
- Court speed starts from a historical prior and is updated by current-event/current-day evidence with uncertainty-aware shrinkage.

---

### Task 1: Canonical Context Warehouse

**Files:**
- Create: `v5_context_schema.py`
- Create: `build_v5_context_warehouse.py`
- Create: `tests/test_v5_context_warehouse.py`
- Create: `.github/workflows/v5_context_warehouse.yml`

**Interfaces:**
- Produces: `build_context_warehouse(base_dir: str='.') -> dict[str, object]`
- Produces files: `context_warehouse/matches.parquet`, `context_warehouse/player_match_rows.parquet`, `context_warehouse/source_manifest.json`, `context_warehouse/schema.json`

- [ ] Write tests asserting stable `match_id`, two player rows per completed singles match, typed dates, canonical tour/surface/best_of, and no post-match outcome fields in pre-match feature namespace.
- [ ] Run `pytest tests/test_v5_context_warehouse.py -v` and verify RED.
- [ ] Implement schema constants and source adapters for existing TennisMyLife + V5 walk-forward/result inputs.
- [ ] Build deterministic stable IDs from tour/date/tournament/normalized player pair.
- [ ] Emit Parquet + manifest/schema and explicit source quality fields.
- [ ] Run tests and workflow; require 0 failures and nonzero 2025/2026 MEN/WTA rows.
- [ ] Commit `feat: add canonical context warehouse`.

### Task 2: Tournament Registry + Geography

**Files:**
- Create: `v5_tournament_registry.py`
- Create: `context_registry/tournaments.csv`
- Create: `tests/test_v5_tournament_registry.py`

**Interfaces:**
- `resolve_tournament(name: str, tour: str, year: int) -> TournamentContext`
- `TournamentContext` fields: canonical_event_id, city, country, latitude, longitude, timezone, altitude_m, indoor, surface, source_quality.

- [ ] Add tests for canonical name aliases, year-sensitive venue changes, missing-field quality flags, and deterministic resolution.
- [ ] Implement registry loader and alias matching without fuzzy auto-accept for ambiguous names.
- [ ] Seed registry from existing tournament names; unresolved events remain explicit rather than guessed.
- [ ] Verify >95% of 2025/2026 main-tour rows resolve to at least city/country before promotion.
- [ ] Commit `feat: add tournament geography registry`.

### Task 3: Rest / Workload / Fatigue Features

**Files:**
- Create: `v5_workload_features.py`
- Create: `tests/test_v5_workload_features.py`

**Interfaces:**
- `build_workload_features(player_rows: pd.DataFrame) -> pd.DataFrame`

- [ ] Write leakage tests where a future match is appended and earlier rows must remain byte-equivalent for workload columns.
- [ ] Implement rest_days, matches/sets/games/minutes windows (3/7/14/30d), consecutive_play_days, event workload, qualifying workload, prior-match sets/games/duration, five-set load, and workload acceleration.
- [ ] Missing duration returns NaN + `duration_quality`, never 0.
- [ ] Validate chronology and boundary conditions at exactly 3/7/14/30 days.
- [ ] Commit `feat: add workload and fatigue features`.

### Task 4: Travel / Acclimation Features

**Files:**
- Create: `v5_travel_features.py`
- Create: `tests/test_v5_travel_features.py`

**Interfaces:**
- `build_travel_features(player_rows: pd.DataFrame, tournament_registry: pd.DataFrame) -> pd.DataFrame`

- [ ] Test haversine distance, east/west timezone sign, continent changes, altitude changes, surface transitions, and no future-event leakage.
- [ ] Implement travel_km, timezone_change_hours, days_since_timezone_change proxy, km_per_recovery_day, altitude_change_m, surface_change, indoor_outdoor_change, and proxy-quality flags.
- [ ] Commit `feat: add travel and acclimation features`.

### Task 5: Historical + Current Court-Speed Engine

**Files:**
- Create: `v5_court_speed.py`
- Create: `tests/test_v5_court_speed.py`

**Interfaces:**
- `build_court_speed_features(matches: pd.DataFrame, player_states: pd.DataFrame) -> pd.DataFrame`
- `blend_court_speed(prior_mean: float, prior_var: float, current_mean: float, current_var: float) -> tuple[float, float]`

- [ ] Test hierarchical prior order: same event -> venue -> comparable cohort -> tour/surface baseline.
- [ ] Test recency weighting and uncertainty increasing as hierarchy backs off.
- [ ] Test current-event update uses only completed matches before target start.
- [ ] Test same-day later-match leakage trap.
- [ ] Implement opponent-adjusted residuals for hold/ace/break/tiebreak/1stSPW/2ndSPW/games-per-set where fields exist; otherwise use strongest validated subset and quality flags.
- [ ] Emit historical prior/current event/current day/blended/delta/sample-size/uncertainty features exactly as specified in amendment.
- [ ] Run ablation: surface-only vs historical-only vs current-only vs blended vs blended+day; save metrics to `experiments/court_speed_ablation.json`.
- [ ] Promote only the best later-period variant.
- [ ] Commit `feat: add historical-prior court speed engine`.

### Task 6: Advanced Rolling Match Statistics

**Files:**
- Create: `v5_rolling_stats.py`
- Create: `tests/test_v5_rolling_stats.py`

**Interfaces:**
- `build_rolling_stats(player_rows: pd.DataFrame) -> pd.DataFrame`

- [ ] Add rolling/EWMA/opponent-adjusted stats for first serve in, 1st/2nd serve points won, ace/DF rate, service/return points won, BP saved/converted, hold/break, tiebreak, set/game share.
- [ ] Add surface-specific and all-surface estimates plus effective sample size and uncertainty.
- [ ] Ensure target match stats never enter its own predictors.
- [ ] Commit `feat: add opponent-adjusted rolling match stats`.

### Task 7: Trajectory + Player-State Vector

**Files:**
- Create: `v5_player_state.py`
- Create: `tests/test_v5_player_state.py`

**Interfaces:**
- `build_player_state(feature_row: pd.Series) -> dict[str, float | str | bool]`

- [ ] Implement regularized slopes for serve, return, Elo, game share; recent-vs-long-term deltas; uncertainty shrinkage by effective sample.
- [ ] Combine base ability, serve, return, surface, trajectory, workload, travel, environment, uncertainty, and quality into a versioned state vector.
- [ ] Verify player-swap symmetry where applicable.
- [ ] Commit `feat: add versioned player state vectors`.

### Task 8: Archetypes + Interaction Features

**Files:**
- Create: `v5_matchup_features.py`
- Create: `tests/test_v5_matchup_features.py`

**Interfaces:**
- `build_matchup_features(state_a: dict, state_b: dict, context: dict) -> dict[str, float]`

- [ ] Implement continuous archetype dimensions: serve dominance, return dominance, first-serve dependence, second-serve vulnerability, ace dependence, break generation, tiebreak reliance, surface specialization, volatility.
- [ ] Implement explicit interactions from spec including workload×heat, travel×rest, timezone×acclimation, big-server×court-speed/altitude, weak-second-serve×elite-returner, trajectory×ranking staleness, court-speed×hold/break tendencies.
- [ ] Ensure signed matchup features reverse appropriately when players are swapped.
- [ ] Commit `feat: add matchup archetypes and interactions`.

### Task 9: Contextual Winner Models

**Files:**
- Create: `v5_contextual_winner.py`
- Create: `diagnose_contextual_winner_walkforward.py`
- Create: `tests/test_v5_contextual_winner.py`

**Interfaces:**
- `fit_contextual_winner(train: pd.DataFrame, feature_names: list[str], model_type: str) -> FittedWinnerModel`
- `predict_proba(model, rows: pd.DataFrame) -> np.ndarray`

- [ ] Establish baselines: accepted SR+Elo model, regularized logistic regression, gradient boosting.
- [ ] Generate only walk-forward/out-of-fold predictions for model comparison.
- [ ] Evaluate Brier, log loss, ECE/calibration, accuracy, and segment metrics.
- [ ] Save experiment records including rejected models.
- [ ] Promote only if unseen-period Brier/log-loss/calibration improve.
- [ ] Commit `feat: add contextual winner model experiments`.

### Task 10: Dedicated Score-Distribution Models

**Files:**
- Create: `v5_score_distribution.py`
- Create: `diagnose_contextual_score_walkforward.py`
- Create: `tests/test_v5_score_distribution.py`

**Interfaces:**
- `predict_score_distribution(match_features: dict, model_bundle) -> ScoreDistribution`

- [ ] Model separate latent matchup strength, serve environment, and dominance geometry.
- [ ] Compare conditioned mechanistic simulation, direct distributional regression, and hybrid parameter-prediction simulation.
- [ ] Score margins/totals with CDF Brier/CRPS-style metrics, bias/RMSE/MAE, set/tiebreak calibration.
- [ ] Keep Bo3 and Bo5 segment handling explicit.
- [ ] Promote only later-period winner of the predefined comparison.
- [ ] Commit `feat: add contextual score distribution models`.

### Task 11: Residual Error-Correction

**Files:**
- Create: `v5_residual_model.py`
- Create: `tests/test_v5_residual_model.py`

**Interfaces:**
- `fit_residual_model(oof_predictions: pd.DataFrame, features: pd.DataFrame, target: str) -> object`

- [ ] Refuse in-sample base predictions via assertion on fold metadata.
- [ ] Train winner-logit, margin, and total residual candidates only on OOF/walk-forward residuals.
- [ ] Reject if improvement disappears on later period or if player/event identity dominates attribution.
- [ ] Commit `feat: add residual correction experiments`.

### Task 12: Ensemble + Disagreement

**Files:**
- Create: `v5_ensemble.py`
- Create: `tests/test_v5_ensemble.py`

**Interfaces:**
- `fit_ensemble(oof_model_predictions: pd.DataFrame, y: np.ndarray) -> object`
- `ensemble_features(...) -> dict[str, float]`

- [ ] Combine mechanistic, Elo, contextual ML, score consistency, and residual outputs using OOF predictions only.
- [ ] Add range/std/entropy and pairwise disagreement metrics.
- [ ] Test whether disagreement predicts calibration error; use for confidence only if validated.
- [ ] Commit `feat: add validated ensemble and disagreement layer`.

### Task 13: Unified Walk-Forward Experiment Runner

**Files:**
- Create: `v5_experiments.py`
- Create: `run_v5_walkforward_experiments.py`
- Create: `tests/test_v5_experiments.py`

**Interfaces:**
- `run_experiment(config: ExperimentConfig) -> ExperimentResult`

- [ ] Enforce chronological folds and immutable feature-set/model versions.
- [ ] Record git SHA, train/validation windows, hyperparameters, seeds, aggregate/segment metrics, promotion decision, reason.
- [ ] Preserve rejected experiment summaries under `experiments/registry/`.
- [ ] Add leakage sentinel test with deliberately future-shifted feature.
- [ ] Commit `feat: add experiment governance and walkforward runner`.

### Task 14: Historical Odds / ROI / CLV Evaluation

**Files:**
- Modify: `historical_backtest_engine.py`
- Create: `v5_market_evaluation.py`
- Create: `tests/test_v5_market_evaluation.py`

**Interfaces:**
- `evaluate_market_edges(frozen_model_rows: pd.DataFrame, historical_odds: pd.DataFrame) -> dict`

- [ ] Assert model prediction timestamps precede odds joins and outcomes.
- [ ] Evaluate no-vig edge, EV, realized ROI, units, CLV where available, market/bookmaker/edge-size/confidence segments.
- [ ] Do not alter underlying probabilities based on market results.
- [ ] Commit `feat: add post-prediction market evaluation`.

### Task 15: Live V5 Integration + Production Acceptance

**Files:**
- Modify: `v5_daily_batch.py`
- Modify: `v5_live_market.py`
- Modify: existing daily workflows
- Create: `tests/test_v5_full_context_live.py`

**Interfaces:**
- Live flow consumes only promoted feature/model versions from experiment registry.

- [ ] Build live context using same feature builders as historical replay.
- [ ] Freeze independent predictions before market join.
- [ ] Add provenance/model-version/context-quality fields to frozen ledger.
- [ ] Preserve existing settlement behavior.
- [ ] Run full regression suite plus a shadow live board comparing current production vs full-context candidate.
- [ ] Promote components only when acceptance criteria are met; keep rejected components inactive but documented.
- [ ] Commit `feat: integrate validated full-context model into live V5`.

## Final Verification

- [ ] Run all tests: `pytest -q`.
- [ ] Run canonical warehouse workflow successfully.
- [ ] Run complete walk-forward experiment suite and save registry artifacts.
- [ ] Confirm no market columns are present in model-training feature manifests.
- [ ] Confirm historical/live feature parity tests pass.
- [ ] Confirm no-lookahead sentinel tests pass.
- [ ] Compare accepted model against current V5 on untouched/later data; require documented improvement before production promotion.
- [ ] Compare live shadow board distributions only as diagnostics, never as tuning targets.
