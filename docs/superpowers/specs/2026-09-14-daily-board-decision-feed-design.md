# Daily Board + Decision Feed Design

## Classification

Architectural change spanning **Product UX**, **Production Reliability**, and a bounded **Model Profitability** policy repair.

## Goal

Restore the full Daily Board as the primary analytical/control surface while retaining the card-based experience as a separate Decision Feed that consumes the exact latest board result set. Preserve the canonical production pipeline and frozen historical forecasts, and repair the current all-REVIEW signal regression without introducing an unvalidated recommendation policy.

## Governing constraints

This design is subordinate to `PROJECT_MANDATE.md` and must preserve:

- one canonical production source of truth per stage;
- no heavy model/context rebuilds inside passive Streamlit page loads;
- frozen sportsbook-independent production forecasts for settlement and OOS tracking;
- no rewriting of historical official predictions when the user edits an interactive scenario;
- explicit separation between official production recommendations and user-adjusted scenarios;
- recommendation-policy changes only when supported by chronological/OOS evidence.

## Product structure

Navigation becomes:

1. **Daily Board**
2. **Decision Feed**
3. **Match Detail**
4. **All Markets**
5. **Performance**
6. **Model Health**
7. **Matchup Lab**

The current card renderer is retained and reused by Decision Feed rather than removed.

## Daily Board

Daily Board is the primary working surface.

On load it should show the latest available canonical production slate/result set without requiring a manual model rebuild. It exposes the full analytical table and the existing interactive scenario controls.

Required editable context fields include:

- Surface
- Environment (Indoor / Outdoor)
- Court Speed
- CPI
- Ace Rate %
- Rally Length
- Relative Air Density
- Altitude m
- Ball Type
- existing tour / best-of overrides where already supported

The board must display, where available:

- player win probabilities;
- fair odds;
- expected game margin;
- expected total;
- current sportsbook prices;
- EV / edge;
- BET / LEAN / REVIEW / PASS status;
- model agreement / disagreement;
- player form, volatility, and state confidence;
- court-condition provenance and freshness;
- diagnostic notes needed to understand blocked or review-only rows.

Users can sort, filter, download, and rerun either the full slate or selected fixtures using adjusted context.

## Production state vs adjusted scenario state

The system must never overwrite the frozen official production forecast when the user changes context interactively.

Daily Board therefore has two result modes:

### Production Forecast

The canonical backend-produced forecast and repricing artifacts. These remain the official source for recommendation ledger, settlement, performance, and OOS monitoring.

### Adjusted Scenario

A Streamlit-session result produced from the same accepted model code using user overrides. Adjusted Scenario results are exploratory/interactive only and must be explicitly labeled as such.

A completed interactive rerun becomes the **active board state for the session**. Until another rerun occurs, downstream UX pages may consume that active board state. It must not mutate canonical production artifacts or the official recommendation ledger.

## Decision Feed

Decision Feed is a separate decision-first page built from the active Daily Board result set.

Source precedence within a Streamlit session:

1. latest successfully completed Adjusted Scenario board, if one exists;
2. otherwise latest canonical Production Forecast board.

Decision Feed must not run another model and must not recalculate probabilities independently. It ranks and renders the exact values already present in the active board.

Cards are ordered by signal tier and then EV within tier:

**BET → LEAN → REVIEW → PASS / NO PRICE**

Default customer-facing feed should emphasize BET and LEAN first, with REVIEW visible in a secondary section rather than allowing REVIEW to dominate the page. PASS / NO PRICE may be collapsed or omitted from the primary feed.

Every feed must clearly display its source mode:

- **Production Forecast**
- **Adjusted Scenario**

Cards continue to show projection, fair odds, expected margin/total, model state/context, market odds, quantified edge, and market-level signal details.

## Shared result contract

Daily Board and Decision Feed must consume one normalized board schema rather than maintain parallel transformations.

The normalized board includes at minimum:

- fixture identity and match metadata;
- context inputs and provenance;
- model probabilities / fair prices;
- expected score distribution summaries;
- market prices and model pricing metrics;
- market-level signals;
- derived primary market / best signal;
- mode (`production` or `adjusted`);
- scenario timestamp / production as-of timestamp.

The existing card preparation logic should remain a presentation/ranking transformation over this board, not a separate signal engine.

