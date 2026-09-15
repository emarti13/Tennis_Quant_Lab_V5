# 2026-09-15 Current Production Architecture — Supersession Spec

**Status:** Approved-current documentation consolidation.  
**Governing references:** `PROJECT_MANDATE.md`, `docs/superpowers/CURRENT_ARCHITECTURE.md`.

## Purpose

This spec records the architecture that must be preserved after the September production-pipeline, Daily Board/Decision Feed, official recommendation, context, CourtSpeed and automation changes. It is intentionally concise and points to the current-state contract rather than rewriting every historical plan.

## Required architecture

Production is one canonical chain:

`refresh → context/model artifacts → frozen daily forecast → market repricing → immutable official recommendation ledger → automatic settlement → performance → UI`.

The full Daily Forecast Board and card-based Decision Feed coexist. The feed is a filtered decision surface over the same canonical production state and must not replace the full board. Multiple official markets may be promoted for one match when each independently satisfies the approved policy. Ancillary/non-official candidates remain auditable.

The model forecast is sportsbook-independent. Market pricing is downstream. Repricing cannot rewrite the frozen forecast or an existing official recommendation.

The official recommendation ledger is the audit source for settlement and performance. Historical official recommendations are immutable except for attaching settlement/result fields. Post-reset official performance is separated from pre-reset/legacy/research rows.

Court conditions are nonblocking enrichment. Resolution order is fresh CourtSpeed → canonical court/master schedule → optional manual override → approved fallback → unknown/no condition adjustment. Missing live court coverage is not permission to invent conditions and is not by itself permission to stop the Daily Board. Freshness and provenance must be explicit.

Context warehouse publication synchronizes the branch before generated files are built. A dirty-worktree rebase after generation is prohibited.

## Supersession rule

Any older spec or plan that implies one of the following is superseded:

- card-only UI replacing the full Daily Board;
- exactly one official bet per match;
- repricing mutating historical official picks;
- CourtSpeed as a mandatory hard dependency for forecast generation;
- manual court input as a required daily step;
- silent Hard/court-condition invention solely to avoid missing context;
- duplicate Indian Wells/BNP Paribas same-tour tournament identities;
- post-build `git pull --rebase` in the context warehouse publication workflow;
- Streamlit page loads performing heavy upstream production rebuilds;
- reactive model tuning based on recent individual outcomes.

## Verification baseline

PR #29 merged to `main` as `d56c30bf17d80239209772181905798517eec6d2`. Its pre-merge head passed the full regression suite (362 tests), CourtSpeed Conditions Tests and Streamlit App Smoke Test.

This is the regression baseline, not a substitute for verifying scheduled production runs and artifact freshness after merge.

## Maintenance

Whenever a future approved change modifies the production architecture, update `docs/superpowers/CURRENT_ARCHITECTURE.md` in the same PR. A change that alters architecture without updating the current-state contract is documentation-incomplete.