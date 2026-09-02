# Stage 1 Context Warehouse Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first production-grade canonical historical match warehouse that converts existing TennisMyLife-style ATP/WTA/Challenger/qualifying CSV inputs into stable match rows, two player rows per match, explicit source provenance, and schema metadata without disturbing the existing V5 refresh/prediction pipeline.

**Architecture:** Add a standalone `context_warehouse` package and CLI. Source adapters normalize existing wide winner/loser match files into a canonical match table; deterministic identifiers and provenance are created before downstream feature engineering. Stage 1 writes CSV always and Parquet when a parquet engine is available, so GitHub Actions and local Windows execution remain robust.

**Tech Stack:** Python 3.12, pandas, hashlib/json/pathlib from the standard library, unittest for zero-dependency test execution, optional pyarrow/fastparquet for Parquet output.

**Spec:** `docs/superpowers/specs/2026-09-01-full-context-tennis-model-design.md` on `design/full-context-tennis-model`, plus binding amendment `docs/superpowers/specs/2026-09-02-court-speed-amendment.md` on this branch.

## Global Constraints

- No lookahead: Stage 1 stores factual match records and provenance only; later feature builders must enforce as-of cutoffs.
- Independent tennis prediction first: no bookmaker price, no-vig probability, line, or recommendation field is part of the canonical tennis state contract.
- Forward-only integration: existing refresh, odds, frozen-ledger, settlement, and market systems remain unchanged.
- Missing source fields stay null; missing duration/rank/timestamps are never silently replaced with zero.
- IDs must be deterministic across reruns for the same canonical record.
- Winner/loser outcome fields live in canonical post-match match rows; player rows carry `is_winner` only as historical outcome data and are never used by pre-match feature code without an as-of gate.

---

## File Structure

- `context_warehouse/__init__.py` — public Stage 1 interfaces.
- `context_warehouse/schema.py` — canonical column lists and schema version.
- `context_warehouse/normalize.py` — deterministic normalization, IDs, and wide-to-canonical conversion.
- `context_warehouse/io.py` — source loading and auditable CSV/optional-Parquet output.
- `build_context_warehouse.py` — CLI orchestration only.
- `tests/test_context_warehouse.py` — deterministic identity, normalization, two-player-row, missing-value, and provenance tests.
- `.github/workflows/context_warehouse_tests.yml` — isolated branch-safe CI verification.

### Task 1: Define the canonical contract with failing tests

**Files:**
- Create: `tests/test_context_warehouse.py`
- Create later: `context_warehouse/schema.py`, `context_warehouse/normalize.py`

**Interfaces:**
- Consumes: pandas `DataFrame` containing TennisMyLife/Jeff-Sackmann-style winner/loser columns.
- Produces: `canonicalize_matches(frame: pd.DataFrame, tour: str, level: str, source_name: str) -> pd.DataFrame`; `build_player_match_rows(matches: pd.DataFrame) -> pd.DataFrame`.

- [ ] **Step 1: Write tests first** for deterministic `match_id`, preserved null ranking, normalized surface/date, and exactly two player rows per match.
- [ ] **Step 2: Add CI workflow** that runs `python -m unittest discover -s tests -p 'test_context_warehouse.py' -v` on pushes affecting Stage 1 files.
- [ ] **Step 3: Push only tests/workflow and verify RED.** Expected failure: import error for missing `context_warehouse` package.

### Task 2: Implement schema and normalization minimally

**Files:**
- Create: `context_warehouse/__init__.py`
- Create: `context_warehouse/schema.py`
- Create: `context_warehouse/normalize.py`

**Interfaces:**
- `SCHEMA_VERSION: str = '1.0.0'`
- `canonicalize_matches(...)` returns one canonical row per valid source match.
- `build_player_match_rows(...)` returns exactly two rows per canonical match, with `player_side` in `{winner, loser}` and deterministic `player_id`.

- [ ] **Step 1:** Implement only enough normalization and deterministic SHA-256 based IDs to satisfy Task 1 tests.
- [ ] **Step 2:** Verify the Stage 1 test workflow is GREEN.
- [ ] **Step 3:** Confirm no existing V5 files are modified by import or test execution.

### Task 3: Add provenance and duplicate handling with tests first

