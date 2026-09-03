# Apple-style Today UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current dataframe-first Daily Board experience with a polished Today-first Streamlit interface that is simple to scan, preserves full analytical depth, and does not change any production model or market-selection logic.

**Architecture:** Keep `tennis_quant_app_v5.py` as the host/orchestrator and reuse its existing market/model loaders. Extract presentation and UI-only transformation logic into focused modules: theme, Today cards, Match Detail, Performance, and Model Health. The UI consumes frozen/current V5 outputs; it must never recompute or override winner probabilities, score candidates, signals, fair odds, thresholds, or policy decisions.

**Tech Stack:** Python 3.12, Streamlit, pandas, existing V5 production artifacts and loaders, pytest/unittest repository regression suite.

**Spec:** `docs/superpowers/specs/2026-09-02-apple-today-ui-design.md`

## Global Constraints

- The model architecture, market logic, probability generation, production candidate selection, and frozen prediction workflow are out of scope.
- Today is the default landing experience.
- Full analytical depth must remain available within one interaction from a match card.
- Dense raw tables move to analyst/deep-detail contexts rather than being removed.
- Performance must distinguish raw market results from unique fixture-level evidence.
- No sportsbook information may be introduced upstream of frozen model outputs.
- No proprietary font files; use a native system-font stack.
- Primary Today layout must remain usable at mobile width without a horizontally scrolling decision table.
- Existing full regression and Streamlit smoke tests must remain green.

## File Structure

- Create `v5_ui_theme.py` — design tokens, CSS, reusable surface/pill/metric helpers.
- Create `v5_ui_today.py` — Today board preparation, ranking, summary strip, match-card rendering, empty/stale states.
- Create `v5_ui_match_detail.py` — fixture-level overview, context, market families, model detail, raw audit expander.
- Create `v5_ui_performance.py` — presentation for raw and fixture-clustered settled-performance audit artifacts.
- Create `v5_ui_health.py` — production-candidate, regression, smoke, freshness, and warning presentation.
- Modify `tennis_quant_app_v5.py` — navigation/orchestration only; reuse existing loaders and batch execution logic.
- Create `tests/test_v5_ui_today.py` — Today transformation/ranking/card contract tests.
- Create `tests/test_v5_ui_navigation.py` — navigation/page registry contract tests.
- Create `tests/test_v5_ui_performance.py` — raw-vs-fixture reporting contract tests.
- Modify Streamlit smoke coverage only where navigation expectations must change from `Daily Board` to `Today`.

---

### Task 1: Design system and shared presentation primitives

**Files:**
- Create: `v5_ui_theme.py`
- Test: `tests/test_v5_ui_today.py`

**Interfaces:**
- Produces: `apply_v5_theme(st_module) -> None`
- Produces: `signal_class(signal: str) -> str`
- Produces: `format_probability(value) -> str`
- Produces: `format_american_odds(value) -> str`
- Produces: `format_edge(value) -> str`

- [ ] **Step 1: Write failing formatting tests**

