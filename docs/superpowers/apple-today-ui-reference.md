# Apple-style Today UI — Maintenance Reference

This document is the durable product reference for the Tennis Quant Lab V5 interface redesign approved on 2026-09-02.

## Product Contract

The UI follows one rule: **simple first, deep on demand**.

The first screen must answer three questions quickly:

1. What are the strongest current opportunities?
2. Why does the model like them?
3. Can I inspect the deeper evidence without hunting through raw tables?

If a future change makes those questions harder to answer, it is a regression even if more data is visible.

## Primary Information Hierarchy

### Today

Default landing page. Shows the current slate as ranked match cards rather than a dataframe-first dashboard.

Each card should surface only:

- fixture/player names
- tournament, start time, tour, Bo3/Bo5
- strongest existing production market/signal
- model probability
- fair American odds
- best market price when available
- model edge
- one deterministic evidence-based explanation
- one interaction to open deeper analysis

BET and LEAN are primary. REVIEW is secondary. PASS must not dominate the default viewport.

### Match Detail

One fixture, progressively disclosed:

- Overview
- Matchup Context
- Market Board
- Model Detail
- Raw/Audit Data

No qualitative explanation may be invented when the supporting context field is absent.

### All Markets

Power-user table view. This is where density belongs. It keeps the full market slate searchable/filterable without turning Today back into a spreadsheet.

### Performance

Must always distinguish raw market outcomes from independent fixture-level evidence.

Example: three correlated winning totals from one fixture plus two losing fixtures may be 3-2 at the market level, but they are not five independent model observations. UI copy and headline metrics must preserve that distinction.

### Model Health

Communicates production winner candidate, production score candidate, validation state, regression/smoke state, market/context freshness, and unresolved warnings. Missing evidence is `unknown` or `unavailable`, never silently green.

## Visual Contract

- Native system-font stack; no shipped proprietary fonts.
- Light neutral canvas.
- White/subtly elevated rounded surfaces.
- Restrained borders/shadows.
- Generous whitespace.
- Strong typographic hierarchy.
- One primary accent color.
- BET/LEAN/REVIEW/PASS use explicit text pills; never rely on color alone.
- Avoid permanent red/green trading-terminal styling.
- Primary Today experience must be mobile-safe without a wide horizontal dataframe.

## Model / UI Boundary

The UI may format, rank, group, filter, and explain existing output fields.

The UI must not:

- recalculate winner probabilities
- recalculate fair odds from an alternate formula
- change BET/LEAN/REVIEW/PASS thresholds
- alter EV
- change production winner/score candidate selection
- introduce sportsbook prices upstream of frozen model output
- fabricate missing context

When presentation needs a derived label such as `primary market`, derive it only from existing signal/EV fields under the current policy hierarchy.

## Performance Integrity

Any public-facing or internal headline win-rate view should display enough context to prevent correlated-market inflation.

Preferred headline set:

- raw market W-L-P
- raw market win rate / ROI
- number of unique fixtures
- fixture profitable rate
- maximum correlated markets per fixture
- ML Brier/log loss where applicable

Additional breakdowns: market family, tour, Bo3/Bo5, signal, favorite/underdog where supported, probability bucket.

## Error-State Contract

- Empty market feed: human-readable state; no pandas stack trace.
- No qualified plays: deliberate empty state plus access to All Markets.
- Stale feed: display timestamp and subdued stale indicator.
- Missing optional context: render strongest available validated subset and label missing context unavailable.

## Files

Design spec:
`docs/superpowers/specs/2026-09-02-apple-today-ui-design.md`

Implementation plan:
`docs/superpowers/plans/2026-09-02-apple-today-ui.md`

Expected presentation modules:

- `v5_ui_theme.py`
- `v5_ui_today.py`
- `v5_ui_match_detail.py`
- `v5_ui_performance.py`
- `v5_ui_health.py`

Host/orchestration:
`tennis_quant_app_v5.py`

## Acceptance Reminder

The redesign is not complete merely because the app looks cleaner. It is complete only when:

- Today is clearly the default product surface.
- The strongest opportunity is understandable within seconds.
- Deeper analysis is one interaction away.
- Model outputs are numerically invariant from the pre-redesign source data.
- Raw tables are still available where appropriate.
- Performance reporting remains honest about correlated markets.
- Model/data health is understandable without reading JSON.
- Full regression and Streamlit smoke verification are green.
