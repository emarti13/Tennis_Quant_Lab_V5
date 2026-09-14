# Official Top Play and Results Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make one primary market per fixture the only official recommendation, make Results & Accuracy grade one frozen forecast per settled fixture, and make Performance grade only official recommendations.

**Architecture:** Reuse one deterministic fixture-level primary-market selector for both the Decision Feed and recommendation pipeline. Keep the full repriced market table for audit/display, but filter to one selected actionable row per fixture before ledger mutation. Add a fixture-level accuracy projection over the existing frozen settlement ledger and switch Results & Accuracy headline metrics to that projection while leaving market-level audit views available.

**Tech Stack:** Python, pandas, pytest, Streamlit, GitHub Actions

**Spec:** `docs/superpowers/specs/2026-09-14-official-top-play-results-contract-design.md`

## Global Constraints

- At most one official recommendation per fixture.
- Raw market `BET`/`LEAN` signals remain available as pricing-candidate evidence and do not independently become official recommendations.
- A frozen official `BET` is immutable; a `LEAN` may be superseded before match start by the fixture's later primary `BET`.
- No official recommendation may be created or changed at or after match start.
- Results & Accuracy uses one settled fixture record and grades winner probability, margin, and total when fields are available.
- Performance uses only the settled official recommendation ledger.
- Existing settled historical rows are never rewritten by duplicate-normalization logic.

---

### Task 1: Shared fixture primary-market selection and official-ledger uniqueness

**Files:**
- Create: `v5_recommendation_policy.py`
- Modify: `v5_recommendation_ledger.py`
- Modify: `v5_reprice_markets.py`
- Test: `tests/test_v5_recommendation_policy.py`
- Test: `tests/test_v5_recommendation_ledger.py`

**Interfaces:**
- Produces: `select_primary_market_rows(observations: pd.DataFrame) -> pd.DataFrame`, returning at most one deterministic source row per fixture.
- Consumes: long-form repriced rows with `fixture_id`, `signal`, `expected_value`, `market_group`, `selection`, `line`, and `market_key`.
- `update_repricing_artifacts(...)` passes only selected fixture-primary rows into `update_official_recommendations(...)` while returning the full repriced table unchanged.

- [ ] **Step 1: Write failing selector tests**

```python
import pandas as pd
from v5_recommendation_policy import select_primary_market_rows


def test_primary_policy_returns_highest_ev_bet_once_per_fixture():
    rows = pd.DataFrame([
        {"fixture_id": "fx1", "market_key": "fx1|ml|a|", "signal": "BET", "expected_value": .20},
        {"fixture_id": "fx1", "market_key": "fx1|spread|b|3.5", "signal": "BET", "expected_value": .45},
        {"fixture_id": "fx1", "market_key": "fx1|total|over|22.5", "signal": "LEAN", "expected_value": .60},
        {"fixture_id": "fx2", "market_key": "fx2|ml|c|", "signal": "LEAN", "expected_value": .11},
    ])
    chosen = select_primary_market_rows(rows)
    assert list(chosen["market_key"]) == ["fx1|spread|b|3.5", "fx2|ml|c|"]
```

Also add a stable tie-break test using source row order.

- [ ] **Step 2: Run the selector tests and verify RED**

Run: `pytest tests/test_v5_recommendation_policy.py -q`
Expected: FAIL because `v5_recommendation_policy` / `select_primary_market_rows` does not exist.

- [ ] **Step 3: Implement the minimal selector**

Implement signal priority `BET=0`, `LEAN=1`, `REVIEW=2`, `PASS=3`, everything else later. Sort inside each fixture by signal priority ascending, expected value descending, then original source order ascending; return one row per fixture. Keep all signal tiers so the same helper can describe the card's primary row, but ledger callers filter selected rows to `BET`/`LEAN`.

- [ ] **Step 4: Run selector tests and verify GREEN**

Run: `pytest tests/test_v5_recommendation_policy.py -q`
Expected: PASS.

- [ ] **Step 5: Write failing official-ledger fixture-uniqueness tests**

Add tests proving:

```python
def test_two_bet_candidates_same_fixture_create_only_selected_official_row():
    observations = pd.concat([
        _obs("BET", 110, "2026-09-08T12:00:00Z", prob=.58).assign(expected_value=.10),
        _obs("BET", 154, "2026-09-08T12:00:00Z", prob=.74).assign(
            market_group="game_spread", selection="Player Two", line=3.5,
            market_key="fx1|game_spread|player two|3.5", expected_value=.40,
        ),
    ], ignore_index=True)
    selected = select_primary_market_rows(observations)
    ledger, _ = update_official_recommendations(pd.DataFrame(), selected)
    assert len(ledger) == 1
    assert ledger.iloc[0]["market_key"] == "fx1|game_spread|player two|3.5"
```

