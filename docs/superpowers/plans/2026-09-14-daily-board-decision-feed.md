# Daily Board + Decision Feed Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the full interactive Daily Board as V5's primary operator workspace, retain cards as a separate Decision Feed driven by the same active board state, and quantitatively diagnose the all-REVIEW signal policy before any official policy change.

**Architecture:** One normalized board is the UI contract. Canonical production artifacts populate the default board; interactive reruns create session-only adjusted board state without mutating frozen production artifacts. Decision Feed is a pure ranking/presentation consumer of that active board. Signal-policy research is isolated from UI restoration and may change official signals only after chronological/OOS evidence supports promotion.

**Tech Stack:** Python, pandas, Streamlit, pytest/unittest, existing V5 production artifacts and simulation/context modules.

**Spec:** `docs/superpowers/specs/2026-09-14-daily-board-decision-feed-design.md`

## Global Constraints

- `PROJECT_MANDATE.md` is the highest-level acceptance contract.
- Preserve one canonical production source of truth and frozen official forecasts.
- No heavy upstream model/context/history rebuild during passive Streamlit page loads.
- Adjusted scenarios are session-only and never write the recommendation ledger or historical production artifacts.
- CourtSpeed remains primary where covered; V5 fallback remains automatic.
- Raw CPI remains distinct from the internal V5 court-speed scale.
- Do not alter the official signal policy without chronological/OOS evidence.
- Use TDD for every behavior change and run the full regression plus Streamlit smoke before completion.

---

### Task 1: Normalize active board state and mode metadata

**Files:**
- Modify: `v5_interactive_production.py`
- Create: `v5_active_board.py`
- Test: `tests/test_v5_active_board.py`

**Interfaces:**
- Consumes: canonical production board DataFrame and `run_interactive_production(...)` output.
- Produces: `normalize_active_board(board: pd.DataFrame, mode: str, as_of=None) -> pd.DataFrame`, `set_active_board(session_state, board, mode, as_of=None)`, `get_active_board(session_state, production_board) -> tuple[pd.DataFrame, str]`, and `clear_adjusted_board(session_state)`.

- [ ] **Step 1: Write failing tests** asserting production defaults to mode `production`, adjusted state takes precedence within a session, mode/as-of metadata are added, and clearing adjusted state restores production.
- [ ] **Step 2: Run** `python -m pytest tests/test_v5_active_board.py -v` and verify failure because `v5_active_board` does not exist.
- [ ] **Step 3: Implement** the small state module using Streamlit-compatible mapping access only; copy DataFrames before storing/returning so UI transformations cannot mutate source artifacts.
- [ ] **Step 4: Run** `python -m pytest tests/test_v5_active_board.py -v` and verify pass.
- [ ] **Step 5: Commit** `v5_active_board.py`, its tests, and only required normalization changes.

### Task 2: Restore Daily Board as a dedicated full-slate page

**Files:**
- Create: `v5_ui_daily_board.py`
- Modify: `v5_ui_app.py`
- Modify: `tennis_quant_app_v5.py` only where an existing reusable board renderer/control helper must be exposed rather than duplicated.
- Test: `tests/test_v5_ui_daily_board.py`
- Test: `tests/test_v5_production_ui_unification.py`

**Interfaces:**
- Consumes: normalized production board, market feed, ratings/context assets already loaded by the app, and active-board helpers from Task 1.
- Produces: `render_daily_board(st_module, production_board, market_feed, ...)` and navigation entry `Daily Board`.

- [ ] **Step 1: Write failing navigation/render tests** requiring `Daily Board` and `Decision Feed` to be distinct navigation destinations and requiring Daily Board to render the full board rather than cards.
- [ ] **Step 2: Run** the two focused test files and verify the new page contract fails.
- [ ] **Step 3: Implement** a dedicated Daily Board renderer using `st.data_editor`/wide table behavior, preserving the existing columns for probabilities, fair odds, EV, signals, expected margin/total, model diagnostics, context provenance, and market prices.
- [ ] **Step 4: Add editable columns** for `Surface`, `Environment`, `Court Speed`, `CPI`, `Ace Rate %`, `Rally Length`, `Relative Air Density`, `Altitude m`, `Ball Type`, plus existing `Tour`/`Best Of` controls where present. Map only through the already-defined override contract in `v5_interactive_production.py`.
- [ ] **Step 5: Add explicit source label** `Production Forecast` when no adjusted board is active and a reset control that calls `clear_adjusted_board(...)`.
- [ ] **Step 6: Run focused tests** and verify pass.
- [ ] **Step 7: Commit** the Daily Board page and navigation restoration.

