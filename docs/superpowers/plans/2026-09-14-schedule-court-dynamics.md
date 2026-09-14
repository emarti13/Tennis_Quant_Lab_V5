# Schedule Court Dynamics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reconcile the supplemental tennis schedule to authoritative V5 warehouse events and use confidently matched structural venue context as a leak-safe fallback prior for dynamic court speed.

**Architecture:** The historical warehouse remains the event/match universe. A focused schedule matcher resolves cross-source event names with scored candidate matching and explicit confidence, enriching warehouse rows only when a match is reliable. The existing streaming court-speed engine then learns structural cohort priors from historically observed residuals before blending current-event evidence. Unmatched warehouse events remain fully valid and retain existing same-event and generic fallbacks.

**Tech Stack:** Python 3.12, pandas, numpy, pytest, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-14-schedule-court-dynamics-design.md`

## Global Constraints
- The historical warehouse is authoritative for which events/matches exist.
- The schedule is supplemental and may contain holes; schedule row count is not a completeness requirement.
- Never drop, reject, or invalidate a warehouse event because schedule enrichment is unavailable.
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
- [ ] Confirm the schedule loads as a valid supplemental source without asserting it is the complete event universe.
- [ ] Implement the schedule loader/normalizer.
- [ ] Run targeted tests and confirm GREEN.
- [ ] Commit.

### Task 2: Cross-source event reconciliation
**Files:** Modify `v5_schedule_context.py`; Test `tests/test_v5_schedule_context.py`.

**Interfaces:** `match_schedule_event(event, schedule) -> dict`; `enrich_events_with_schedule(events, schedule) -> DataFrame`.

- [ ] Add tests for exact, sponsor/alias, fuzzy-high, city-assisted, incompatible-tour/surface and ambiguous matches.
- [ ] Add a regression proving unmatched warehouse events survive unchanged apart from unavailable schedule fields.
- [ ] Implement candidate filtering, similarity scoring, confidence threshold and runner-up margin.
- [ ] Persist match method, score, candidate count and matched schedule name.
- [ ] Run targeted tests and confirm GREEN.
- [ ] Commit.

### Task 3: Merge schedule context into the V5 context pipeline
**Files:** Modify `build_v5_context_matchups.py`; test relevant context integration.

**Interfaces:** Warehouse/player rows retain their original identity and gain schedule fields only when reconciliation succeeds.

- [ ] Prove a differently named schedule event can enrich a warehouse event.
- [ ] Prove an unmatched warehouse event remains in output.
- [ ] Merge schedule enrichment into context construction without filtering source rows.
- [ ] Run targeted tests and confirm GREEN.
- [ ] Commit.

### Task 4: Add schedule-structural court-speed prior
**Files:** Modify `v5_court_speed.py`; Test `tests/test_v5_schedule_court_speed.py` and `tests/test_v5_court_speed.py`.

**Interfaces:** Court-speed observations include schedule structural keys where available; output adds `court_speed_structural_prior`, sample size and uncertainty.

- [ ] Prove same-event history wins.
- [ ] Prove schedule structural cohort is second fallback only when schedule context exists.
- [ ] Prove generic tour/surface/indoor remains the fallback for unmatched events.
- [ ] Prove future/same-time rows never affect prior.
- [ ] Preserve existing blended/current-event behavior.
- [ ] Run targeted tests and confirm GREEN.
- [ ] Commit.

### Task 5: Production model/context integration and QC
**Files:** Modify `build_v5_context_matchups.py` and tests under `tests/`.

**Interfaces:** Shared context exposes new numeric structural court-speed features while preserving existing model inputs; schedule matching QC reports resolved/ambiguous/unmatched coverage informationally.

- [ ] Add tests for feature propagation and QC counts.
- [ ] Ensure low schedule coverage does not fail production by itself.
- [ ] Implement propagation without changing existing feature names.
- [ ] Run context/model targeted tests.
- [ ] Commit.

### Task 6: Full verification and merge
- [ ] Run complete pytest suite.
- [ ] Run Streamlit smoke test.
- [ ] Inspect schedule-match coverage/QC on available repository artifacts as an enrichment metric, not a completeness gate.
- [ ] Open/update PR with source-authority rule and unresolved-event behavior.
- [ ] Merge only after CI passes.
- [ ] Verify merged files and production-facing interfaces on `main`.
