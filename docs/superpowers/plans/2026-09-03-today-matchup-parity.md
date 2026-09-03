# Today Matchup-Lab Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the requested Slate Setup / Advanced controls and enrich each Today card with compact Matchup Lab-equivalent projection output while leaving every other page unchanged.

**Architecture:** Extend the existing daily simulation result row so it carries the same player-state diagnostics used by Matchup Lab, then render those fields inside `v5_ui_today.py`. Keep the daily simulation/model path unchanged and reuse its outputs. Move the slate preview/editor/diagnostics into the existing collapsed advanced section in `tennis_quant_app_v5.py`.

**Tech Stack:** Python 3.12, Streamlit, pandas, pytest.

**Spec:** `docs/superpowers/specs/2026-09-03-today-matchup-parity-design.md`

## Global Constraints
- Only Today and Slate Setup / Advanced may change.
- Match Detail, All Markets, Performance, Model Health, and Matchup Lab remain unchanged.
- No model probability, fair-odds, EV, threshold, signal, simulation, or pricing logic changes.
- Giant tables remain hidden by default.
- Today reuses the daily simulation output; no duplicate model path.

---

### Task 1: Daily result parity fields

**Files:**
- Modify: `tennis_quant_app_v5.py`
- Test: `tests/test_v5_today_matchup_parity.py`

**Interfaces:**
- Consumes: `_batch_one_match(row, ratings_by_tour, summary, sims)`.
- Produces: existing daily result row plus `P1/P2 Form`, `P1/P2 Form Percentile`, `P1/P2 Volatility`, `P1/P2 Volatility Percentile`, `P1/P2 Volatility Label`, `P1/P2 State Conf Label`, and `Surface Elo P1 %`.

- [ ] Write a failing test asserting the parity fields are present without changing existing probability/fair/margin/total fields.
- [ ] Run the focused test and confirm RED.
- [ ] Add the fields from the already-loaded `a`, `b`, and `p_elo` values in `_batch_one_match`; do not recompute the model.
- [ ] Run focused tests and confirm GREEN.

### Task 2: Compact Matchup Lab-style Today card

**Files:**
- Modify: `v5_ui_today.py`
- Test: `tests/test_v5_today_matchup_parity.py`

**Interfaces:**
- Consumes: enriched daily result row.
- Produces: `match_card_html(row)` containing projection, player state, agreement, and actionable market output.

- [ ] Add failing tests asserting card HTML includes win probability/fair odds, expected margin/total, form, volatility, state confidence, agreement/model gap, and market signal/EV data.
- [ ] Run tests and confirm RED.
- [ ] Extend the existing card HTML with compact grouped sections while preserving existing ranking and signal semantics.
- [ ] Run tests and confirm GREEN.

### Task 3: Restore requested Slate Setup / Advanced capability

**Files:**
- Modify: `tennis_quant_app_v5.py`
- Test: `tests/test_v5_today_matchup_parity.py`

**Interfaces:**
- Consumes: `_oddspapi_daily_slate()`, ratings lookups, existing precision mapping.
- Produces: one collapsed `Slate Setup / Advanced` section with simulation precision, editable Tour/Surface/Best Of, surface-source warnings, unmatched-player diagnostics, current market slate preview, and run action.

- [ ] Add host-contract tests for advanced section labels and retained controls.
- [ ] Run tests and confirm RED.
- [ ] Reorganize the existing Today host flow so the requested controls/preview live inside the collapsed advanced expander; preserve simulation behavior and session-state result storage.
- [ ] Run focused tests and confirm GREEN.

### Task 4: Full verification and integration

**Files:**
- Test: `tests/`

- [ ] Run `python -m pytest tests -q` and require zero failures.
- [ ] Run the existing Streamlit smoke workflow / AppTest and require Today-first navigation with no uncaught exception.
- [ ] Verify existing model-output invariance tests remain green.
- [ ] Review diff to confirm no secondary-page code changed.
- [ ] Open PR and merge only after the branch is green; rerun full regression and Streamlit smoke on merged `main`.