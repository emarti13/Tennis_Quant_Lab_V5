> **Superseded (2026-10-12).** Court-condition / CourtSpeed work is retired; its code was removed in
> the Step 1 repo cleanup. Surface and court information come from the master tennis schedule
> (see `docs/superpowers/plans/2026-10-12-ground-up-rebuild-plan.md`, Step 2). Kept for history only.

# Court-Speed Prior Amendment

Date: 2026-09-01
Applies to: `2026-09-01-full-context-tennis-model-design.md`
Status: Approved in chat

## Amendment

The court-speed engine must not begin each tournament from a neutral or zero-information state. Every event begins with a historical prior and then updates that prior with current-event evidence as matches are completed.

### Historical prior hierarchy

For a target event, construct a recency-weighted prior in this order:

1. Same canonical tournament / venue in prior seasons.
2. Same venue or city when tournament naming changed but the playing environment is materially continuous.
3. Comparable tournament cohort matched on surface, indoor/outdoor status, altitude, tour level, and climate class.
4. Tour x surface x indoor/outdoor baseline.

The estimator must expose how much of the prior came from each hierarchy level and an uncertainty term that increases as evidence becomes weaker.

### Current-event updating

As current-year matches complete, calculate opponent-adjusted residual signals available strictly before the target match:

- hold-rate residual
- ace-rate residual
- break-rate residual
- tiebreak-rate residual
- first-serve points-won residual
- second-serve points-won residual
- games-per-set residual

Blend the historical prior with current-event evidence using sample-size / uncertainty-aware shrinkage. Current-event information should progressively dominate only when its effective sample is large and internally consistent.

### Current-day updating

A same-day component may be estimated from earlier completed matches that day only. Later matches on the same day may never leak backward. Weather and court-assignment quality flags should remain separate inputs so the model can distinguish a structural venue prior from short-lived atmospheric effects.

### Required output features

- `court_speed_historical_prior`
- `court_speed_historical_sample_size`
- `court_speed_historical_uncertainty`
- `court_speed_current_event`
- `court_speed_current_event_sample_size`
- `court_speed_current_event_uncertainty`
- `court_speed_current_day`
- `court_speed_current_day_sample_size`
- `court_speed_blended`
- `court_speed_blended_uncertainty`
- `court_speed_delta_vs_historical`
- `court_speed_prior_level`

### Validation

Compare at minimum:

1. surface-only baseline
2. historical-prior-only court speed
3. current-event-only court speed
4. historical + current-event blended court speed
5. historical + current-event + current-day blended court speed

The blended implementation is promoted only if it improves later-period winner and/or score-distribution metrics without introducing lookahead. If same-day updates do not add stable out-of-sample value, retain the historical + event blend and reject the same-day component.
