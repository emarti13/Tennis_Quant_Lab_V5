# Schedule Court Dynamics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reconcile the comprehensive tennis schedule to V5 events and use the matched structural venue context as a leak-safe fallback prior for dynamic court speed.

**Architecture:** Add a focused schedule matcher that resolves cross-source event names with scored candidate matching and explicit confidence. Merge resolved schedule fields into the tournament registry/player rows, then let the existing streaming court-speed engine learn structural cohort priors from historical residuals before blending current-event evidence.

**Tech Stack:** Python 3.12, pandas, numpy, pytest, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-14-schedule-court-dynamics-design.md`

## Global Constraints
- Never treat a failed raw-name join as final without candidate matching.
- Ambiguous event matches fail closed.
- No future-event or same-timestamp leakage.
- Schedule labels inform priors through historical observed residuals, not arbitrary betting coefficients.
- Existing production court-speed outputs remain backward compatible.

---

### Task 1: Version and normalize the schedule source
**Files:** Create `context_registry/tennis_master_schedule.csv`; Create `v5_schedule_context.py`; Test `tests/test_v5_schedule_context.py`.

**Interfaces:** `load_schedule(path) -> DataFrame`; `normalize_schedule(frame) -> DataFrame`; `speed_profile_family(value) -> str`.

- [ ] Write tests for year suffix removal, tour-family normalization, setting normalization, altitude parsing and speed-profile family normalization.
- [ ] Run targeted tests and confirm RED.
- [ ] Implement the schedule loader/normalizer.
- [ ] Run targeted tests and confirm GREEN.
- [ ] Commit.

### Task 2: Cross-source event reconciliation
**Files:** Modify `v5_schedule_context.py`; Test `tests/test_v5_schedule_context.py`.

**Interfaces:** `match_schedule_event(event, schedule) -> dict`; `enrich_events_with_schedule(events, schedule) -> DataFrame`.

- [ ] Add failing tests for exact, sponsor/alias, fuzzy-high, city-assisted, incompatible-tour/surface and ambiguous matches.
- [ ] Run targeted tests and confirm RED.
- [ ] Implement candidate filtering, similarity scoring, confidence threshold and runner-up margin.
- [ ] Persist match method, score, candidate count and matched schedule name.
- [ ] Run targeted tests and confirm GREEN.
- [ ] Commit.

### Task 3: Merge schedule context into the V5 tournament registry
**Files:** Modify `build_v5_venue_registry.py`, `v5_tournament_registry.py`, `v5_travel_features.py`; Test `tests/test_v5_schedule_context.py` and relevant venue/travel tests.

**Interfaces:** Registry rows carry schedule fields; `TournamentContext` exposes those fields; travel enrichment copies them to player rows.

- [ ] Write failing integration test proving a warehouse event with a differently named schedule event receives structural metadata.
- [ ] Run test and confirm RED.
- [ ] Merge schedule enrichment into venue-registry build.
- [ ] Extend TournamentContext and travel feature output with schedule metadata.
- [ ] Run targeted tests and confirm GREEN.
- [ ] Commit.

### Task 4: Add schedule-structural court-speed prior
**Files:** Modify `v5_court_speed.py`; Test `tests/test_v5_court_speed.py`.

**Interfaces:** Court-speed observations include schedule structural keys; output adds `court_speed_structural_prior`, sample size and uncertainty.

- [ ] Write failing tests proving same-event history wins, schedule structural cohort is second fallback, generic tour/surface/indoor is third fallback, and future/same-time rows never affect prior.
- [ ] Run targeted tests and confirm RED.
- [ ] Implement structural cohort state and fallback hierarchy in streaming court-speed engine.
- [ ] Preserve existing blended/current-event behavior.
- [ ] Run targeted tests and confirm GREEN.
- [ ] Commit.

### Task 5: Production model/context integration and QC
**Files:** Modify `build_v5_context_matchups.py`, `v5_player_state.py` if required; add/modify tests under `tests/`.

**Interfaces:** Shared context exposes the new numeric structural court-speed feature while preserving existing model inputs; schedule matching QC exposes resolved/ambiguous/unmatched counts.

- [ ] Add failing tests for feature propagation and QC counts.
- [ ] Implement propagation without changing existing feature names.
- [ ] Run context/model targeted tests.
- [ ] Commit.

### Task 6: Full verification and merge
- [ ] Run complete pytest suite.
- [ ] Run Streamlit smoke test.
- [ ] Inspect schedule-match coverage/QC on available repository artifacts.
- [ ] Open PR with exact coverage and unresolved-event report.
- [ ] Merge only after CI passes.
- [ ] Verify merged files and production-facing interfaces on `main`.
