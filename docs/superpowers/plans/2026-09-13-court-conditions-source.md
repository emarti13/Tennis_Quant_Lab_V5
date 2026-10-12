> **Superseded (2026-10-12).** Court-condition / CourtSpeed work is retired; its code was removed in
> the Step 1 repo cleanup. Surface and court information come from the master tennis schedule
> (see `docs/superpowers/plans/2026-10-12-ground-up-rebuild-plan.md`, Step 2). Kept for history only.

# Court Conditions Source Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a source-agnostic court-conditions layer backed initially by a persisted CourtSpeed-derived snapshot, then expose those conditions to V5 simulation/context without creating a second model path or contaminating the accepted court-speed scale.

**Architecture:** Store external tournament-year conditions in a versioned CSV snapshot, load them through a dedicated adapter that normalizes aliases and performs metric-by-metric nearest-prior fallback, then attach the resulting canonical fields/provenance to the existing effective context fixture. Raw CPI/ace/rally/RAD/ball data remain distinct from the accepted `court_speed_blended` state; accepted existing model features keep driving official probabilities until new coefficients earn promotion through walk-forward validation.

**Tech Stack:** Python 3.12, pandas, existing V5 context/court-speed modules, Streamlit, pytest.

**Spec:** `docs/superpowers/specs/2026-09-13-court-conditions-source-amendment.md`

## Global Constraints

- No network scraping from Streamlit or normal model execution.
- Surface remains Hard / Clay / Grass; environment remains a separate Indoor / Outdoor / Unknown dimension.
- Never copy raw CPI into `court_speed_blended`.
- Fallback may only use the exact year or an earlier year; never a future year.
- Fallback and provenance are metric-specific.
- Unknown tournaments stay on the current V5 fallback path.
- Do not alter frozen historical predictions or recommendation thresholds.
- New CPI/ace/rally/ball coefficients are not promoted into official production without chronological OOS validation.

---

### Task 1: Canonical external-condition adapter

**Files:**
- Create: `v5_court_conditions_source.py`
- Create: `tests/test_v5_court_conditions_source.py`

**Interfaces:**
- `normalize_event_name(name: str) -> str`
- `load_condition_snapshot(path: str | Path | None = None) -> pd.DataFrame`
- `lookup_court_conditions(tournament: str, year: int, snapshot: pd.DataFrame | None = None) -> dict`
- Output includes canonical values plus `<metric>_source_year` provenance.

- [ ] Write tests proving alias normalization, exact-year lookup, nearest-prior fallback, no future-year fallback, Indoor independent of Hard, missing-event safety, and raw CPI remaining separate from internal court-speed fields.
- [ ] Run focused test and verify RED because module does not exist.
- [ ] Implement the minimal loader, alias normalization, metric-specific fallback, and provenance contract.
- [ ] Run focused test and verify GREEN.

### Task 2: Persist current CourtSpeed-derived snapshot

**Files:**
- Create: `data/court_conditions/courtspeed_snapshot.csv`
- Test: `tests/test_v5_court_conditions_source.py`

**Interfaces:**
- CSV columns: `event_key,event_name,year,surface_type,environment,cpi,ace_rate_pct,rally_length,relative_air_density,altitude_m,ball_type,overall_speed_rating,source_name,source_updated_at`.

- [ ] Add fixture assertions for Paris and ATP Finals indoor hard records plus representative outdoor events.
- [ ] Add current/prior-year values from the source pages, preserving blanks as missing rather than guessing.
- [ ] Verify the loader reads the repository snapshot and fallback selects prior-year values when current-year measurements are not yet available.

### Task 3: Attach external conditions to existing effective context

**Files:**
- Modify: `v5_daily_batch.py`
- Modify: `v5_interactive_production.py`
- Create/modify: `tests/test_v5_court_conditions_integration.py`

**Interfaces:**
- Existing `_context_fixture(prepared)` gains external condition fields without changing sportsbook-independent model identity.
- Interactive overrides propagate through existing fixture rows using provider-agnostic canonical names.

- [ ] Write tests proving condition lookup attaches Surface/Environment/CPI/Ace/Rally/RAD/Altitude/Ball/provenance to the context fixture and does not overwrite `court_speed_blended`.
- [ ] Verify RED.
- [ ] Add lookup at fixture preparation/effective-context construction and preserve existing fallback behavior for unknown events.
- [ ] Add interactive row mapping for Environment and source diagnostics; keep accepted model math unchanged for raw CPI/ace/rally/ball fields.
- [ ] Verify focused integration tests GREEN.

### Task 4: Expose editable simulation condition fields

**Files:**
- Modify: `tennis_quant_app_v5.py` and/or the current daily-run advanced editor host used by production.
- Modify: relevant UI contract tests.

**Interfaces:**
- Advanced editor exposes Surface Type, Environment, Court Speed, CPI, Ace Rate %, Rally Length, RAD/Altitude, Ball Type.
- Inferred values remain visible; overrides apply only to the interactive simulation request and do not mutate the persisted snapshot.

- [ ] Write UI contract tests for all condition controls and override provenance.
- [ ] Verify RED.
- [ ] Add controls using existing editor/override patterns; no model calculations live in Streamlit.
- [ ] Verify focused UI tests GREEN.

### Task 5: Verification and merge readiness

**Files:**
- No new feature scope.

- [ ] Run the new source-adapter and integration/UI tests.
- [ ] Run the existing court-speed/context tests to prove no scale/leakage regression.
- [ ] Inspect diff for accidental network calls, CPI-to-`court_speed_blended` assignment, second prediction path, or future-year fallback.
- [ ] Run one repository CI verification on the finished branch; do not create debugging-only production/API runs.
- [ ] Merge only after verification evidence is green; otherwise report the exact blocker and leave `main` unchanged.