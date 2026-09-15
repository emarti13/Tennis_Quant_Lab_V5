# Tennis Quant Lab V5 — Current Architecture and Anti-Regression Contract

**As of:** 2026-09-15  
**Status:** Governing current-state reference. Read this after `PROJECT_MANDATE.md` and before older dated specs/plans.

This document exists to prevent a future engineering agent from reconstructing an older V5 architecture from historical plans. Dated specs and plans remain useful history, but where they describe a superseded implementation, **this current-state contract wins unless a newer approved document explicitly replaces it**.

## 1. Governing production chain

V5 is one production system:

**source/data refresh → canonical context/model artifacts → sportsbook-independent daily forecast → live market repricing → official recommendation ledger → automatic settlement → Results/Performance → UI**

Do not create parallel production paths, rebuild heavy upstream state inside Streamlit, or substitute an older local workflow because it is easier to run.

## 2. Daily Board and Decision Feed

The product has two complementary views, not competing versions of the app.

- **Daily Forecast Board:** full daily slate, full model/market information, context visibility and approved adjustment controls.
- **Decision Feed:** card-based view of the strongest actionable selections derived from the same canonical board/repricing state.
- The Decision Feed must not replace or shrink the full Daily Board.
- There is **no one-bet-per-match rule**. If ML, spread and/or total independently satisfy the approved recommendation policy, multiple official selections from one match are allowed.
- Non-official/ancillary REVIEW/PASS candidates remain auditable; they must not silently disappear merely because the day rolls over.
- Model probability/fair price and market/implied price remain visibly distinct.

## 3. Forecast and market separation

The model forecast is sportsbook-independent and frozen before market selection. Market prices are attached downstream during repricing.

Never train or reconstruct an official forecast from the price later used to judge its edge. Repricing may change current market opportunity, but it must not rewrite the frozen model forecast or historical official recommendation.

## 4. Official recommendation ledger

The official ledger is the immutable audit record of promoted recommendations.

For each official recommendation preserve, at minimum, the recommendation identity, fixture/match identity, market/selection, frozen model probability/fair price, accepted recommendation-time market price, recommendation timestamp/policy state, eventual result and settlement provenance.

Later repricing must not mutate an already frozen official recommendation. Duplicate actionable repricings are ignored/audited rather than creating duplicate official bets.

Results/Performance must distinguish official post-reset recommendations from legacy/pre-reset/research/diagnostic rows.

## 5. Settlement and performance

Completed official recommendations settle automatically from canonical result data. Settlement must preserve the frozen recommendation terms and attach result, score/source, units and settlement timestamp without rewriting the original recommendation.

Performance is calculated from the settled official ledger, not reconstructed ad hoc from the current board. Correlated same-match recommendations must remain identifiable for analysis.

## 6. Court, surface and environmental context

Court conditions are **enrichment, not a hard dependency that is allowed to stop the Daily Board**.

Current resolution precedence is:

1. Fresh CourtSpeed/live court-condition source when a trustworthy current match exists.
2. Canonical court/master-schedule context.
3. Optional user/manual override when explicitly supplied.
4. Existing approved V5 fallback context where applicable.
5. Otherwise `UNKNOWN` / no court-condition adjustment.

Rules:

- Missing CourtSpeed coverage must not crash or block production.
- Do not invent a court condition to make the pipeline run.
- Record provenance per field/source where available (`CourtSpeed`, canonical court file/schedule, manual, fallback, unknown).
- Source health and production readiness are separate concepts.
- Supported source-health states include `READY`, `PARTIAL`, `NO_CURRENT_COVERAGE`, and `STALE_LKG` as appropriate.
- `STALE_LKG` must never masquerade as fresh.
- A schema-valid zero-row current CourtSpeed response is a coverage condition, not automatically an exception.
- Canonical schedule matching fails closed on genuine ambiguity.
- `Indian Wells` and `Indian Wells Open` are accepted aliases of the canonical `BNP Paribas Open` tournament identity; do not recreate them as competing same-tour tournament identities.

Weather is not currently a required production input. Future weather enrichment must earn inclusion without making ordinary forecast generation dependent on unavailable granular weather data.

## 7. Context warehouse

The context warehouse is a generated canonical upstream artifact. Its scheduled workflow must synchronize/rebase **before** generating tracked outputs. Never perform `git pull --rebase` after the build has dirtied the worktree.

Publication order is therefore:

**checkout → synchronize with main → build/test/verify canonical artifacts → publish generated changes**.

A successful build that fails publication is not a successful production refresh.

## 8. Production readiness and degradation

Each stage must expose freshness/health clearly. Optional enrichment failure may degrade to explicit unknown/LKG behavior where mathematically safe. Required stale inputs beyond their approved window must fail closed for official recommendations rather than silently publishing misleading picks.

The UI loading is not proof that production is healthy. Readiness requires canonical artifacts to be fresh enough and the complete downstream path to consume them correctly.

## 9. Model-change rule

Do not change model weights, calibration, thresholds, favorite/underdog treatment, totals/spreads behavior, or recommendation policy in response to a small recent sample or a memorable match.

Model/policy changes require chronological out-of-sample evidence and appropriate calibration/performance validation. Context fields becoming available does not mean they automatically receive predictive weight; candidate features must earn promotion.

## 10. Current verification baseline

PR #29 (`Fix production automation blockers`) was merged to `main` on 2026-09-15 as merge commit `d56c30bf17d80239209772181905798517eec6d2`.

Immediately before merge, its head `4337d9f41b659bf8b6e9a035183a063fb8416b29` passed:

- V5 Full Regression Suite: **362 passed**.
- CourtSpeed Conditions Tests: **passed**.
- Streamlit App Smoke Test: **passed**.

This verifies the code/PR regression baseline. It does **not by itself prove** post-merge scheduled production publication/freshness; production workflow runs and canonical artifacts must still be inspected when claiming operational readiness.

## 11. Anti-regression rules for future agents

Before modifying V5:

1. Read `PROJECT_MANDATE.md`.
2. Read this file completely.
3. Read the relevant current specs/plans for the subsystem.
4. Inspect current production code and artifacts before assuming a dated plan is still the implementation.
5. Never restore an older UI, model path, recommendation contract, court dependency, or workflow merely because an older document describes it.
6. Treat historical plans as implementation history unless they agree with this current-state contract.
7. Update this file whenever a merged architectural change supersedes any statement here.
8. Do not call a production change complete until CI and the relevant end-to-end production path are verified.

## 12. Current target

The target remains:

**hands-off daily operation + one auditable production truth + durable out-of-sample edge + automatic settlement/performance + sellable customer-facing MVP**.
