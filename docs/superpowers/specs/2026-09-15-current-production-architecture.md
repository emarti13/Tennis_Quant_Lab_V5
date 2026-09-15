# Tennis Quant Lab V5 — Current Production Architecture Baseline

**Status:** Governing current-state architecture snapshot
**Effective:** 2026-09-15
**Purpose:** Prevent regression to superseded V5 behavior after the September production-pipeline, Daily Board, recommendation-ledger, schedule/context, and court-condition changes.

This document supplements `PROJECT_MANDATE.md`. If an older spec or plan describes behavior that conflicts with this snapshot, do **not** restore the older behavior merely because it appears in an earlier document. Reconcile the older document against this baseline and current production code first.

## 1. Canonical production chain

The production architecture is one auditable chain:

**source/data refresh → context warehouse → sportsbook-independent daily forecast → market repricing → official recommendation ledger → settlement → performance/results → Streamlit UI**

Hard rules:

- Do not create a second production path to work around a failure.
- Streamlit consumes canonical artifacts; page loads do not rebuild heavy upstream state.
- Forecast probabilities are frozen independently of sportsbook prices.
- Market repricing prices the frozen forecast; it does not silently rebuild or rewrite it.
- Official recommendations are immutable historical records once frozen.
- Settlement and performance consume the official ledger rather than reconstructing historical picks from current model state.

## 2. Daily Board and Decision Feed

The **Daily Forecast Board** is the full-slate analytical workspace. It must remain available with the complete daily slate and supported context controls.

The **Decision Feed** is a separate card-based view derived from the same canonical forecast/repricing pipeline. It is not a replacement for the full Daily Board.

There is **no one-bet-per-match rule**. If multiple markets on the same match independently meet the official recommendation policy, multiple top-level official recommendations are valid. Lower-tier/ancillary/review outputs must remain auditable rather than disappearing when the day rolls over.

Do not regress the product to a card-only experience or to a UI where every selection is automatically REVIEW without statistically justified policy logic.

## 3. Forecast, repricing, and recommendation immutability

The daily forecast is sportsbook-independent and must be frozen before market pricing drives recommendation decisions.

Repricing may run repeatedly as market prices change. It must:

- preserve the frozen model probability/forecast;
- compare current available prices against the frozen forecast;
- avoid duplicating already-frozen official recommendations;
- preserve recommendation-time price and model probability in the official ledger;
- never rewrite prior official recommendations because a later price or model run differs.

Duplicate actionable repricings for an already-frozen recommendation are audit events, not new official bets.

## 4. Official recommendation ledger, reset boundary, settlement, performance

The official recommendation ledger is the canonical history of promoted selections. Each official recommendation must preserve enough information to audit what was recommended at recommendation time, including the frozen model probability and available price.

The September 2026 Results Accuracy / Performance reset establishes a reporting boundary. Pre-reset recommendations remain historical/auditable but are excluded from post-reset performance reporting. Do not repopulate post-reset performance with legacy/pre-reset rows.

Settlement must update completed official recommendations from canonical results while leaving unresolved recommendations open. Performance must derive from settled post-reset official recommendations. PASS, REVIEW, ancillary, legacy, research, and diagnostic rows must not be silently mixed into official performance.

## 5. Context warehouse

The context warehouse is an upstream production artifact, not a Streamlit-page computation. The production build has demonstrated a warehouse on the order of 50,053 matches / 100,106 player-match rows; exact counts may grow as sources refresh.

The workflow publication order is now:

1. checkout;
2. synchronize/rebase with `main` while the worktree is clean;
3. build/validate generated warehouse artifacts;
4. publish generated changes.

Do **not** restore the former pattern that attempted `git pull --rebase` after generated tracked files had dirtied the worktree. That was a production automation blocker.

## 6. Schedule and tournament identity

Canonical schedule identity must distinguish real tournaments while allowing known alternate names to resolve deterministically.

Indian Wells is the same tournament identity as the **BNP Paribas Open**. `Indian Wells` and `Indian Wells Open` are accepted aliases for `BNP Paribas Open`; they must not be modeled as competing same-city tournaments.