**Files:**
- Modify: `tests/test_context_warehouse.py`
- Modify: `context_warehouse/normalize.py`

**Interfaces:**
- Canonical rows include `source_name`, `source_row_number`, `source_tourney_id`, `source_match_num`, `ingest_schema_version`.
- Duplicate source records sharing the same deterministic match identity collapse to one canonical match.

- [ ] **Step 1:** Add failing tests proving duplicate collapse and source provenance.
- [ ] **Step 2:** Verify RED for the missing behavior.
- [ ] **Step 3:** Implement minimal behavior.
- [ ] **Step 4:** Verify GREEN.

### Task 4: Add durable writer and manifest with tests first

**Files:**
- Modify: `tests/test_context_warehouse.py`
- Create: `context_warehouse/io.py`

**Interfaces:**
- `write_warehouse(matches, player_rows, output_dir, source_manifest) -> dict`
- Required durable files: `matches.csv`, `player_match_rows.csv`, `source_manifest.json`, `schema.json`.
- Preferred optional files: `matches.parquet`, `player_match_rows.parquet` if a parquet engine is available.

- [ ] **Step 1:** Add failing temp-directory tests for required CSV/JSON outputs and manifest row counts.
- [ ] **Step 2:** Verify RED.
- [ ] **Step 3:** Implement atomic-ish write-to-temp then replace behavior for JSON/CSV outputs; Parquet failure must be recorded, not fatal.
- [ ] **Step 4:** Verify GREEN.

### Task 5: Add CLI adapter for current four source families with tests first

**Files:**
- Modify: `tests/test_context_warehouse.py`
- Create: `build_context_warehouse.py`

**Interfaces:**
- CLI accepts repeated `--input TOUR:LEVEL:PATH` values.
- Default mappings support `ATP.csv`, `ATPQualifiers.csv`, `Challenger.csv`, and `WTA.csv` when explicitly passed by workflow/local caller.
- `--output-dir` defaults to `context_warehouse_output` to avoid collision with Python package directory.

- [ ] **Step 1:** Add failing parser/orchestration tests using temporary CSV fixtures.
- [ ] **Step 2:** Verify RED.
- [ ] **Step 3:** Implement CLI that concatenates normalized sources, deduplicates canonical identities, builds player rows, and writes the manifest.
- [ ] **Step 4:** Verify GREEN.

### Task 6: Integration smoke test against synthetic ATP/WTA history

**Files:**
- Modify: `tests/test_context_warehouse.py`
- Modify only if required: Stage 1 implementation files.

**Interfaces:**
- A mixed MEN/WTA synthetic input produces a warehouse with stable IDs, correct tour/level metadata, exactly 2N player rows, no bookmaker fields, and no zero-filled missing ranks.

- [ ] **Step 1:** Add the integration test before any integration-specific implementation.
- [ ] **Step 2:** Verify RED only if behavior is not already satisfied; if it passes immediately because prior tasks fully implement the contract, document that no new production behavior is required.
- [ ] **Step 3:** Run full `unittest discover` suite.
- [ ] **Step 4:** Run the CLI on the synthetic fixtures and inspect `schema.json`/`source_manifest.json` row counts.

### Task 7: Stage 1 acceptance gate

**Files:**
- Create: `docs/experiments/2026-09-02-stage1-context-warehouse.md`

- [ ] **Step 1:** Record branch SHA, test workflow run, schema version, tests passed, known source-field coverage, and any Parquet engine availability result.
- [ ] **Step 2:** Verify the branch still descends from the inspected `main` baseline `a7779f81d1759be2ea2f0f530e85a19166d8e8ba` or rebase/refresh before merge if main advanced.
- [ ] **Step 3:** Do not touch production prediction wiring yet. Stage 2 begins only after Stage 1 contract and leakage/provenance foundations are accepted.

## Self-Review

Spec coverage for Stage 1 is complete: canonical match grain, deterministic IDs, tour/event/surface/date/player/result/rank fields where supplied, source provenance, durable match/player outputs, schema metadata, missing-value preservation, and forward-only isolation are covered. The court-speed amendment is intentionally not implemented in Stage 1; Stage 1 provides the historical record required for its later strict-as-of computation. No sportsbook inputs enter this subsystem.

No placeholder tasks remain. Interfaces are intentionally small and reusable by Stage 2 historical replay and live adapters.