# Tennis Quant Lab V5 — Superpowers Documentation Index

Before using any spec, plan, or implementation document in this directory, read the repository-root [`PROJECT_MANDATE.md`](../../PROJECT_MANDATE.md), then read [`CURRENT_ARCHITECTURE.md`](CURRENT_ARCHITECTURE.md).

The governing order is:

1. `PROJECT_MANDATE.md` — highest-level product and engineering acceptance contract.
2. `docs/superpowers/CURRENT_ARCHITECTURE.md` — current merged architecture and anti-regression contract; this prevents older dated documents from restoring superseded behavior.
3. `docs/superpowers/specs/` — approved architecture and behavior specifications, interpreted through the current architecture contract.
4. `docs/superpowers/plans/` — implementation plans for approved specifications; older plans are historical where later architecture supersedes them.
5. Production code/workflows — implementation of the above and the evidence needed to confirm actual current behavior.
6. Experiments/local fixes — must not override the mandate or approved/current architecture.

All work should continuously feed back to the same target:

**hands-off operation + durable out-of-sample edge + sellable MVP**.

A local fix is allowed when appropriate, but it must be checked against the full production system before being considered complete.

## Anti-regression rule

Do not infer current V5 behavior from the date or detail of an old plan alone. Before continuing a subsystem, compare its dated plan/spec with `CURRENT_ARCHITECTURE.md` and the current production implementation. If they conflict, do not resurrect the older behavior. Update the current architecture document whenever an approved merged change supersedes it.