At the same time, genuinely distinct same-city tournaments must still fail closed when matching is ambiguous. Do not solve ambiguity by broadly lowering matching safeguards.

## 7. Court conditions and court context — nonblocking enrichment

Court conditions are useful enrichment but are **not a hard dependency for production forecast availability**.

Resolution precedence is:

1. fresh CourtSpeed/live court-condition data when available;
2. canonical court/master-schedule data;
3. optional user/manual selection when available;
4. otherwise UNKNOWN / no court-condition adjustment.

Manual input is optional. Missing CourtSpeed coverage must not stop the Daily Board or baseline model.

Per-field provenance should be retained where available (for example CourtSpeed, CanonicalCourtFile, Manual, Unknown). Source health and production health are separate concepts.

Expected source-health states include:

- `READY` — current coverage is fresh;
- `PARTIAL` — some current coverage resolved;
- `NO_CURRENT_COVERAGE` — source returned no usable current-event coverage without an exceptional failure;
- `STALE_LKG` — current refresh failed and last-known-good source data is retained for source continuity.

A source being stale or uncovered does **not** automatically mean production is blocked. The resolver must degrade to canonical court data or UNKNOWN/no adjustment. Stale data must never be mislabeled fresh.

A schema-valid empty CourtSpeed response is a normal zero-coverage condition, not a reason for a `KeyError` or a cascading production failure.

## 8. Surface/environment controls

Do not invent court-condition information when unresolved. UNKNOWN means no court-condition adjustment. A generic baseline surface used elsewhere in the model must not be presented as if it were observed live court-condition evidence.

Altitude/court/master-schedule enrichment should be used where canonical data supports it, especially for 2025+ data. Missing weather is acceptable; weather remains future enrichment and must not become a manual or hard production dependency.

## 9. Automation and freshness behavior

Normal daily operation is intended to be hands-off. Production workflows should refresh canonical artifacts on their approved cadence, recover automatically when dependencies recover, and preserve last-known-good artifacts only where mathematically appropriate.

Do not replace automated source behavior with instructions for the user to upload/rebuild files every day. Do not add unnecessary repeated external calls when a valid recent artifact exists. Freshness must be explicit and auditable.

## 10. Current verification baseline

PR #29 (`fix/production-automation-blockers`) was merged to `main` on 2026-09-15 as merge commit `d56c30bf17d80239209772181905798517eec6d2`.

Before merge, head `4337d9f41b659bf8b6e9a035183a063fb8416b29` passed:

- V5 Full Regression Suite — **362 passed**;
- CourtSpeed Conditions Tests — passed;
- Streamlit App Smoke Test — passed.

This proves the merged code passed PR-level regression/smoke checks. It does **not**, by itself, prove every corrected scheduled workflow has subsequently executed successfully on `main`. Production workflow execution after the merge must still be verified before claiming those runtime blockers fully closed.

## 11. Anti-regression rules for future agents

Before changing V5 production behavior:

1. Read `PROJECT_MANDATE.md`.
2. Read this current-production baseline.
3. Read the specific domain spec/plan relevant to the change.
4. Inspect current `main` code/workflows before assuming an older plan is still the implementation target.
5. Treat older plans as historical implementation guidance when they conflict with later accepted architecture.
6. Never restore a removed/manual/duplicate path merely because an old document describes it.
7. Add or update regression tests for behavior changes.
8. Verify end-to-end production behavior before claiming completion.

When documentation conflicts, prefer the most recent **approved** architecture that is consistent with `PROJECT_MANDATE.md`, then update the stale documentation rather than implementing the stale instruction.

## 12. Current near-term production verification

After this documentation baseline, the next production-readiness work remains:

- verify the corrected Context Warehouse scheduled/manual execution on `main` publishes cleanly;
- verify CourtSpeed zero/partial/failure semantics on `main` and confirm missing live coverage does not block forecast production;
- confirm canonical production artifact freshness;
- confirm current Daily Forecast generation;
- confirm repricing consumes the current frozen forecast;
- confirm official recommendation immutability;
- confirm settlement and post-reset performance update from canonical artifacts.

Do not confuse these remaining runtime verification items with permission to redesign the architecture above.