> **Superseded (2026-10-12).** Court-condition / CourtSpeed work is retired; its code was removed in
> the Step 1 repo cleanup. Surface and court information come from the master tennis schedule
> (see `docs/superpowers/plans/2026-10-12-ground-up-rebuild-plan.md`, Step 2). Kept for history only.

# Court Conditions Source Build — 2026-09-13

Work category: Model Profitability / Production Reliability

## Implemented on feature branch

- Source-agnostic `v5_court_conditions_source.py` adapter.
- Persisted CourtSpeed-derived 2024–2026 snapshot for Slams, Masters 1000s, and ATP Finals.
- Metric-specific exact/prior-year fallback with source-year provenance; future-year fallback forbidden.
- Live full-context targets now carry Surface, Indoor/Outdoor, CPI, adjusted ace rate, rally length, RAD, altitude, ball type, overall speed rating, and source metadata.
- Indoor targets suppress exposed outdoor weather inputs in the matchup context.
- Existing internal `court_speed_blended` remains authoritative; CPI is never copied directly into that scale.
- Interactive production plumbing accepts Environment and internal Court Speed overrides plus CPI/Ace/Rally/RAD/Altitude/Ball scenario metadata.

## Model-governance note

Surface, Indoor/Outdoor applicability, and the existing internal court-speed state are connected to the accepted model/context path. CPI, ace rate, rally length, and ball type are now available as canonical pre-match context but have no newly invented production coefficients. Any new direct coefficient or external-to-internal speed transform remains gated by chronological out-of-sample validation under the project mandate.

## Resource rule

No live OddsPapi call or production workflow run was used for this feature work. Verification is intended to use repository tests/PR CI only.