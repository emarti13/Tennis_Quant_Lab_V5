# Tennis Quant Lab V5 — Current State / Resume Here

**Updated:** 2026-09-15

This is the short operational handoff for any agent resuming V5 work. It is intentionally current-state focused. Read it after `PROJECT_MANDATE.md` and `specs/2026-09-15-current-production-architecture.md`.

## Production architecture now

Canonical chain:

**refreshes → context warehouse → frozen daily forecast → market repricing → official recommendation ledger → settlement → post-reset performance/results → UI**

UI architecture:

- **Daily Forecast Board:** complete daily slate / analytical workspace.
- **Decision Feed:** separate card-based strongest-selection view.
- Do not replace one with the other.
- Multiple official recommendations can exist on the same match when each market independently qualifies.

Recommendation architecture:

- forecast is sportsbook-independent and frozen;
- repricing can rerun as odds change;
- recommendation-time price/probability are frozen in the official ledger;
- later repricing cannot rewrite official history;
- ancillary/review output remains auditable;
- post-reset performance excludes pre-reset recommendations.

Context/court architecture:

- context warehouse is upstream and canonical;
- CourtSpeed is enrichment, not a production hard dependency;
- resolution: fresh CourtSpeed → canonical court/master schedule → optional manual → UNKNOWN/no adjustment;
- source health is separate from production readiness;
- valid zero CourtSpeed coverage must not crash production;
- Indian Wells / Indian Wells Open are aliases of BNP Paribas Open, while true ambiguity still fails closed.

## Latest merged milestone

PR #29 merged to `main` on 2026-09-15.

Merge commit: `d56c30bf17d80239209772181905798517eec6d2`

PR head verification before merge:

- V5 Full Regression Suite: 362 passed;
- CourtSpeed Conditions Tests: passed;
- Streamlit App Smoke Test: passed.

Included fixes:

- context-warehouse publication order (sync clean checkout before generation; no rebase after dirtying tracked artifacts);
- CourtSpeed schema-safe empty responses;
- nonblocking canonical court-file fallback;
- safer schedule ambiguity behavior;
- deterministic Indian Wells aliases;
- regression coverage for court resolution and tournament identity.

## Do not regress to these superseded behaviors

- card-only Today experience;
- removal of the full Daily Board;
- one-bet-per-match assumption;
- treating all selections as REVIEW without policy evidence;
- rebuilding model/context in Streamlit page loads;
- repricing that changes frozen model predictions;
- mutable historical official recommendations;
- performance that mixes pre-reset/legacy recommendations into the current reporting period;
- mandatory manual court-condition entry;
- CourtSpeed outage/zero coverage blocking the baseline forecast;
- defaulting unknown live court conditions to invented observed conditions;
- duplicate Indian Wells tournament identities;
- `git pull --rebase` after context generation dirties the workflow worktree;
- claiming a scheduled-production fix complete based only on PR CI.

## Next verification gate

Do not redesign before checking these on current `main`:

1. Context Warehouse workflow actually runs and publishes correctly after PR #29.
2. CourtSpeed refresh produces correct READY/PARTIAL/NO_CURRENT_COVERAGE/STALE_LKG semantics and remains nonblocking.
3. Canonical production artifacts are fresh enough for current production.
4. Daily forecast is current and generated from canonical upstream artifacts.
5. Repricing is current and consumes the frozen forecast.
6. Official ledger remains immutable with no duplicate actionable recommendations.
7. Completed recommendations settle from canonical results.
8. Post-reset Results/Performance reflect only eligible settled official recommendations.

Only after those checks should the next production-readiness conclusion be made.