Add a second test where a later primary BET on a different market cannot create a second official row for the same fixture, and a third test where an existing OPEN duplicate fixture is normalized to one strongest row.

- [ ] **Step 6: Run ledger tests and verify RED**

Run: `pytest tests/test_v5_recommendation_ledger.py tests/test_v5_recommendation_policy.py -q`
Expected: new fixture-uniqueness tests FAIL under current market-key uniqueness behavior.

- [ ] **Step 7: Implement fixture-level ledger uniqueness and repricing handoff**

Change `update_official_recommendations` to use fixture identity as the official decision uniqueness boundary. Normalize only OPEN duplicate rows per fixture by signal priority and frozen EV; preserve every settled row untouched. Permit OPEN `LEAN` -> `BET` replacement at fixture level even when market key changes. Keep BET immutable. In `update_repricing_artifacts`, compute `selected = select_primary_market_rows(repriced)` and pass only actionable selected rows into the ledger updater.

- [ ] **Step 8: Run affected tests and verify GREEN**

Run: `pytest tests/test_v5_recommendation_policy.py tests/test_v5_recommendation_ledger.py tests/test_v5_official_recommendation_settlement.py -q`
Expected: PASS.

- [ ] **Step 9: Commit Task 1**

Commit message: `fix: freeze one official top play per fixture`

---

### Task 2: Decision Feed copy makes official play versus candidates explicit

**Files:**
- Modify: `v5_ui_today.py`
- Test: `tests/test_v5_ui_today.py`

**Interfaces:**
- Consumes: existing `Primary Market`, `Best Signal`, and per-market raw signal fields.
- Produces: card copy that identifies the header as `Official top play` when actionable and identifies the lower section as `Current pricing candidates — not separately logged`.

- [ ] **Step 1: Write failing UI copy tests**

Add assertions against `match_card_html(...)` that an actionable card contains `Official top play` and `Current pricing candidates`, while the lower raw market signals remain visible.

- [ ] **Step 2: Run UI tests and verify RED**

Run: `pytest tests/test_v5_ui_today.py -q`
Expected: FAIL because those labels do not exist.

- [ ] **Step 3: Implement minimal copy changes**

Keep signal badges unchanged. Add the official/top-play label next to or immediately above the primary selection. Rename the lower output heading/copy so the user can see that those rows are candidate signals and are not independently written to Performance.

- [ ] **Step 4: Run UI tests and verify GREEN**

Run: `pytest tests/test_v5_ui_today.py -q`
Expected: PASS.

- [ ] **Step 5: Commit Task 2**

Commit message: `ui: distinguish official play from pricing candidates`

---

### Task 3: Fixture-level Results & Accuracy projection

**Files:**
- Create: `v5_fixture_accuracy.py`
- Modify: `results_accuracy_page.py`
- Test: `tests/test_v5_fixture_accuracy.py`
- Modify: `tests/test_results_accuracy.py`

**Interfaces:**
- Produces: `fixture_accuracy_records(frozen: pd.DataFrame) -> pd.DataFrame` with one row per settled fixture.
- Required output fields when source data permits: `fixture_id`, `player1`, `player2`, `p1_probability`, `predicted_winner`, `actual_winner`, `winner_correct`, `brier_score`, `expected_margin`, `actual_margin`, `margin_error`, `abs_margin_error`, `expected_total`, `actual_total`, `total_error`, `abs_total_error`, `result_score`.
- Results & Accuracy headline consumes that fixture frame rather than actionable market rows.

- [ ] **Step 1: Write failing fixture-accuracy tests**

Create a synthetic settled frozen ledger with several market rows for one fixture but one shared forecast/result. Assert `fixture_accuracy_records` returns one row and, for `p1_probability=.575`, expected margin `.54`, expected total `22.5`, and a P1 6-4 7-5 win (`winner_games=13`, `loser_games=9`):

```python
assert row["winner_correct"] is True
assert row["brier_score"] == pytest.approx((.575 - 1.0) ** 2)
assert row["actual_margin"] == pytest.approx(4.0)
assert row["margin_error"] == pytest.approx(3.46)
assert row["actual_total"] == pytest.approx(22.0)
assert row["total_error"] == pytest.approx(-.5)
```

Also test a P2 win so actual margin is negative from P1 perspective.

- [ ] **Step 2: Run fixture-accuracy tests and verify RED**

Run: `pytest tests/test_v5_fixture_accuracy.py -q`
Expected: FAIL because the module/function does not exist.

- [ ] **Step 3: Implement fixture projection**

Collapse settled frozen rows by `fixture_id`. Resolve forecast fields from `full_context_probability_p1` first, with explicit compatible fallbacks only when a match-level field already exists in the frozen row. Resolve player identities from `resolved_player1`/`resolved_player2` then provider names. Compute actual game margin from P1 perspective using winner identity plus `winner_games`/`loser_games`. Do not synthesize missing values.