```python
from v5_ui_theme import format_probability, format_american_odds, format_edge, signal_class


def test_ui_number_formatting_and_signal_classes():
    assert format_probability(0.673) == "67.3%"
    assert format_american_odds(-203) == "-203"
    assert format_american_odds(145) == "+145"
    assert format_edge(0.0841) == "+8.4%"
    assert signal_class("BET") == "signal-bet"
    assert signal_class("PASS") == "signal-pass"
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `pytest tests/test_v5_ui_today.py::test_ui_number_formatting_and_signal_classes -v`
Expected: FAIL because `v5_ui_theme` does not exist.

- [ ] **Step 3: Implement the theme module**

Implement a native font stack (`-apple-system`, `BlinkMacSystemFont`, `Segoe UI`, `Roboto`, sans-serif), neutral background, rounded cards, restrained border/shadow, accessible signal pills, responsive breakpoints, and the formatting helpers above. CSS must be injected only by `apply_v5_theme()`.

- [ ] **Step 4: Run the focused test and verify GREEN**

Run: `pytest tests/test_v5_ui_today.py::test_ui_number_formatting_and_signal_classes -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add v5_ui_theme.py tests/test_v5_ui_today.py
git commit -m "feat: add V5 Apple-style UI theme"
```

### Task 2: Today board transformation and actionability ranking

**Files:**
- Create: `v5_ui_today.py`
- Modify: `tests/test_v5_ui_today.py`

**Interfaces:**
- Consumes: existing board dataframe produced by `daily_board()` / frozen daily workflow.
- Produces: `prepare_today_board(board: pd.DataFrame) -> pd.DataFrame`
- Produces: `today_summary(board: pd.DataFrame, market_feed: pd.DataFrame, snapshot: str | None) -> dict`
- Produces: `primary_market_for_row(row: pd.Series) -> dict`
- Produces: `why_it_stands_out(row: pd.Series) -> str`

- [ ] **Step 1: Write failing ranking and preservation tests**

```python
def test_prepare_today_board_preserves_source_values_and_ranks_signal_first():
    import pandas as pd
    from v5_ui_today import prepare_today_board

    source = pd.DataFrame([
        {"Fixture ID":"a", "Player 1":"A", "Player 2":"B", "P1 V5 %":0.61, "P1 Fair":-156,
         "P1 ML EV":0.05, "P1 ML Signal":"LEAN", "Expected Margin":2.1, "Expected Total":22.4},
        {"Fixture ID":"b", "Player 1":"C", "Player 2":"D", "P1 V5 %":0.58, "P1 Fair":-138,
         "P1 ML EV":0.03, "P1 ML Signal":"BET", "Expected Margin":1.3, "Expected Total":21.8},
    ])
    out = prepare_today_board(source)
    assert out.iloc[0]["Fixture ID"] == "b"
    assert out.loc[out["Fixture ID"] == "a", "P1 V5 %"].iloc[0] == 0.61
    assert out.loc[out["Fixture ID"] == "a", "P1 Fair"].iloc[0] == -156
```

- [ ] **Step 2: Run focused tests and verify RED**

Run: `pytest tests/test_v5_ui_today.py -v`
Expected: FAIL because Today transformations are not implemented.

- [ ] **Step 3: Implement deterministic primary-market selection**

Use existing signal fields only: `BET`, `LEAN`, `REVIEW`, `PASS`, `NO PRICE`. Candidate families are P1/P2 ML, P1/P2 spread, Over, Under. Select the best signal tier first; inside a tier select the largest existing EV. Do not invent a signal or threshold.

- [ ] **Step 4: Implement concise deterministic explanation generation**

Build explanations only from existing row fields such as `Agreement`, `Model Gap`, `Expected Margin`, `Expected Total`, score/context metadata when present. Unsupported fields are omitted rather than narrated. No external/LLM-generated tennis prose.

- [ ] **Step 5: Run Today tests and verify GREEN**

Run: `pytest tests/test_v5_ui_today.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add v5_ui_today.py tests/test_v5_ui_today.py
git commit -m "feat: add Today board preparation and ranking"
```

### Task 3: Today page rendering and mobile-safe match cards

**Files:**
- Modify: `v5_ui_today.py`
- Modify: `tennis_quant_app_v5.py`
- Modify: `tests/test_v5_ui_today.py`

**Interfaces:**
- Produces: `render_today_page(st_module, board, market_feed, all_prices, snapshot, on_run_board) -> None`
- Produces: `render_match_card(st_module, row: pd.Series) -> None`

- [ ] **Step 1: Add tests for populated and empty Today states**

Use a minimal fake Streamlit recorder to assert the renderer emits an intentional empty-state message when no rows are qualified and emits player names / primary market text for a populated board.

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest tests/test_v5_ui_today.py -v`
Expected: FAIL on missing render functions.

- [ ] **Step 3: Implement Today header and summary strip**

Render product name, slate date, analyzed match count, refresh timestamp, Best Edge, Qualified Plays, Model Health, and Markets Live. Stale/unknown timestamps must be explicit rather than silently treated as fresh.

- [ ] **Step 4: Implement responsive match cards**

