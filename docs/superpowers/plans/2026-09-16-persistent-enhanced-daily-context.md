# Persistent Enhanced Daily Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make enhanced tournament context editable, durable, reusable, and active in live Daily Board predictions.

**Architecture:** Add one canonical tournament override registry and resolver. Daily Board edits write through it; production context resolution overlays it before live feature construction. Missing values stay missing and existing frozen history remains immutable.

**Tech Stack:** Python, pandas, Streamlit, pytest, GitHub Actions

**Spec:** `docs/superpowers/specs/2026-09-16-persistent-enhanced-daily-context-design.md`

## Global Constraints
- One canonical production source of truth.
- No sportsbook information enters model features.
- No silent zero/default substitution for missing enhanced context.
- Frozen historical recommendations are immutable.
- Persist edits by canonical tournament identity, not fixture ID.

---

### Task 1: Canonical tournament override registry
**Files:** Create `v5_tournament_context_registry.py`; create `tests/test_tournament_context_registry.py`.
**Interfaces:** `canonical_tournament_key(name) -> str`; `load_overrides(path) -> DataFrame`; `apply_overrides(frame, overrides) -> DataFrame`; `upsert_tournament_context(path, tournament, values) -> DataFrame`.
- [ ] Write failing tests for persistence, inheritance, replacement, and missing-value preservation.
- [ ] Run focused pytest and verify RED.
- [ ] Implement the minimal registry/resolver.
- [ ] Run focused pytest and verify GREEN.
- [ ] Commit.

### Task 2: Daily Board write-through and categorical controls
**Files:** Modify `v5_ui_daily_board.py`; modify `v5_interactive_production.py`; create/modify focused UI/interactive tests.
**Interfaces:** Daily Board sends changed tournament context to the registry before recalculation; interactive production resolves persisted context into fixture overrides.
- [ ] Write failing tests proving saved tournament context is inherited by a fresh fixture and categorical Ball Type/Surface values are accepted.
- [ ] Run focused tests and verify RED.
- [ ] Implement persistence hook and registry overlay.
- [ ] Run focused tests and verify GREEN.
- [ ] Commit.

### Task 3: Production feature parity
**Files:** Modify `v5_daily_batch.py` and/or `v5_full_context_live.py` only where required; add focused production-context tests.
**Interfaces:** Resolved tournament context reaches `build_live_matchup_features_from_enriched` and the validated enhanced winner/score candidates; absent fields remain missing.
- [ ] Write failing tests proving present altitude/ball/court values affect the live feature row while absent values remain missing rather than zero.
- [ ] Run focused tests and verify RED.
- [ ] Implement minimal production resolver integration.
- [ ] Run focused tests and verify GREEN.
- [ ] Commit.

### Task 4: Durable deployed persistence and refresh overlay
**Files:** Add backend write adapter and refresh overlay integration; update workflow only if required.
**Interfaces:** Local registry write is atomic; deployed write-through persists the registry to the repository when a configured credential is available; refresh loads the same registry before emitting canonical context artifacts.
- [ ] Write failing tests for remote-write success/failure contract and refresh overlay.
- [ ] Run focused tests and verify RED.
- [ ] Implement adapter without embedding credentials.
- [ ] Run focused tests and verify GREEN.
- [ ] Commit.

### Task 5: End-to-end verification
**Files:** No behavior change unless verification exposes a defect.
- [ ] Run focused registry/context/UI tests.
- [ ] Run full regression suite.
- [ ] Run Streamlit smoke test.
- [ ] Trigger production-equivalent Daily Board build and inspect output for enhanced candidate plus populated context fields.
- [ ] Verify historical frozen rows were not rewritten.
- [ ] Open PR with exact verification evidence.