## Signal-policy regression: all REVIEW

The current production signal function forces `REVIEW` whenever `state_confidence < 0.45` before evaluating BET/LEAN EV and edge thresholds. Production pricing passes market-specific state confidence into this gate. This can collapse an entire slate into REVIEW when player-state confidence values are broadly below 45%.

This behavior must be treated as a recommendation-policy regression, not worked around in the card layer.

### Repair rules

1. Do not simply remove or lower the 0.45 threshold by intuition.
2. Reproduce the current slate classification and quantify how many otherwise qualifying BET/LEAN rows are downgraded solely by the confidence gate.
3. Evaluate the confidence gate chronologically on historical priced predictions where available, comparing at least:
   - current hard gate;
   - no hard gate, confidence retained as diagnostic/ranking metadata;
   - one or more evidence-based graduated policies if sample size permits.
4. Compare OOS units, ROI, drawdown, hit rate where meaningful, calibration by confidence bucket, and sample count.
5. Only a policy supported by evidence may drive official production signals.
6. Until a replacement policy earns promotion, preserve the current official production policy rather than silently changing historical meaning.
7. Interactive Adjusted Scenario output may display the raw EV/edge alongside the official signal so the user can distinguish "pricing edge exists" from "official policy downgraded to REVIEW."

The objective is to prevent a confidence-quality diagnostic from unintentionally making the product unusable while preserving statistical governance.

## Context controls and CourtSpeed

CourtSpeed remains the primary physical court-condition source when covered. V5 fallback remains automatic for missing fields/events.

Interactive overrides take precedence only for the Adjusted Scenario calculation. They must never rewrite CourtSpeed snapshots or production context history.

Court-speed numeric overrides remain on the validated internal V5 court-speed scale. Raw CPI remains a separate observable field and must not be substituted directly for internal court speed.

## Backend dependency handling

Daily Board must not silently rebuild TennisMyLife history or other heavy context during passive page load.

The persisted context warehouse remains a backend responsibility. The production pipeline must make required context artifacts durably available to Streamlit. If those artifacts are unavailable, the app must display the true dependency/freshness state rather than instructing the user to perform a model rebuild that violates production architecture.

Interactive reruns require the persisted context assets already available locally to the app. Missing required assets fail closed with a precise explanation.

## UX behavior

Daily Board is dense by design because it is the operator/analytical workspace. It should use a wide dataframe/editor and collapsible advanced diagnostics rather than convert every match into a card.

Decision Feed is the mobile-friendly concise view. Cards remain visually compact and optimized for quickly identifying the strongest current selections.

A user should be able to:

1. open Daily Board and inspect the full slate;
2. adjust one or more context values;
3. rerun the slate or selected matches;
4. immediately open Decision Feed;
5. see cards generated from those exact adjusted results;
6. return to the canonical Production Forecast state without altering historical production artifacts.

## Testing and acceptance

Implementation must use TDD and include coverage for:

- navigation exposes Daily Board and Decision Feed separately;
- Daily Board renders the full normalized board;
- editable context controls map to the existing override fields correctly;
- adjusted reruns update session active-board state;
- Decision Feed consumes active-board state without recalculating probabilities;
- production and adjusted modes are clearly labeled;
- canonical production artifacts remain unchanged after adjusted reruns;
- card ranking preserves BET → LEAN → REVIEW priority;
- signal-policy diagnostic reproduces the all-REVIEW downgrade mechanism;
- any promoted signal-policy change has an evidence artifact and OOS validation tests;
- persisted context-warehouse failure states remain explicit;
- full repository regression passes;
- Streamlit smoke verifies both Daily Board and Decision Feed navigation and rendering.

## Completion criteria

This work is complete only when:

- the full Daily Board is usable again in deployed Streamlit;
- surface/environment/court-condition adjustment controls work end to end;
- an adjusted rerun flows into Decision Feed cards from the same result set;
- Production Forecast remains frozen and auditable;
- Decision Feed no longer behaves as the only usable interface;
- the all-REVIEW behavior has been diagnosed quantitatively and either corrected through an evidence-backed policy promotion or explicitly surfaced as an official-policy constraint with raw edge diagnostics;
- relevant regression and Streamlit smoke checks are green;
- the deployed experience is verified, not merely unit-tested.