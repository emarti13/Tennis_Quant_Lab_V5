# Tennis Quant Lab V5 — Apple-style “Today” UI Redesign

Date: 2026-09-02
Status: Approved design direction, pending written-spec review

## Objective

Redesign the Streamlit product surface so the first experience is calm, intuitive, and decision-oriented while preserving the full analytical depth already available in V5.

The product should feel closer to an Apple-designed analytical app than a traditional quantitative dashboard: strong hierarchy, generous spacing, restrained color, clear primary actions, and progressive disclosure.

The model architecture, market logic, probability generation, production candidate selection, and frozen prediction workflow are out of scope for this redesign. The UI consumes those outputs; it does not change them.

## Product Principle

**Simple first. Deep on demand.**

A user should be able to open the app and understand the strongest actionable matches in seconds. Full model diagnostics remain available one layer deeper for analysis, validation, and auditability.

## Primary Navigation

The top-level app is organized around five destinations:

1. **Today** — default landing page; strongest actionable matches for the current slate.
2. **Match Detail** — full reasoning and market breakdown for one fixture.
3. **All Markets** — dense, searchable analyst view for the full slate.
4. **Performance** — honest settled performance, including fixture-clustered reporting.
5. **Model Health** — validation, calibration, data freshness, production model selections, and diagnostic status.

The existing functionality is not removed. Dense diagnostics and raw data move out of the primary path and into the appropriate secondary destination.

## Today Page

### Header

A compact product header shows:

- Tennis Quant Lab
- current slate date
- number of matches analyzed
- last successful refresh timestamp
- compact model/data health state

The header should not compete visually with the slate.

### Summary Strip

Four compact summary cards appear directly beneath the header:

- **Best Edge** — strongest qualified model-vs-market edge on the slate
- **Qualified Plays** — count of BET/LEAN opportunities according to the current production policy
- **Model Health** — concise state derived from current production/validation artifacts
- **Markets Live** — count of active books / current market freshness indicator

These cards summarize the board without requiring interpretation of a dataframe.

### Match Cards

The primary slate is presented as ranked match cards rather than a full-width raw table.

Each card shows only the information needed for a first-pass decision:

- player names
- tournament
- start time
- tour
- Bo3/Bo5
- primary recommended market
- signal pill: BET / LEAN / REVIEW / PASS
- model probability
- fair American odds
- best available market price
- model edge
- one concise “Why it stands out” explanation
- “View analysis” affordance

Example information hierarchy:

**Jannik Sinner vs Alex de Minaur**  
US Open · 7:00 PM · Men · Bo5

**Sinner -4.5 games**  `BET`

Model **67%** · Fair **-203**  
Best market **-115** · Edge **+13.5%**

Why it stands out: stronger contextual margin profile, favorable return matchup, low model disagreement.

The explanation should be generated only from deterministic model/context fields already available in the app. It must not invent qualitative tennis narratives unsupported by the data.

### Ranking

Cards are sorted by current production policy and actionability, not simply by absolute edge. The existing model/policy remains authoritative.

Recommended hierarchy:

1. BET
2. LEAN
3. REVIEW
4. PASS

Within the same signal tier, use the current production ranking logic or qualified edge ranking already present in the board.

PASS rows should not dominate the default viewport. They may appear in a collapsed “Other Matches” area or remain primarily in All Markets.

## Match Detail

Selecting a match exposes the complete analytical layer without leaving the user in a wall of columns.

Information is grouped into clear sections:

### Overview

- winner probability and fair odds
- primary spread projection
- primary total projection
- current best market prices
- signal and edge
- uncertainty / model disagreement

### Matchup Context

- serve/return strength comparison
- recent form/state inputs
- rest and workload
- travel / timezone context
- court speed / altitude context where available
- relevant player-state uncertainty

### Market Board

All available ML, spread, and total lines for the fixture, including alternate lines. Correlated markets are visually grouped by market family.

### Model Detail

- production winner candidate used for the tour
- production score candidate used for the tour
- selected probability components
- score-distribution expectations
- relevant calibration/uncertainty metadata

### Raw / Audit Data

A final expander contains the dense raw fields for debugging and expert inspection.

## All Markets

This is the power-user view.

It retains a dataframe-style presentation but improves usability through:

- search
- tour filter
- tournament filter
- market filter
- signal filter
- Bo3/Bo5 filter
- sort by edge / probability / start time / signal
- compact default columns
- optional “show advanced columns” toggle

The goal is not to eliminate tables; it is to move them to the place where a table is the correct interaction model.

## Performance

The Performance page must not overstate results from correlated markets.

It should show both:

- raw market-level W-L-P / ROI
- unique fixture-level performance

Additional breakdowns:

