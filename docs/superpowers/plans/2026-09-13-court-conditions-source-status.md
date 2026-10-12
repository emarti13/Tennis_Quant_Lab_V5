> **Superseded (2026-10-12).** Court-condition / CourtSpeed work is retired; its code was removed in
> the Step 1 repo cleanup. Surface and court information come from the master tennis schedule
> (see `docs/superpowers/plans/2026-10-12-ground-up-rebuild-plan.md`, Step 2). Kept for history only.

# Court Conditions Implementation Status

Current branch implementation includes the provider-agnostic source adapter, persisted snapshot, live full-context ingestion, Indoor/Outdoor weather applicability, interactive override plumbing, diagnostics, and focused regression tests.

Remaining before merge: run PR CI once, inspect any failures, and fix only verified defects. No live OddsPapi or production refresh is required for this feature verification.