### Task 3: Wire selected/full reruns into session-only adjusted state

**Files:**
- Modify: `v5_ui_daily_board.py`
- Modify: `v5_interactive_production.py` only if an existing function needs a narrow reusable interface.
- Test: `tests/test_v5_daily_board_adjusted_state.py`
- Test: `tests/test_v5_court_conditions_integration.py`

**Interfaces:**
- Consumes: edited Daily Board rows and `run_interactive_production(...)`.
- Produces: successful adjusted board stored via `set_active_board(..., mode="adjusted")`; production artifacts remain unchanged.

- [ ] **Step 1: Write failing tests** proving an edited Surface/Environment/Court Speed value reaches its existing `v5_*_override`, a successful rerun updates active state, and the original production DataFrame remains byte/value-equivalent.
- [ ] **Step 2: Add tests** for CPI, ace rate, rally length, RAD, altitude, and ball type override plumbing; if any currently stop before `_target_rows`, make those failures explicit.
- [ ] **Step 3: Run focused tests** and confirm the expected failures.
- [ ] **Step 4: Implement minimal override completion** so `_target_rows` honors explicit `external_*_override` values before source snapshot values while preserving source values when no override is supplied. Keep supporting metrics diagnostic unless already part of validated model math.
- [ ] **Step 5: Implement rerun controls** for the full slate and selected fixtures; merge selected rerun results back into the session adjusted board by fixture identity without touching canonical files.
- [ ] **Step 6: Render rerun errors inline** with fixture/stage/error and retain the last successful active board rather than replacing it with partial failure.
- [ ] **Step 7: Run focused tests** and verify pass.
- [ ] **Step 8: Commit** adjusted-state and context-control wiring.

### Task 4: Convert current Today cards into Decision Feed over active board

**Files:**
- Modify: `v5_ui_today.py`
- Modify: `v5_ui_app.py`
- Test: `tests/test_v5_ui_today.py`
- Test: `tests/test_v5_decision_feed_active_state.py`

**Interfaces:**
- Consumes: `get_active_board(...)` output only.
- Produces: `Decision Feed` cards with no model/simulation invocation.

- [ ] **Step 1: Write failing tests** proving Decision Feed uses adjusted board values when present, production values otherwise, and never calls model/simulation functions.
- [ ] **Step 2: Write ranking tests** requiring BET before LEAN before REVIEW, EV descending inside a tier, REVIEW in a secondary section, and PASS/NO PRICE excluded or collapsed from the primary feed.
- [ ] **Step 3: Run focused tests** and verify failure under the current Today-only route.
- [ ] **Step 4: Rename/reframe presentation copy** from Today to Decision Feed while retaining the existing card renderer and `prepare_today_board` as a presentation transform.
- [ ] **Step 5: Add mode badge** `Production Forecast` or `Adjusted Scenario` sourced from active-board metadata.
- [ ] **Step 6: Ensure card fields are read directly** from normalized board columns; do not recompute probability, fair odds, EV, or signal in the card layer.
- [ ] **Step 7: Run focused tests** and verify pass.
- [ ] **Step 8: Commit** Decision Feed separation.

### Task 5: Quantify the all-REVIEW confidence-gate regression

**Files:**
- Create: `diagnose_signal_confidence_gate.py`
- Create: `tests/test_signal_confidence_gate_diagnostic.py`
- Create after execution: `docs/experiments/2026-09-14-signal-confidence-gate.md`

**Interfaces:**
- Consumes: frozen historical priced predictions/recommendation artifacts available in the repository; current `signal_row` thresholds.
- Produces: deterministic comparison table for current hard gate, no hard gate, and evidence-supported graduated candidate policies where sample permits.

- [ ] **Step 1: Write failing unit tests** with synthetic rows showing that the current `<0.45` confidence gate converts an otherwise BET/LEAN row to REVIEW and that the diagnostic separately records `raw_signal_without_confidence_gate` and `official_signal`.
- [ ] **Step 2: Run** `python -m pytest tests/test_signal_confidence_gate_diagnostic.py -v` and verify failure.
- [ ] **Step 3: Implement diagnostic functions** that replay signals without modifying `v5_live_market.signal_row`, group by chronological period/confidence bucket, and calculate sample count, wins/losses where meaningful, units, ROI, drawdown, and classification counts.
- [ ] **Step 4: Add a slate-level report** counting rows downgraded solely by state confidence so the current all-REVIEW behavior is directly measurable.
- [ ] **Step 5: Run the diagnostic** against available frozen history and save exact results/methodology to the experiment markdown file.
- [ ] **Step 6: Decide promotion from evidence only:** if one candidate has adequate chronological/OOS support, document the exact rule and metrics; otherwise explicitly retain current official policy and surface raw edge/raw pre-gate signal diagnostically in Daily Board/Decision Feed.
- [ ] **Step 7: Run unit tests** and verify pass.
- [ ] **Step 8: Commit** diagnostic code and evidence artifact. Do not change production policy in this task unless Task 6's promotion gate is satisfied.

