# V5 Architecture Documentation Policy

## Why

V5 evolves quickly. Historical specs/plans are intentionally retained, but future sessions must not mistake historical detail for current behavior.

## Required hierarchy

`PROJECT_MANDATE.md` → `CURRENT_ARCHITECTURE.md` → current specs → current plans → production implementation/evidence → experiments.

`SUPERSESSION_MAP.md` and `DEPRECATED_BEHAVIOR.md` are interpretation aids for older documents.

## When architecture changes

A PR/merge that changes production architecture should update, as applicable:

- `CURRENT_ARCHITECTURE.md` — what is true now.
- `ARCHITECTURE_CHANGELOG.md` — what changed and when.
- `SUPERSESSION_MAP.md` — which older assumption is now unsafe.
- `CURRENT_PRODUCTION_STATUS.md` — what is actually verified in production versus only implemented/tested.
- relevant new spec/plan when detailed design or execution guidance is needed.

Do not rewrite all historical plans after every change. Preserve history and make supersession explicit.

## Verification language

Documentation must distinguish:

- designed/approved;
- implemented;
- CI verified;
- merged to main;
- production workflow verified;
- current artifact freshness verified;
- end-to-end production ready.

Never collapse those states into a generic `done` claim.