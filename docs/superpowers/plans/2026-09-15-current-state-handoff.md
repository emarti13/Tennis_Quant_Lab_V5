# 2026-09-15 V5 Current-State Handoff

**Read first:** `PROJECT_MANDATE.md` and `docs/superpowers/CURRENT_ARCHITECTURE.md`.

## What is already implemented/merged

- Full Daily Forecast Board and separate card-based Decision Feed architecture.
- Multiple qualifying official markets per match are allowed; no one-bet-per-match constraint.
- Official recommendation ledger freezes recommendation-time forecast/price state and rejects duplicate actionable repricings rather than rewriting official history.
- Automatic settlement/performance architecture is downstream of the frozen official ledger.
- Court resolver supports fresh CourtSpeed and canonical court/master-schedule fallback, with nonblocking unknown behavior.
- CourtSpeed parser supports schema-valid empty metric output instead of raising solely because zero rows were recognized.
- Schedule matching fails closed on genuine ambiguity and has explicit Indian Wells / Indian Wells Open → BNP Paribas Open canonical alias behavior.
- Context warehouse workflow was reordered so synchronization happens before generated tracked artifacts dirty the worktree.
- PR #29 merged to main as `d56c30bf17d80239209772181905798517eec6d2` after 362/362 full-regression tests plus CourtSpeed and Streamlit smoke checks passed.

## Do not regress

Do not restore an older card-only app, one-pick-per-match policy, mutable recommendation history, hard CourtSpeed dependency, required manual court entry, duplicate Indian Wells tournament identity, or post-build rebase workflow.

Do not assume a historical plan is current simply because it is detailed. `CURRENT_ARCHITECTURE.md` is the current-state bridge across the dated documents.

## Immediate verification gates after this documentation pause

Resume production-readiness work by verifying on `main`:

1. Context Warehouse workflow actually builds **and publishes** after the workflow-order fix.
2. CourtSpeed refresh reports zero/partial coverage as a nonfatal source-health state and preserves explicit freshness/LKG semantics without blocking production.
3. Canonical production artifacts are fresh enough for the current day.
4. Daily forecast is current and consumes canonical context without hidden page-load rebuilds.
5. Market feed/repricing is current and official frozen recommendations remain immutable.
6. Settlement consumes completed canonical results and updates the official ledger.
7. Results/Performance reflect settled post-reset official recommendations only, with legacy/pre-reset data separated.
8. Any remaining blocker is fixed at both immediate and system level, then the current architecture docs are updated if architecture changes.

## Completion standard

Do not report the self-functioning pipeline as production-ready merely because CI is green. Production readiness requires fresh end-to-end evidence from the scheduled/dispatchable production chain and canonical artifacts.