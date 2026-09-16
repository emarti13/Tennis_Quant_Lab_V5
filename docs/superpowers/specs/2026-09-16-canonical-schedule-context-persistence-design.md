# Canonical Schedule Context Persistence Design

Date: 2026-09-16
Status: Approved in chat

## Goal
Make official ATP, ATP Challenger, WTA Tour, and WTA 125 schedules the authoritative backbone for tournament identity and surface while retaining and re-keying the existing enriched tournament context. Daily Board edits become durable only after a successful **RUN ADJUSTED DAILY BOARD** action.

## Canonical identity
Canonical tournament identity is season-aware and tour/category-aware. Resolve using the strongest available combination of season, tour, category/level, official tournament name, city/location, and schedule week/date. Provider/feed names are aliases into this identity; loose city-only matching must never merge distinct events such as the WTA SP Open and the Sao Paulo ATP Challenger.

Official schedule names and surfaces are authoritative. Normalize surface codes without losing indoor/outdoor information: H = Hard/Outdoor, IH or I H = Hard/Indoor, C/CL = Clay/Outdoor unless explicitly indoor, IC or I C = Clay/Indoor, G = Grass.

## Context enrichment
The current context warehouse remains the source of enrichment characteristics such as altitude, ball type, court speed/CPI, ace-rate/rally characteristics, relative air density/environment, and other validated tournament-level features. Re-key existing enrichment records to canonical tournament IDs rather than discarding or rebuilding valid context.

A blank field is treated as unresolved/data-quality failure until the pipeline has successfully resolved the tournament and exhausted the appropriate context sources/history. Genuine unavailability may remain missing. Never fabricate zero/default context merely to eliminate blanks.

## Daily Board resolution
Production resolution order:
1. Resolve fixture/feed tournament to canonical tournament identity.
2. Load authoritative official-schedule name/surface and indoor/outdoor state.
3. Attach persistent enrichment by canonical ID.
4. Apply previously committed verified context corrections.
5. Build the Daily Board and model features.

Surface and tournament identity should not be blank for an event represented in the canonical schedules. Ambiguous identity resolution fails closed and is surfaced as unresolved rather than fuzzy-attaching to a potentially different event.

## Commit semantics for Daily Board edits
Editing a Daily Board control is temporary session state only. It MUST NOT write to persistent context on widget change, rerender, or any action other than **RUN ADJUSTED DAILY BOARD**.

When **RUN ADJUSTED DAILY BOARD** is clicked:
1. Determine fields actually changed from the resolved canonical values.
2. Validate the proposed changes and canonical tournament identity.
3. Run the adjusted board through the production prediction path.
4. Only if that adjusted run succeeds, persist the changed context fields to the appropriate canonical tournament record/override store.
5. Reload the persistent registry and resolve the tournament again to verify read-back.
6. Report persistence failure explicitly if write/read-back fails; do not claim the change is durable.

A failed adjusted calculation commits nothing. Clicking the button without changing a field must not stamp existing values as manual overrides.

## Future reuse
Committed context is pulled automatically on later fixtures and future Daily Boards for the same canonical tournament identity. Tournament-specific corrections must not leak to similarly named events on another tour/category. Characteristics that legitimately change by season may be season-scoped; stable venue characteristics can be inherited only through explicit canonical rules rather than uncontrolled fuzzy matching.

## Data-quality observability
Track identity resolution and context completeness separately. Distinguish `unresolved` (expected data failed to resolve/attach) from genuinely `missing/unavailable`. Production diagnostics should report match counts and unresolved canonical IDs so a 0/N context-source match is treated as a blocker rather than silently producing a sparse board.

## Verification
TDD coverage must include:
- official schedule identity/surface resolution for ATP, Challenger, WTA Tour, and WTA 125;
- WTA SP Open Sao Paulo resolves to Hard and never to the Sao Paulo Challenger clay record;
- indoor hard remains distinct from outdoor hard;
- existing enrichment survives re-keying to canonical IDs;
- expected blanks are flagged unresolved until source exhaustion is proven;
- editing a widget alone performs no durable write;
- failed adjusted runs perform no durable write;
- successful RUN ADJUSTED DAILY BOARD persists only changed fields;
- fresh registry load/read-back returns the committed values;
- later fixtures for the same canonical tournament inherit committed context;
- similarly named tournaments do not inherit each other's corrections;
- production-equivalent Daily Board smoke test has canonical tournament/surface populated and expected enriched fields attached.

Historical frozen forecasts/recommendations remain immutable.