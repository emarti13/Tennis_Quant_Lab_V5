# Court-Speed Architecture Amendment

Date: 2026-09-02
Status: User-approved amendment to `2026-09-01-full-context-tennis-model-design.md`

## Purpose

The dynamic court-speed design must not begin each tournament from zero current-event evidence. Early-round predictions require a historically informed prior that is then updated by strictly pre-match current-event observations.

## Required architecture

For every target match, court speed is estimated hierarchically and strictly as-of the prediction cutoff:

1. **Historical event/venue prior.** Use prior editions of the same event/venue as the primary starting estimate.
2. **Recency weighting.** More recent editions receive greater weight than older editions.
3. **Hierarchical fallback.** If same-event history is sparse, shrink toward venue, comparable tournament/surface/altitude, and finally tour/surface baselines.
4. **Current-event update.** Blend only matches completed before the target match into the historical prior.
5. **Current-day update.** Same-day evidence may contribute only when those matches completed before the target prediction cutoff. Later same-day matches are forbidden.
6. **Uncertainty-aware blending.** Historical and current evidence are weighted by effective sample size/reliability rather than blindly averaged.

## Required outputs

The feature contract must expose at minimum:

- `court_speed_historical_prior`
- `court_speed_current_event`
- `court_speed_current_day`
- `court_speed_blended`
- `court_speed_historical_sample_size`
- `court_speed_current_sample_size`
- `court_speed_uncertainty`
- `court_speed_change_vs_historical`
- `court_speed_source_quality`

The change-versus-history term is itself a candidate predictive feature because it captures an event playing materially faster or slower than its normal structural profile.

## Evidence inputs

Court-speed evidence should use opponent-adjusted residuals where feasible, including hold rate, ace rate, break rate, tiebreak rate, first-serve points won, second-serve points won, and games per set. Structural historical priors capture persistent venue/surface characteristics; current residuals capture transient effects such as balls, weather, humidity, wind, and playing conditions.

## Leakage rule

Every court-speed feature must be reproducible from information available before scheduled first serve. Future tournament matches, later same-day matches, and post-match values from the target fixture must not change the target row.

This amendment is part of the approved architecture and is binding on implementation and validation.