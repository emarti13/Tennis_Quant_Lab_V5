# V5 Self-Functioning Production Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert V5 into a self-functioning production system that stays comfortably under 3,000 GitHub Actions minutes/month while preserving one daily model forecast, one lightweight market repricing per day for the time being, one official recommendation per market, and statistically honest settlement/performance.

**Architecture:** Separate expensive sportsbook-independent forecasting from cheap sportsbook-dependent repricing. Freeze one canonical model forecast ledger daily; the current quota-conservation cadence performs one OddsPapi refresh per day, which only normalizes prices, joins them to the frozen forecast, re-evaluates price-dependent policy states, appends market history, and updates a first-crossing official recommendation ledger. Settlement consumes only official recommendations. All canonical artifacts use last-known-good promotion and explicit health states. Market refresh frequency can be increased later when API capacity supports it without compromising production reliability.

**Tech Stack:** Python 3.12, pandas, Streamlit, GitHub Actions, existing V5 model/context/settlement modules.

**Spec:** `docs/superpowers/specs/2026-09-08-self-functioning-production-pipeline-design.md`

## Global Constraints

- Hard GitHub-hosted Actions budget: 3,000 minutes/month; target comfortably below 80%.
- Current OddsPapi production cadence: one scheduled market refresh/repricing per day for the time being.
- Do not change accepted winner/score model mathematics.
- Do not tune recommendation thresholds on already-observed live outcomes.
- Do not rewrite historical frozen predictions.
- Stale sportsbook prices may never generate BET/LEAN.
- Routine data refreshes must not run the full repository regression suite.
- Canonical artifacts must be last-known-good promoted only after validation.
- One market key may contribute at most one official settled recommendation.

---

### Task 1: Forecast / Repricing Artifact Contracts

**Files:**
- Create: `v5_production_artifacts.py`
- Create: `tests/test_v5_production_artifacts.py`

**Interfaces:**
- Produces stable market key normalization, artifact validation/promotion helpers, and status artifact writer.
- Used by forecast generation, repricing, settlement, and UI.

- [ ] Write failing tests for stable market keys, atomic last-known-good promotion, and status payload schema.
- [ ] Verify RED.
- [ ] Implement minimal helpers.
- [ ] Verify focused tests GREEN.
- [ ] Commit.

### Task 2: Daily Sportsbook-Independent Forecast Ledger

**Files:**
- Modify: `v5_daily_batch.py`
- Create: `tests/test_v5_daily_forecast_ledger.py`
- Modify: `.github/workflows/v5_daily_predictions.yml`

**Interfaces:**
- Produces: `v5_daily_ready/daily_forecasts.csv` and `v5_daily_ready/forecast_status.json`.
- One row per fixture/model-version/day with winner/score probabilities, model candidates, context/state metadata, generated timestamp.
- No market price, EV, or signal field is part of forecast identity.

- [ ] Write failing tests proving same fixture is written once per forecast day and outputs contain no sportsbook-dependent signal/EV fields.
- [ ] Verify RED.
- [ ] Add forecast-ledger export from existing accepted production batch outputs without changing model math.
- [ ] Change workflow to one heavy daily forecast run; run only focused contracts, context build, model batch, and forecast promotion.
- [ ] Verify focused tests GREEN.
- [ ] Commit.

### Task 3: Lightweight Daily Repricing

**Files:**
- Create: `v5_reprice_markets.py`
- Create: `tests/test_v5_repricing.py`
- Modify: `.github/workflows/oddspapi_normalized_daily_v2.yml`

**Interfaces:**
- Consumes latest valid `daily_forecasts.csv` plus fresh normalized OddsPapi market rows.
- Produces `v5_daily_ready/latest_repriced_board.csv`, `v5_daily_ready/market_snapshot_history.csv`, and `v5_daily_ready/repricing_status.json`.
- Recomputes only market/no-vig probability, edge, EV, and existing signal policy from frozen probabilities/distributions.

- [ ] Write failing tests proving probabilities remain identical across repeated same-day repricing snapshots while EV/signals can change with price.
- [ ] Write failing test that stale price input cannot emit BET/LEAN.
- [ ] Verify RED.
- [ ] Implement repricer using existing `add_model_pricing` / signal policy semantics and frozen forecast outputs.
- [ ] Wire OddsPapi workflow to run repricing immediately after validated market-feed promotion, without context rebuild/full simulation/full regression.
- [ ] Configure one scheduled OddsPapi refresh/repricing per day for the time being under the current quota constraint.
- [ ] Verify focused tests GREEN.
- [ ] Commit.

### Task 4: First-Crossing Official Recommendation Ledger

**Files:**
- Create: `v5_recommendation_ledger.py`
- Create: `tests/test_v5_recommendation_ledger.py`
- Modify: `v5_reprice_markets.py`