- [ ] **Step 4: Run fixture-accuracy tests and verify GREEN**

Run: `pytest tests/test_v5_fixture_accuracy.py -q`
Expected: PASS.

- [ ] **Step 5: Write failing Results page scope tests**

Add tests that headline calculations operate on fixture records and therefore count one settled fixture even when the frozen ledger contains many settled market rows. Assert winner accuracy and mean Brier/margin/total absolute error.

- [ ] **Step 6: Run Results page tests and verify RED**

Run: `pytest tests/test_results_accuracy.py tests/test_results_scope_and_html_rendering.py -q`
Expected: FAIL because current headline logic is market/actionable scoped.

- [ ] **Step 7: Switch Results & Accuracy headline to fixture metrics**

Add a fixture metric helper in `results_accuracy_page.py` and render headline metrics: settled fixtures, winner accuracy, Brier score, margin MAE, total MAE. Add a fixture calibration table using `p1_probability` and actual P1 win outcome. Keep existing market-level settled ledger tables under an explicit audit expander rather than deleting them.

- [ ] **Step 8: Run Results tests and verify GREEN**

Run: `pytest tests/test_v5_fixture_accuracy.py tests/test_results_accuracy.py tests/test_results_scope_and_html_rendering.py -q`
Expected: PASS.

- [ ] **Step 9: Commit Task 3**

Commit message: `feat: grade frozen forecasts once per fixture`

---

### Task 4: Performance contract guard and end-to-end regression

**Files:**
- Modify: `v5_official_performance.py`
- Modify: `v5_ui_performance.py`
- Test: `tests/test_v5_official_recommendation_settlement.py`
- Test: `tests/test_v5_ui_performance.py`
- Test: `tests/test_v5_settlement_pipeline.py`

**Interfaces:**
- Performance continues consuming only `official_recommendations.csv` / `official_performance.json`.
- New-production invariant: one official recommendation per fixture, therefore `max_recommendations_per_fixture <= 1` once historical duplicate rows are absent.

- [ ] **Step 1: Write failing Performance invariant tests**

Add a report test showing a clean official ledger with one recommendation per fixture reports `max_recommendations_per_fixture == 1`. Add UI copy assertion stating that supporting pricing candidates are excluded from Performance.

- [ ] **Step 2: Run Performance tests and verify RED where copy/invariant handling is missing**

Run: `pytest tests/test_v5_official_recommendation_settlement.py tests/test_v5_ui_performance.py tests/test_v5_settlement_pipeline.py -q`
Expected: at least the new copy/invariant assertion fails before implementation.

- [ ] **Step 3: Implement minimal Performance guard/copy**

Keep the official ledger as source of truth. Update subtitle/caption to state: one official top play per fixture is counted; supporting candidate signals are excluded. Do not reintroduce candidate-market statistics into headline ROI.

- [ ] **Step 4: Run Performance tests and verify GREEN**

Run: `pytest tests/test_v5_official_recommendation_settlement.py tests/test_v5_ui_performance.py tests/test_v5_settlement_pipeline.py -q`
Expected: PASS.

- [ ] **Step 5: Run complete regression suite**

Run: `pytest -q`
Expected: PASS with zero failures.

- [ ] **Step 6: Commit Task 4**

Commit message: `test: enforce official top play production contract`

---

### Task 5: Production artifact normalization and release verification

**Files:**
- Modify only generated canonical artifacts produced by the normal pipeline if the workflow runs them: `v5_daily_ready/official_recommendations.csv`, `v5_daily_ready/official_performance.json`, status/audit artifacts as applicable.

**Interfaces:**
- Normal repricing must collapse today's open duplicate official recommendations to one row per fixture using the new contract.
- Settlement must continue to grade only those official rows.

- [ ] **Step 1: Open a PR from `fix/official-top-play-contract` to `main`**

Ensure full regression and Streamlit smoke workflows run on the PR.

- [ ] **Step 2: Verify CI is green**

Required checks: complete pytest suite and Streamlit smoke test. Investigate any failing check rather than merging around it.

- [ ] **Step 3: Merge after green CI**

Use a normal merge/squash consistent with repository history.

- [ ] **Step 4: Verify main production behavior**

Confirm the next repricing run produces at most one OPEN official recommendation per fixture, the Decision Feed copy is explicit, Results & Accuracy shows fixture-level metrics after settlement, and Performance counts only official rows.

- [ ] **Step 5: Record any remaining blocker**

If canonical results settlement has not yet occurred for the day's matches, treat empty Results/Performance values as pending evidence rather than a code failure; verify the structures and workflow are ready to populate automatically.
