# Schedule-to-Court-Dynamics Design

Date: 2026-09-14
Status: Approved in chat

## Goal
Integrate the comprehensive 2025-2027 tennis master schedule into V5 so tournament-specific structural court conditions inform the leak-safe dynamic court-speed state used by production modeling.

## Source contract
The schedule contains: Year, Circuit Tour, Tournament Name, City Venue, Surface, Setting, Altitude (m), Altitude (ft), Speed Profile, Ball Characteristics.

The schedule is a different source from the V5 warehouse, so tournament names must never be joined by raw equality alone. A missing direct-name match is not an automatic NaN.

## Event reconciliation
For every warehouse/live event, candidate schedule rows are restricted first by compatible year and tour family. Candidate scoring then uses normalized tournament name similarity, token overlap, sponsor-insensitive name variants, surface agreement, city/venue evidence when available, and level/circuit compatibility when available.

Resolution states:
- exact: unique normalized-name match after year/tour filtering
- alias: deterministic alias/stripped-name match
- fuzzy_high: unique high-confidence scored candidate with a sufficient margin over runner-up
- ambiguous: plausible candidates exist but confidence/margin is insufficient
- unmatched: no plausible schedule candidate after candidate search

Every resolved row retains schedule_match_score, schedule_match_method, schedule_match_candidate_count, matched schedule name and source fields. Ambiguous matches fail closed rather than silently attaching the wrong venue.

## Court-dynamics hierarchy
The schedule is structural context, not a hard-coded betting adjustment. Court-speed evidence remains learned from completed match residuals.

For each target match, the historical prior hierarchy is:
1. same canonical event historical residuals from prior years;
2. schedule-structural cohort historical residuals using tour family, surface, setting, speed-profile family and altitude band;
3. existing tour/surface/indoor fallback.

Current-event and current-day completed-match evidence then update the historical prior exactly as in the approved court-speed architecture. The target match and later matches remain excluded.

This means schedule labels such as High Altitude, Slow Court / Fast Air, indoor hard, ball characteristics and venue altitude influence the prior through historically observed behavior rather than arbitrary fixed coefficients.

## Feature contract
Resolved schedule context is exposed on enriched player rows:
- schedule_tournament_name
- schedule_city_venue
- schedule_surface
- schedule_setting
- schedule_altitude_m
- schedule_speed_profile
- schedule_speed_profile_family
- schedule_ball_characteristics
- schedule_match_method
- schedule_match_score
- schedule_match_candidate_count

Court-speed output adds:
- court_speed_structural_prior
- court_speed_structural_sample_size
- court_speed_structural_uncertainty
- court_speed_prior_level may now be same_event, schedule_structural, tour_surface_indoor, or none

Existing outputs court_speed_historical_prior, court_speed_current_event, court_speed_current_day, court_speed_blended, uncertainty and delta remain backward compatible.

## Leakage rules
Schedule data is static pre-match metadata. Historical speed residuals use only prior years for historical priors. Current-event/day residuals use only matches with timestamps strictly before the target timestamp. Rows at the exact same timestamp are priced before any row in that batch updates state.

## Production integration
The schedule CSV is versioned in the repository. Venue/context registry construction enriches warehouse tournament rows with resolved schedule context. Player-history enrichment carries those fields into court-speed feature construction. Existing production consumers retain their interfaces and gain the new features without requiring manual matching.

## Validation
Tests must cover sponsor/name differences, year suffix removal, city-assisted matching, surface/tour rejection, ambiguous candidate fail-closed behavior, structural fallback usage, same-event precedence, and no same-day/future leakage.