### Task 6: Promote an evidence-backed signal policy, or expose the constraint transparently

**Files:**
- Modify conditionally: `v5_live_market.py`
- Modify conditionally: `v5_daily_batch.py`
- Modify conditionally: `v5_reprice_markets.py`
- Modify: `v5_interactive_production.py`
- Modify: `v5_ui_daily_board.py`
- Modify: `v5_ui_today.py`
- Test: `tests/test_v5_signal_policy.py`

**Interfaces:**
- Consumes: Task 5 evidence artifact.
- Produces: either a promoted official signal rule with regression coverage, or unchanged official rule plus explicit raw-edge/pre-gate diagnostics.

- [ ] **Step 1: Write tests for the evidence-selected outcome.** If promoted, encode the exact approved rule and preserve BET/LEAN/PASS semantics. If not promoted, assert `signal_row` remains unchanged while UI rows include `Raw Pricing Signal`, `Official Signal`, and `Review Reason`.
- [ ] **Step 2: Run focused tests** and verify failure before implementation.
- [ ] **Step 3: Implement only the evidence-selected outcome.** Keep one canonical signal function; do not fork a separate Decision Feed policy.
- [ ] **Step 4: Run focused tests** and verify pass.
- [ ] **Step 5: Commit** the policy repair or transparent constraint surfacing with the evidence document in the commit history.

### Task 7: Close the persisted-context dependency exposed by Daily Board

**Files:**
- Modify: `.github/workflows/v5_context_warehouse.yml`
- Modify as required: context warehouse persistence/loader module identified by existing workflow imports.
- Test: existing context warehouse tests plus a new `tests/test_v5_context_warehouse_persistence_contract.py`.

**Interfaces:**
- Consumes: backend-built `context_warehouse/player_match_rows.parquet` and companion assets.
- Produces: durable canonical context artifacts available to deployed Streamlit before interactive reruns.

- [ ] **Step 1: Write a failing persistence-contract test** proving the backend refresh has a durable publish step and the app loader expects that same canonical location/source.
- [ ] **Step 2: Run the focused test** and verify it reproduces the missing-warehouse architectural gap rather than bypassing it.
- [ ] **Step 3: Implement durable publication** using the repository's established production artifact mechanism, serialized under the existing production writer lock. Preserve last-known-good artifacts on build failure and explicit freshness metadata.
- [ ] **Step 4: Correct user-facing failure copy** so it reports actual freshness/persistence state and never tells the user to perform a prohibited live rebuild.
- [ ] **Step 5: Run context tests** and verify pass.
- [ ] **Step 6: Commit** backend persistence fix separately from UI work.

### Task 8: Full regression, deployed smoke, and anti-drift verification

**Files:**
- Modify: `.github/workflows/streamlit-app-smoke.yml` only if needed to exercise both pages.
- Test: repository test suite.
- Document: `docs/experiments/2026-09-14-daily-board-decision-feed-verification.md`

**Interfaces:**
- Consumes: completed Tasks 1–7.
- Produces: end-to-end verification evidence suitable for merge/completion decision.

- [ ] **Step 1: Extend Streamlit smoke** to assert both `Daily Board` and `Decision Feed` routes render and that Decision Feed can consume a supplied adjusted active board without recalculation.
- [ ] **Step 2: Run focused UI/context/signal tests** and record exact pass/fail counts.
- [ ] **Step 3: Run the full repository regression suite** and fix root causes of any failures rather than weakening unrelated assertions.
- [ ] **Step 4: Run Streamlit smoke** against the feature branch and require green status.
- [ ] **Step 5: Verify production immutability** by comparing canonical forecast/recommendation artifacts before and after an adjusted scenario test.
- [ ] **Step 6: Verify backend context availability** through the same path the deployed app uses.
- [ ] **Step 7: Write verification evidence** including commit SHA, tests, UI routes, active-state behavior, signal-policy outcome, context persistence, and any external dependency that truly prevents live proof.
- [ ] **Step 8: Perform anti-drift check:** confirm low manual intervention preserved/improved, one source of truth preserved, statistical validity preserved/improved, and sellable-MVP usability improved.
- [ ] **Step 9: Commit** verification/workflow changes, open PR, require green checks, merge only after verification, then verify the merged `main` deployment state.