Default viewport shows BET and LEAN first, REVIEW next, and collapses PASS/other matches. Each card must expose player names, tournament/start/tour/Bo format, primary market, signal, model probability, fair odds, market price when present, edge, deterministic explanation, and a `View analysis` affordance.

- [ ] **Step 5: Replace dataframe-first Daily Board result presentation with Today rendering**

Keep existing batch-run/load logic intact. Move raw slate coverage/editor controls into a compact `Slate setup / advanced` expander. After board availability, route presentation through `render_today_page()`.

- [ ] **Step 6: Run Today tests plus daily-board regressions**

Run: `pytest tests/test_v5_ui_today.py tests/test_v5_daily_batch.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add v5_ui_today.py tennis_quant_app_v5.py tests/test_v5_ui_today.py
git commit -m "feat: make Today the primary V5 slate experience"
```

### Task 4: Match Detail progressive disclosure

**Files:**
- Create: `v5_ui_match_detail.py`
- Modify: `tennis_quant_app_v5.py`
- Modify: `tests/test_v5_ui_navigation.py`

**Interfaces:**
- Produces: `render_match_detail(st_module, row: pd.Series, all_prices: pd.DataFrame, context: dict | None = None) -> None`

- [ ] **Step 1: Write navigation/detail contract tests**

Assert the page registry exposes `Today`, `Match Detail`, `All Markets`, `Performance`, and `Model Health`, and that Match Detail can be given one existing board row without modifying its numeric values.

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest tests/test_v5_ui_navigation.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement grouped Match Detail sections**

Sections: Overview, Matchup Context, Market Board, Model Detail, Raw/Audit Data. Alternate spread/total lines are grouped by family. Missing optional context renders `Unavailable` rather than fabricated values.

- [ ] **Step 4: Integrate card selection through Streamlit session state**

A Today card sets selected fixture id and switches the current page to Match Detail; Match Detail resolves the row from the existing board/session data.

- [ ] **Step 5: Run navigation tests and verify GREEN**

Run: `pytest tests/test_v5_ui_navigation.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add v5_ui_match_detail.py tennis_quant_app_v5.py tests/test_v5_ui_navigation.py
git commit -m "feat: add progressive match detail experience"
```

### Task 5: All Markets analyst view

**Files:**
- Modify: `tennis_quant_app_v5.py`
- Modify: `tests/test_v5_ui_navigation.py`

**Interfaces:**
- Produces host-level `render_all_markets_page()` using existing market feed / all-book price loaders.

- [ ] **Step 1: Add analyst-view filter contract test**

Verify the analyst page can preserve all source rows while restricting by tour, tournament, market family, signal, and Bo3/Bo5 without recalculating EV or signals.

- [ ] **Step 2: Implement compact default columns and advanced-column toggle**

Default columns focus on fixture, market, signal, probability/fair price, market price, EV, and start time. Existing dense/raw fields remain available behind `Show advanced columns`.

- [ ] **Step 3: Run navigation/analyst tests**

Run: `pytest tests/test_v5_ui_navigation.py -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tennis_quant_app_v5.py tests/test_v5_ui_navigation.py
git commit -m "feat: add All Markets analyst view"
```

### Task 6: Honest Performance page

**Files:**
- Create: `v5_ui_performance.py`
- Create: `tests/test_v5_ui_performance.py`
- Modify: `tennis_quant_app_v5.py`

**Interfaces:**
- Consumes: settled-performance integrity audit JSON/CSV produced by the existing audit pipeline.
- Produces: `load_performance_report(base_dir: Path) -> dict`
- Produces: `render_performance_page(st_module, report: dict) -> None`

- [ ] **Step 1: Write raw-vs-fixture contract test**

```python
def test_performance_headline_keeps_raw_and_fixture_results_separate():
    from v5_ui_performance import headline_metrics
    report = {
        "raw_market": {"wins":3,"losses":2,"pushes":0,"win_rate":0.60},
        "fixture_clustered": {"profitable_fixtures":1,"losing_fixtures":2,"fixtures":3,"profitable_rate":1/3},
    }
    out = headline_metrics(report)
    assert out["market_win_rate"] == 0.60
    assert out["fixture_profitable_rate"] == 1/3
    assert out["market_results_label"] != out["fixture_results_label"]
```