- ML / spread / total
- tour
- Bo3 / Bo5
- favorite / underdog where applicable
- probability buckets
- signal tier
- fixture market count / maximum correlated markets
- Brier score and log loss for applicable binary probability markets

Headline language must distinguish “market results” from “independent fixtures.”

## Model Health

This page replaces scattered technical status information with a compact system-health view.

It should include:

- current production winner candidate for MEN and WTA
- current production score candidate for MEN and WTA
- most recent validation result
- full regression status
- Streamlit smoke status
- data freshness
- market feed freshness
- context warehouse freshness
- unresolved data-quality warnings

Detailed JSON/report content can remain behind expanders.

## Visual Design System

### Overall Feel

- generous whitespace
- light neutral background
- white or subtly elevated cards
- rounded corners
- restrained shadows or borders
- high-contrast typography
- minimal decoration
- one primary accent color
- color used to support hierarchy, not to turn the screen into a red/green trading terminal

### Typography

Use a clean system-font stack compatible with Streamlit/browser environments. Prefer native system fonts rather than shipping proprietary font files.

Hierarchy:

- large but restrained page title
- strong match/player names
- medium-weight primary market
- muted metadata
- compact numerical secondary details

### Signal Styling

BET / LEAN / REVIEW / PASS are small rounded pills.

Do not rely on color alone. Text labels remain explicit for accessibility and clarity.

### Number Formatting

- probabilities shown as percentages
- American odds shown side-by-side with model probability
- edges shown consistently to one decimal place unless additional precision is useful for diagnostics
- timestamps formatted for human readability

## Responsive Behavior

The Today page must remain usable on mobile.

Desktop:
- summary strip in one row when space allows
- cards use full content hierarchy

Mobile:
- summary cards wrap cleanly
- match cards become single-column
- no horizontally scrolling primary decision table
- secondary analytics remain collapsed by default

All Markets may retain horizontal table behavior because it is explicitly the analyst view.

## Data and Logic Boundaries

The redesign must not:

- recalculate winner probabilities independently in UI code
- alter model thresholds
- alter BET/LEAN/REVIEW/PASS policy
- alter fair odds calculation
- alter market selection logic
- introduce sportsbook information upstream of frozen model outputs
- replace production candidate artifacts with UI defaults

The UI should consume current V5 production outputs and expose them with better hierarchy.

## Error / Empty States

### No market feed

Show a compact human-readable state explaining that model projections may exist but live market comparison is unavailable. Do not throw a dataframe/read error into the user surface.

### No qualified plays

Show a deliberate empty state such as “No qualified plays on the current slate” and still allow access to All Markets.

### Stale data

Show the stale timestamp and a subdued warning badge rather than silently presenting old data as current.

### Missing optional context

Render the strongest available validated subset and mark unavailable context as unavailable. Do not fabricate context values.

## Implementation Architecture

The existing Streamlit app remains the host application.

The redesign should introduce focused UI helpers instead of adding more presentation responsibility to the already-large main app file.

Recommended modules:

- `v5_ui_theme.py` — CSS/theme tokens and shared styling helpers
- `v5_ui_today.py` — Today page and match-card rendering
- `v5_ui_match_detail.py` — match detail sections
- `v5_ui_performance.py` — performance presentation
- `v5_ui_health.py` — model/data health presentation

Existing data-loading/model functions should be reused rather than duplicated.

The main `tennis_quant_app_v5.py` should orchestrate navigation and pass prepared data into these presentation modules.

## Testing

The redesign requires both behavioral and smoke coverage.

Minimum contracts:

1. Today page renders with a populated board.
2. Today page renders a deliberate empty state with no qualified plays.
3. Missing/empty market files do not crash the Today page.
4. Match cards preserve model probability, fair odds, market price, edge, and signal from source rows.
5. Card ranking does not alter production policy ordering semantics.
6. Alternate markets remain accessible in Match Detail / All Markets.
7. Performance page reports both raw-market and fixture-clustered metrics.
8. Mobile-safe primary layout does not require a wide dataframe for the Today experience.
9. Existing full regression suite remains green.
10. Streamlit smoke test remains green.

## Acceptance Criteria

The redesign is complete when:

- Today is the default, visually calm landing experience.
- A user can identify the strongest current opportunity in under a few seconds without reading a dataframe.
- Full analytical depth is still available within one interaction from each match card.
- Existing production model outputs and decision policy are unchanged.
- Dense raw tables are moved to analyst/deep-detail contexts rather than removed.
- Performance reporting visibly distinguishes correlated market results from fixture-level evidence.
- Model/data freshness and health are understandable without reading JSON.
- The app remains functional on Streamlit Cloud and on mobile-width screens.
- Full regression and Streamlit smoke verification are green after implementation.
