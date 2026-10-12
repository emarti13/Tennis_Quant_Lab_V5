> **Superseded (2026-10-12).** Court-condition / CourtSpeed work is retired; its code was removed in
> the Step 1 repo cleanup. Surface and court information come from the master tennis schedule
> (see `docs/superpowers/plans/2026-10-12-ground-up-rebuild-plan.md`, Step 2). Kept for history only.

# CourtSpeed Refresh / Primary Conditions Source Design

Date: 2026-09-14
Status: User-approved design pending written-spec review
Repository: Tennis_Quant_Lab_V5

## 1. Objective

Make CourtSpeed the primary ongoing source for tournament court-condition evidence while preserving V5 as the automatic fallback whenever CourtSpeed is missing, stale, incomplete, or unavailable.

The production system must refresh CourtSpeed-derived data automatically ahead of upcoming tournaments, persist a validated last-known-good snapshot, resolve each condition field independently, and feed one canonical match-context record into the existing frozen forecast pipeline.

This is Production Reliability plus Research/Model Profitability infrastructure. It must preserve one source of truth, hands-off operation, strict pre-match boundaries, explicit freshness, and no unvalidated changes to production probability math.

## 2. Source Policy

CourtSpeed is the primary source for the foreseeable future for the condition fields it publishes or aggregates.

Primary CourtSpeed-backed fields include, where available:
- surface type;
- environment / indoor-outdoor;
- CPI;
- adjusted ace rate;
- rally length;
- relative air density;
- altitude;
- ball type;
- overall speed rating;
- source timestamp / source year / provenance.

V5 remains the automatic fallback source for any field not available or not fresh enough from CourtSpeed.

Fallback is field-level, not whole-record. A single fixture may legitimately use CourtSpeed for CPI and ball type while using V5 for weather or dynamic court speed.

## 3. Canonical Source Resolution

The canonical condition record for a fixture is resolved in this order for each field:

1. fresh exact-year CourtSpeed value;
2. valid CourtSpeed prior-year value under the existing no-lookahead rules;
3. V5 canonical inferred / dynamic value;
4. unresolved/missing only if neither source can produce a valid value.

Every resolved field must preserve:
- resolved value;
- source provider;
- source year where relevant;
- observed/refreshed timestamp;
- freshness state;
- whether fallback occurred.

CourtSpeed values must never be relabeled as V5, and V5 fallback values must never be presented as CourtSpeed-derived.

## 4. Refresh Architecture

Add a backend CourtSpeed refresh step that runs outside Streamlit.

The refresh flow is:

`upcoming tournament discovery`
→ `CourtSpeed fetch / parse`
→ `schema normalization`
→ `validation`
→ `merge into versioned persisted snapshot`
→ `refresh status / freshness metadata`
→ `canonical field-level CourtSpeed/V5 resolution`
→ `daily context / frozen forecast`

No live CourtSpeed request may occur from a Streamlit page load or interactive render path.

## 5. Schedule

Default cadence: once daily.

The daily refresh should occur before the normal production forecasting window so upcoming-event conditions are available before frozen forecasts are built.

The refresh should target:
- tournaments currently active;
- upcoming tournaments within a bounded discovery horizon;
- already-known current-season events where CourtSpeed may have published new CPI, rally, ace-rate, ball, or environment data since the prior snapshot.

The schedule should avoid unnecessary polling and preserve GitHub Actions budget.

## 6. Upcoming Tournament Discovery

The updater should derive its target event list from the existing canonical fixture / tournament pipeline rather than maintain a separate manual event calendar.

Tournament names should be normalized through the existing event-alias layer used by `v5_court_conditions_source.py`.

If CourtSpeed exposes an event not yet recognized by the alias layer, the refresh should record it as unresolved for review without corrupting an existing event key.

## 7. Persistence and Last-Known-Good

The repository snapshot under `data/court_conditions/` remains the durable canonical CourtSpeed cache.

Refresh behavior must:
- merge new observations without rewriting historical source years;
- preserve prior values when a new fetch omits a field;
- update only fields actually observed from the new source response;
- maintain deterministic ordering / schema;
- write refresh metadata and source timestamp;
- preserve a last-known-good snapshot if fetch or validation fails.

A failed refresh must not replace a valid snapshot with an empty or partially corrupted file.

## 8. Freshness Contract

CourtSpeed freshness is explicit.

Suggested source states:
- `READY` — recent successful refresh and usable data;
- `STALE_LKG` — refresh failed but last-known-good data remains within allowed age;
- `FALLBACK_V5` — CourtSpeed value unavailable or beyond allowed freshness, V5 used;
- `MISSING` — neither CourtSpeed nor V5 can supply a valid field.

Freshness is evaluated per source artifact and, where needed, per field/event.

Stale data must never silently appear fresh.

## 9. Failure and Recovery Behavior

CourtSpeed outage or parser failure must degrade automatically:

- keep last-known-good snapshot unchanged;
- mark refresh status failed/stale;
- use still-valid CourtSpeed fields within the allowed freshness window;
- otherwise fall field-by-field to V5;
- continue production when V5 fallback can produce a mathematically valid context;
- fail closed only if a required condition cannot be resolved safely from either source.

When CourtSpeed recovers, the next scheduled refresh should restore primary-source usage automatically with no manual repair step.