- [ ] **Step 2: Run test and verify RED**

Run: `pytest tests/test_v5_ui_performance.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement report loading and presentation**

Show raw market W-L-P/ROI and unique fixture-level evidence side-by-side, then ML/spread/total, tour, Bo format, probability bucket, signal, favorite/underdog where supported, maximum correlated markets, Brier/log loss where applicable.

- [ ] **Step 4: Run performance tests and verify GREEN**

Run: `pytest tests/test_v5_ui_performance.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add v5_ui_performance.py tennis_quant_app_v5.py tests/test_v5_ui_performance.py
git commit -m "feat: add honest settled performance page"
```

### Task 7: Model Health page

**Files:**
- Create: `v5_ui_health.py`
- Modify: `tennis_quant_app_v5.py`
- Modify: `tests/test_v5_ui_navigation.py`

**Interfaces:**
- Produces: `load_model_health(base_dir: Path) -> dict`
- Produces: `render_model_health_page(st_module, health: dict) -> None`

- [ ] **Step 1: Add health loader tests with missing optional artifacts**

Verify missing score/diagnostic artifacts produce explicit `unknown`/`unavailable` states rather than exceptions.

- [ ] **Step 2: Implement artifact-backed health state**

Read production winner candidates, production score candidates, validation status, full regression status, Streamlit smoke status, market freshness, context freshness, and unresolved warnings. Do not infer green status when evidence is absent.

- [ ] **Step 3: Render compact health cards with diagnostic expanders**

Keep JSON/detail content behind expanders; primary view should communicate current production selections and freshness quickly.

- [ ] **Step 4: Run health/navigation tests**

Run: `pytest tests/test_v5_ui_navigation.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add v5_ui_health.py tennis_quant_app_v5.py tests/test_v5_ui_navigation.py
git commit -m "feat: add V5 model health page"
```

### Task 8: Navigation, smoke coverage, and production verification

**Files:**
- Modify: `tennis_quant_app_v5.py`
- Modify: relevant Streamlit smoke test/workflow expectations
- Modify: `tests/test_v5_ui_navigation.py`

**Interfaces:**
- Produces: final page registry with default `Today` and secondary `Matchup Lab` retained as an expert workflow where appropriate.

- [ ] **Step 1: Make Today the default route**

Use the existing Streamlit host, apply `apply_v5_theme()` once after `st.set_page_config()`, and present navigation labels with Today first. Retain Matchup Lab as a secondary expert destination rather than deleting it.

- [ ] **Step 2: Run all UI-focused tests**

Run: `pytest tests/test_v5_ui_today.py tests/test_v5_ui_navigation.py tests/test_v5_ui_performance.py -v`
Expected: PASS.

- [ ] **Step 3: Run the entire repository regression suite**

Run: `pytest -q`
Expected: all tests pass; no pre-existing regression is accepted as part of the UI work.

- [ ] **Step 4: Run Streamlit smoke verification**

Launch the app using the repository's existing smoke mechanism and verify: healthy endpoint, no uncaught exception, Today visible as primary navigation, populated/empty state render does not crash.

- [ ] **Step 5: Verify model-output invariance**

Compare representative pre-redesign board rows against post-redesign source rows for model probability, fair odds, signal, EV, expected margin, and expected total. Values must match exactly; only presentation may differ.

- [ ] **Step 6: Commit final integration**

```bash
git add tennis_quant_app_v5.py tests .github/workflows
git commit -m "feat: complete Apple-style Today V5 experience"
```

## Plan Self-Review

- Spec coverage: Today, Match Detail, All Markets, Performance, Model Health, mobile behavior, error states, model boundaries, and verification are each assigned to an implementation task.
- Placeholder scan: no TBD/TODO/implement-later placeholders remain.
- Type/interface consistency: page modules consume existing pandas dataframes/artifacts and do not introduce parallel probability/market calculations.
- Scope control: Matchup Lab model logic is retained; this plan changes navigation and presentation only.
