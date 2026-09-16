# Persistent Enhanced Daily Context Design

Date: 2026-09-16
Status: Approved in chat

## Goal
Activate the validated enhanced context in the live Daily Board while allowing missing tournament context to be filled or corrected once and remembered for future slates and future seasons.

## Contract
- Tournament-level context is canonical, not fixture-session state.
- Daily Board displays the current canonical values for Surface, Environment, Court Speed, CPI, Ace Rate %, Rally Length, Relative Air Density, Altitude m, and Ball Type.
- A user edit persists against canonical tournament identity and is reused on later pulls, including later seasons, until changed again.
- Missing context remains missing. It is never silently converted to zero or a fabricated default.
- The prediction path uses every enhanced feature that is present and omits unavailable enhanced feature contributions for that match.
- Existing sportsbook-independent forecast -> market pricing -> frozen ledger architecture remains intact.
- Historical frozen recommendations are never rewritten by later context edits.

## Persistence
Use a durable tournament-context override registry, keyed by normalized canonical tournament identity rather than fixture ID. The backend context refresh overlays this registry onto generated tournament metadata. Daily Board edits write through the same registry interface. The registry stores only the latest selected value for each tournament-level field; changing a value replaces the prior value.

For deployed Streamlit, durable write-through requires a repository write credential configured as a Streamlit secret/environment value. If durable remote persistence is unavailable, the UI must not claim that a change was saved permanently; it may still run the current adjusted calculation, but must report persistence failure explicitly.

## Modeling
The live feature builder consumes the resolved tournament context before winner and score-distribution prediction. Features with values participate normally. Missing values remain NaN/missing and use the model's validated missing-feature behavior; they do not receive a zero-value adjustment. The same resolved values feed moneyline, spread, and total outputs.

## UI
The existing Daily Board editor remains the single editing surface. Surface, Environment and Ball Type use dropdowns where categorical choices are known. Numeric context fields remain editable numeric fields. Running the board persists changed tournament-level context first, then recalculates the affected slate through the production model path. No Auto/Manual/Unknown provenance labels are required in the customer-facing board.

## Verification
Tests must prove: tournament edits survive a fresh registry load; later fixtures for the same tournament inherit saved values; a later edit replaces the prior value; missing values remain missing; the interactive production path consumes persisted values; and existing frozen history is not rewritten. End-to-end verification must include a production/Streamlit smoke run and inspection that enhanced context fields and enhanced model candidates appear in the resulting board.