## 10. Relationship to V5 Court Speed

CourtSpeed's CPI and Overall Speed Rating are evidence inputs, not automatic replacements for V5's validated internal court-speed state.

The existing V5 dynamic court-speed model remains authoritative for production probability math unless a new CourtSpeed-derived transformation or coefficient earns promotion through chronological out-of-sample validation.

The source refresh may populate raw CPI, ace rate, rally length, RAD, altitude, ball type, environment, and overall speed evidence immediately because those are data/provenance changes.

Any new predictive weighting, transformation, direct probability adjustment, or replacement of `court_speed_blended` is Model Profitability work and requires walk-forward OOS validation before promotion.

## 11. Weather and Environment

CourtSpeed environment data may establish Indoor/Outdoor when valid.

For Outdoor matches:
- V5 weather remains eligible and may be used alongside CourtSpeed court-condition evidence.

For Indoor matches:
- exposed outdoor weather effects remain suppressed under the approved surface/environment design;
- indoor status is explicit applicability state, not ordinary weather missingness.

CourtSpeed is not required to become the primary live weather provider unless separately approved.

## 12. Canonical Data Contract

The condition record consumed downstream should expose fields equivalent to:

- `surface_type`
- `surface_source`
- `environment`
- `environment_source`
- `cpi`
- `cpi_source`
- `ace_rate_pct`
- `ace_rate_source`
- `rally_length`
- `rally_source`
- `relative_air_density`
- `rad_source`
- `altitude_m`
- `altitude_source`
- `ball_type`
- `ball_source`
- `overall_speed_rating`
- `overall_speed_source`
- `court_speed_model`
- `court_speed_source`
- `source_refreshed_at`
- `source_freshness`

The downstream forecast should consume resolved canonical values rather than implement its own source-selection logic.

## 13. Workflow Integration

The CourtSpeed refresh should be its own lightweight upstream production step or an early stage of the existing context refresh workflow, but it must not create a second forecast path.

Required ordering:

`CourtSpeed refresh`
→ `canonical conditions snapshot`
→ `context refresh`
→ `frozen sportsbook-independent forecast`
→ `repricing`
→ `official recommendation ledger`
→ `settlement/performance`

A CourtSpeed refresh must not trigger OddsPapi debugging or unnecessary market pulls.

## 14. Actions Budget

The refresh workflow must be lightweight and quota-conscious.

Requirements:
- one normal scheduled run per day;
- manual dispatch allowed for recovery/maintenance;
- no high-frequency polling;
- static fixture/unit tests for parser behavior;
- no live CourtSpeed network calls in ordinary CI tests;
- production fetch only in the scheduled refresh job;
- avoid duplicate workflow triggers for the same refresh.

## 15. Testing Contract

Automated tests must prove at minimum:

- exact-year CourtSpeed values outrank V5 fallback;
- prior-year CourtSpeed fallback never looks forward;
- missing CourtSpeed fields fall individually to V5;
- stale CourtSpeed fields fall to V5 after the allowed freshness window;
- refresh failure preserves last-known-good snapshot;
- partial source responses do not erase prior valid fields;
- unresolved tournament aliases do not overwrite another event;
- Indoor continues to suppress outdoor-weather effects;
- source/provenance fields remain accurate after fallback;
- no CourtSpeed network call occurs during Streamlit rendering;
- no CourtSpeed network call occurs in ordinary unit/CI tests;
- canonical forecast consumes resolved condition fields from one source-resolution layer;
- official model math is unchanged unless separately OOS-promoted.

## 16. Observability

Persist a CourtSpeed refresh status artifact containing at least:
- run timestamp;
- source endpoint/version identifier where available;
- events requested;
- events matched;
- rows/fields updated;
- unresolved events;
- whether last-known-good was retained;
- freshness state;
- error summary.

The production health/UI layer may later expose a concise Court Conditions health indicator from this artifact.

## 17. Commercial / Source Portability

The downstream data contract must remain provider-agnostic.

CourtSpeed is the primary source now, but source-specific parsing stays isolated so another provider can replace or supplement it later without changing the canonical forecast/context interfaces.

Do not embed CourtSpeed-specific assumptions inside model or UI calculations.

## 18. Non-Goals

This change does not:
- make CourtSpeed a live dependency of Streamlit;
- make a CourtSpeed outage halt production when V5 fallback is valid;
- replace V5 weather with CourtSpeed weather;
- treat CPI as identical to V5 court speed;
- introduce unvalidated CPI/ace/rally/ball coefficients;
- rewrite frozen historical predictions;
- add sportsbook prices to model formation;
- create a second production forecast path.

## 19. Mandate Alignment

1. **Low manual intervention:** scheduled refresh and automatic fallback remove tournament-by-tournament manual updates.
2. **One source of truth:** one canonical resolved condition record feeds the existing forecast pipeline.
3. **Statistical validity:** CourtSpeed improves source evidence without bypassing OOS promotion rules for new predictive effects.
4. **Sellable MVP:** richer and fresher condition context improves production quality while remaining auditable and resilient.

The intended steady state is that V5 can encounter a new tournament, attempt to populate its condition evidence from CourtSpeed automatically, fall back safely where CourtSpeed is incomplete, and continue the canonical production pipeline without user intervention.