**Interfaces:**
- Produces: `v5_daily_ready/official_recommendations.csv` and optional append-only recommendation audit history.
- Stable market key: fixture + market group + normalized selection + normalized line.

- [ ] Write failing tests for PASS/REVIEW no-op, first LEAN creation, later BET supersession before start, first BET freeze, duplicate snapshot suppression, immutable frozen price/probability/timestamp, and no post-start recommendation.
- [ ] Verify RED.
- [ ] Implement idempotent first-crossing ledger update.
- [ ] Integrate into repricing job.
- [ ] Verify focused tests GREEN.
- [ ] Commit.

### Task 5: Settlement and Performance Consume Official Recommendations Only

**Files:**
- Modify: `v5_settlement.py`
- Modify: `diagnose_v5_settled_performance.py`
- Modify: `results_accuracy_page.py` and/or current Results/Performance loaders as required
- Create: `tests/test_v5_official_recommendation_settlement.py`

**Interfaces:**
- Settlement consumes `official_recommendations.csv` for current-engine headline performance.
- Legacy frozen history remains separate and immutable.

- [ ] Write failing tests showing repeated repricing snapshots for one market settle once, PASS/REVIEW do not enter headline record, and legacy/current scopes remain distinct.
- [ ] Verify RED.
- [ ] Modify settlement/audit pipeline to use official current-engine recommendations.
- [ ] Add median odds, favorite/underdog mix, price bands, unique fixtures, max recommendations/fixture, and retirement sensitivity when metadata exists.
- [ ] Verify focused tests GREEN.
- [ ] Commit.

### Task 6: Today / Match Detail Read Forecast + Repricing Artifacts

**Files:**
- Modify: `v5_ui_host.py`
- Modify: `v5_ui_today.py`
- Modify: `v5_ui_match_detail.py`
- Create: `tests/test_v5_ui_production_artifacts.py`

**Interfaces:**
- Today no longer has to run the heavy model manually for normal daily use.
- Reads canonical daily forecast + latest repriced board; advanced/manual run remains recovery/debug only if retained.

- [ ] Write failing UI contracts for READY, STALE_PRICES, NO_FUTURE_FIXTURES, MISSING, and current recommendation ledger display.
- [ ] Verify RED.
- [ ] Wire Today to latest repriced production artifact and explicit status artifacts.
- [ ] Keep stale fixture visibility but hide/disable actionable stale recommendations.
- [ ] Verify focused UI tests GREEN.
- [ ] Commit.

### Task 7: Actions Budget and Workflow Fan-Out Guardrails

**Files:**
- Modify: `.github/workflows/v5_player_ratings_refresh.yml`
- Modify: `.github/workflows/v5_daily_predictions.yml`
- Modify: `.github/workflows/oddspapi_normalized_daily_v2.yml`
- Modify: `.github/workflows/v5_automatic_settlement.yml`
- Modify: `.github/workflows/oddspapi_2026_backfill.yml`
- Create: `v5_actions_budget.py`
- Create: `tests/test_v5_actions_budget.py`

**Interfaces:**
- Encodes configured monthly run counts and expected minute ceilings.
- Production jobs have isolated concurrency; historical jobs cannot block/cancel production.

- [ ] Write failing tests enforcing one lightweight market run/day for the current quota-conservation configuration, one heavy forecast/day, one settlement/day, low-cadence backfill, no duplicate triggers, no full suite in routine jobs, and projected monthly usage < 2,400 minutes (80% of budget).
- [ ] Verify RED.
- [ ] Implement budget estimator and finalize workflow cadences/trigger isolation.
- [ ] Verify focused tests GREEN.
- [ ] Commit.

### Task 8: End-to-End Production Contract

**Files:**
- Create: `tests/test_v5_self_functioning_pipeline.py`
- Modify status/artifact modules only if contract exposes a real gap.

**Interfaces:**
- Synthetic lifecycle: one forecast → one or more price snapshots → changing signals → one official recommendation → one settlement.

- [ ] Write end-to-end test with repeated price snapshots for one market so idempotence remains proven independent of the currently configured daily cadence.
- [ ] Assert model probability never changes, official recommendation count <= 1 per market key, first BET is immutable, settlement count = 1, and performance count = 1.
- [ ] Verify RED if any integration gap remains.
- [ ] Fix only identified integration gaps.
- [ ] Verify focused integration test GREEN.
- [ ] Commit.

### Task 9: Verification, Streamlit Smoke, and Merge

**Files:**
- No production feature expansion.

- [ ] Run all new production-pipeline tests.
- [ ] Run full repository regression once on the final feature branch.
- [ ] Run Streamlit smoke once.
- [ ] Verify no model probability/output invariance regression.
- [ ] Review branch diff for unrelated changes/debug scaffolding.
- [ ] Create PR, review, merge only after executable verification is green; if Actions minutes block hosted CI, report that explicitly and do not claim green.
- [ ] Post-merge verify canonical workflow definitions and production artifact readers on `main`.
