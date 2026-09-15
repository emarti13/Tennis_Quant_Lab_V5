# Tennis Quant Lab V5 — Superpowers Documentation Index

Before using any spec, plan, or implementation document in this directory, read the repository-root [`PROJECT_MANDATE.md`](../../PROJECT_MANDATE.md) **and** [`specs/2026-09-15-current-production-architecture.md`](specs/2026-09-15-current-production-architecture.md).

The governing order is:

1. `PROJECT_MANDATE.md` — highest-level product and engineering acceptance contract.
2. `docs/superpowers/specs/2026-09-15-current-production-architecture.md` — current accepted production architecture and anti-regression baseline.
3. Other approved documents in `docs/superpowers/specs/` — domain architecture and behavior specifications, interpreted consistently with the current baseline.
4. `docs/superpowers/plans/` — implementation plans for approved specifications; older plans are historical guidance when later accepted architecture supersedes them.
5. Current production code/workflows — implementation evidence that must be inspected before changing behavior.
6. Experiments/local fixes — must not override the mandate or approved architecture.

## Anti-regression rule

Do **not** implement an older plan/spec literally when it conflicts with a later accepted architecture or current canonical production behavior. First reconcile the document against the current-production baseline and `main`, then update stale documentation rather than reverting the product.

This is especially important for the current V5 architecture:

- one canonical production pipeline from refresh through UI;
- full Daily Forecast Board plus separate card-based Decision Feed;
- multiple official markets per match allowed when each independently qualifies;
- frozen sportsbook-independent forecast followed by repeatable market repricing;
- immutable official recommendation ledger and post-reset performance boundary;
- settlement/performance derived from canonical official artifacts;
- context warehouse built upstream, not during Streamlit page loads;
- CourtSpeed/live court data treated as nonblocking enrichment with canonical court-file fallback and UNKNOWN/no-adjustment behavior;
- optional manual court input only, never a required daily production step;
- known tournament aliases such as Indian Wells / Indian Wells Open resolving to BNP Paribas Open without weakening genuine ambiguity safeguards;
- production workflow fixes must be verified on `main` before being called complete.

All work should continuously feed back to the same target:

**hands-off operation + durable out-of-sample edge + sellable MVP**.

A local fix is allowed when appropriate, but it must be checked against the full production system before being considered complete.