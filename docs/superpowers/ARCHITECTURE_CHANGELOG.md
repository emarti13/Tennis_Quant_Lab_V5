# Tennis Quant Lab V5 — Architecture Changelog

This is a compact supersession log. It is not a substitute for `CURRENT_ARCHITECTURE.md`.

## 2026-09-15 — Production automation blockers / canonical tournament identity

- Context Warehouse publication reordered: synchronize before build; do not rebase a dirty generated worktree.
- Court conditions formally treated as nonblocking enrichment with canonical schedule fallback and explicit unknown behavior.
- Empty CourtSpeed parsing made schema-safe.
- Genuine schedule ambiguity fails closed.
- `Indian Wells` and `Indian Wells Open` resolve to canonical `BNP Paribas Open`; they are not competing same-tour tournament identities.
- PR #29 merged as `d56c30bf17d80239209772181905798517eec6d2` after 362-test full regression + CourtSpeed + Streamlit smoke passed.

## 2026-09-14 — Daily Board / Decision Feed and official recommendation contract

- Full Daily Forecast Board retained as the complete slate/workbench.
- Card-based Decision Feed established as a separate strongest-selection surface rather than replacing the board.
- Removed conceptual one-bet-per-match limitation: multiple markets can be official when independently qualified.
- Official recommendations freeze recommendation-time state; repricing does not rewrite history.
- Ancillary/non-official candidates remain trackable/auditable.
- Results Accuracy/Performance contract separates official tracked performance from legacy/reset history.

## 2026-09-13 to 2026-09-14 — Court/source enrichment

- CourtSpeed/live conditions introduced as external enrichment with provenance/freshness.
- Raw court-condition metrics remain distinct from promoted model features.
- New context data does not automatically receive model weight; promotion requires validation.

## 2026-09-08 — Self-functioning production pipeline

- Canonical production direction established: refresh → forecast → repricing → official ledger → settlement → performance → UI.
- Hands-off operation, freshness contracts, fail-closed official publishing and one source of truth became production requirements.

## Maintenance rule

Add a changelog entry whenever a merged architectural change supersedes a prior design assumption. Update `CURRENT_ARCHITECTURE.md` at the same time.