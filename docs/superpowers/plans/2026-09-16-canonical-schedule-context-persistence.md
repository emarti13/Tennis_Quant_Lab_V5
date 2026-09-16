# Canonical Schedule Context Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make official schedules authoritative for tournament identity/surface, reliably attach existing enrichment, and persist Daily Board corrections only after a successful RUN ADJUSTED DAILY BOARD transaction.

**Architecture:** Add a canonical schedule registry and resolver in front of the existing context enrichment/override layer. Re-key enrichment to canonical IDs, then make the Daily Board adjusted-run button the sole persistence transaction boundary with rollback-on-run-failure and write/read-back verification.

**Tech Stack:** Python, pandas, Streamlit, pytest, existing V5 production/context modules.

**Spec:** `docs/superpowers/specs/2026-09-16-canonical-schedule-context-persistence-design.md`

## Global Constraints
- Official ATP/Challenger/WTA/WTA125 schedule identity and surface outrank inferred/fuzzy context.
- Preserve indoor/outdoor surface information.
- Never city-only fuzzy-merge distinct tournaments.
- Preserve valid existing enrichment; re-key it rather than replacing it.
- Widget edits alone never persist.
- Only a successful RUN ADJUSTED DAILY BOARD may commit changed fields.
- Failed adjusted runs commit nothing.
- Frozen historical recommendations remain immutable.

---

### Task 1: Canonical schedule registry and surface normalization
**Files:** Create focused canonical schedule module/data under `context_registry/`; add tests under `tests/`.
**Produces:** canonical tournament ID, official name, season, tour/category, location/date identity, normalized surface/environment.
- [ ] Write failing tests for ATP, Challenger, WTA Tour, WTA125 and H/IH/C/CL/IC/G normalization.
- [ ] Implement registry/parser representation using schedule-derived records.
- [ ] Verify tests and commit.

### Task 2: Deterministic tournament identity resolver
**Files:** Modify/add resolver near existing context registry; integrate with `v5_daily_batch.py`/interactive path as appropriate.
**Produces:** resolved canonical ID plus resolution status/source.
- [ ] Write failing tests for aliases, season/category discrimination and ambiguity fail-closed behavior.
- [ ] Add explicit regression: WTA `SP Open`/`WTA Sao Paulo, Brazil Women, Singles` -> WTA hard event; Sao Paulo Challenger -> Challenger clay event.
- [ ] Implement strongest-key resolution before controlled aliases; prohibit loose city-only collision.
- [ ] Verify and commit.

### Task 3: Re-key existing enrichment to canonical identity
**Files:** Context warehouse/registry generation and tests.
**Produces:** canonical context rows retaining altitude, ball, court speed/CPI, ace/rally, air-density/environment and other validated fields.
- [ ] Write tests proving enrichment survives identity migration.
- [ ] Build non-destructive re-key/join path with unmatched/ambiguous diagnostics.
- [ ] Verify no valid enrichment is silently dropped and commit.

### Task 4: Context completeness/data-quality gate
**Files:** Context refresh/status reporting and Daily Board assembly tests.
- [ ] Write tests distinguishing `unresolved` from genuinely unavailable/missing.
- [ ] Treat expected context-source 0/N matching as a production blocker/diagnostic failure.
- [ ] Ensure scheduled tournament identity/surface cannot silently render blank.
- [ ] Add completeness counts/unresolved IDs to diagnostics and commit.

### Task 5: Transactional RUN ADJUSTED DAILY BOARD persistence
**Files:** `v5_ui_daily_board.py`, persistent context registry interface, interactive production tests.
- [ ] Write test proving widget edits alone cause zero persistent writes.
- [ ] Write test proving adjusted-run failure causes zero persistent writes.
- [ ] Write test proving successful adjusted run persists only fields changed from canonical resolved values.
- [ ] Move persistence to after successful production rerun.
- [ ] Reload registry and verify read-back before reporting durable success.
- [ ] Verify later fixture inherits correction and similarly named tournament does not.
- [ ] Commit.

### Task 6: Production integration and regression verification
**Files:** Existing production regression/smoke tests and relevant docs/status artifacts.
- [ ] Run focused canonical/context/persistence tests.
- [ ] Run full regression suite.
- [ ] Run Streamlit/production-equivalent Daily Board smoke test.
- [ ] Inspect a current slate: official tournament/surface populated; enrichment attached where available; unresolved fields explicitly diagnosed.
- [ ] Specifically inspect WTA Sao Paulo as Hard and confirm no Challenger clay collision.
- [ ] Confirm frozen recommendation history unchanged.
- [ ] Commit final verification evidence and prepare PR for review/merge.