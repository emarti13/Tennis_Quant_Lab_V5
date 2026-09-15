# READ BEFORE V5 WORK

Before changing Tennis Quant Lab V5, an engineering agent must:

1. Read `/PROJECT_MANDATE.md`.
2. Read `/docs/superpowers/CURRENT_ARCHITECTURE.md`.
3. Read `/docs/superpowers/SUPERSESSION_MAP.md`.
4. Read the relevant dated specs/plans for the subsystem.
5. Inspect the current `main` implementation and canonical artifacts/workflows before deciding what is missing.

## Stop conditions

Stop and re-check the current architecture before implementing any change that would:

- remove the full Daily Forecast Board in favor of cards only;
- enforce one official bet per match;
- mutate a frozen official recommendation during repricing;
- make CourtSpeed or manual court entry mandatory for ordinary forecast generation;
- silently invent court-condition context;
- recreate Indian Wells as a competing same-tour identity to BNP Paribas Open;
- rebuild heavy upstream production state inside Streamlit;
- add a duplicate production source of truth;
- tune the model/policy because of a short recent streak;
- claim a production fix from CI alone without checking the relevant production path.

## Documentation maintenance

If an approved merged change alters architecture, update `CURRENT_ARCHITECTURE.md`, `SUPERSESSION_MAP.md` where relevant, and `ARCHITECTURE_CHANGELOG.md` in the same workstream. This is part of completion, not optional cleanup.