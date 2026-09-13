# V5 Self-Functioning Production Pipeline Design

## Goal

Make Tennis Quant Lab V5 operate as a durable production system under a hard GitHub Actions budget of 3,000 minutes per month while preserving live market freshness, immutable prediction records, and statistically honest performance reporting.

## Production cadence

### Heavy model work — once daily
- Refresh player data and ratings.
- Rebuild context/state features.
- Run the full accepted production winner and score models.
- Freeze sportsbook-independent match probabilities and score distributions for the day's eligible fixtures.
- Full-model outputs are immutable for the day unless an explicit manual recovery run is invoked.

### Lightweight market work — once daily for the time being
- Pull fresh OddsPapi fixtures and sportsbook prices once daily while operating under the current API quota constraint.
- Normalize market rows.
- Join current prices to the day's already-frozen model outputs.
- Recompute only price-dependent values: implied/no-vig market probability, edge, EV, and BET/LEAN/REVIEW/PASS policy state.
- Do not rebuild ratings, context warehouse, simulations, or production model probabilities during routine repricing.
- This is a temporary quota-conservation cadence; increase market refresh frequency only when API capacity supports it without compromising hands-off production reliability.

### Settlement — once daily
- Settle official frozen recommendations against completed match results.
- Regenerate market-level and fixture-cluster-adjusted performance artifacts.
- Preserve original forecast, first actionable price, model version, policy version, and recommendation timestamp.

### Historical/research work — isolated and low cadence
- Historical OddsPapi backfill runs only a few times per week.
- Acceptance experiments and full-regression suites run on relevant code/model changes, not on every data refresh.
- Historical work must never share a concurrency group with the production market feed.

## Artifact contract

### Daily model forecast ledger
One sportsbook-independent forecast per fixture/model version/day. Required identity fields include:
- fixture_id
- forecast_date
- model_version
- winner_candidate
- score_candidate
- player orientation
- win probabilities
- expected margin/total or score-distribution outputs
- context quality/state fields
- generated_at_utc

This ledger is not duplicated when prices refresh.

### Market snapshot history
Each live OddsPapi pull may append a price observation identified by snapshot time, fixture, market family, selection, and line. Multiple observations are expected and are diagnostic/history data only.

### Official recommendation ledger
A market recommendation is uniquely identified by a stable market key:
`fixture_id + market_group + normalized_selection + normalized_line`.

Policy:
- PASS/REVIEW observations do not create official recommendation records.
- The first transition into BET creates the official actionable BET record for that market key.
- If a market never reaches BET but reaches LEAN, the first LEAN may create an official LEAN record unless a later BET supersedes it before match start; supersession must preserve the original LEAN audit history but only one official settlement row is counted for headline recommendation performance.
- Once an official BET is frozen, later price pulls do not create additional bets or additional win/loss records for that same market key.
- Later prices may update the live UI and market-history table but cannot mutate the frozen official recommendation price, timestamp, model probability, or result record.
- No official recommendation may be created after match start.

## Performance integrity

Headline performance must not count price refreshes as independent bets.

Report separately:
1. current-engine official BET/LEAN recommendations;
2. legacy official recommendations;
3. all market observations for audit only;
4. fixture-cluster-adjusted results where correlated recommendations from one match are treated as one evidence cluster.

Required live metrics include:
- official recommendations
- unique fixtures
- W-L-P
- hit rate
- units / ROI
- median American odds
- favorite/underdog mix
- performance by price band
- maximum recommendations per fixture
- retirement/injury sensitivity view when result metadata permits.

## Reliability and last-known-good behavior

Every production stage writes a compact status artifact containing:
- stage name
- run timestamp
- source artifact timestamp/version
- success/failure state
- row/fixture counts
- freshness state
- error summary if applicable.

Canonical production artifacts follow last-known-good promotion:
- build new output in a temporary/staging location;
- validate schema, non-empty/future-fixture expectations where applicable, and freshness;
- only then replace the canonical artifact;
- failed refreshes never overwrite a valid canonical artifact with empty or partial output.

Market-feed state is explicitly one of:
- READY
- STALE_PRICES
- NO_FUTURE_FIXTURES
- MISSING

STALE_PRICES may preserve fixture visibility but must block BET/LEAN generation from stale sportsbook prices.

## Actions-minute budget constraint

The architecture must target comfortably below 3,000 GitHub-hosted Actions minutes/month.

Budget principles:
- one lightweight market job/day for the time being under the current OddsPapi quota constraint;
- one heavy model job/day;
- one settlement job/day;
- one ratings/data refresh folded into the heavy daily model job where practical;
- historical backfill limited to a few runs/week;
- no full repository regression on routine data refreshes;
- full regression and Streamlit smoke run only on relevant code/model changes and merge verification;
- avoid duplicate workflow triggers caused by both file pushes and workflow_run for the same event.

A monthly budget report should be maintainable from configured workflow frequencies and observed average durations. If projected usage approaches 80% of the 3,000-minute allowance, non-production scheduled work should be reduced before production refreshes are affected.

## Production priority

Priority order:
1. live market refresh and lightweight repricing;
2. daily accepted-model forecast generation;
3. settlement/performance;
4. player-data maintenance;
5. historical backfill/research.

Lower-priority workflows must never cancel, block, or consume concurrency reserved for higher-priority production work.

## UI behavior

Today reads the canonical daily forecast plus the latest valid live pricing/repricing artifact.
- Fresh prices: show current recommendations.
- Stale prices: show fixture/model information with a stale-price warning and no actionable BET/LEAN from stale prices.
- Missing feed: show a true missing-feed state.
- No future fixtures: show a deliberate no-upcoming-fixtures state.

The UI must never infer that a stale feed is missing and must never create recommendation records itself.

## Testing contract

Required automated contracts include:
- stale feed != missing feed;
- stale odds cannot produce BET/LEAN;
- repeated price pulls do not create duplicate official bets;
- first BET crossing freezes exactly one official recommendation;
- later price changes cannot mutate the frozen official recommendation;
- daily model probabilities are unchanged across same-day repricing runs;
- no recommendation after match start;
- failed artifact build cannot overwrite last-known-good canonical output;
- performance headline excludes PASS/REVIEW and duplicate snapshots;
- fixture-cluster metrics remain distinct from raw market metrics;
- workflow trigger tests prevent duplicate fan-out;
- recurring workflow cadence remains within the 3,000-minute design constraint and configured API quota.

## Non-goals

- Do not change the accepted probability-model mathematics as part of this architecture work.
- Do not tune recommendation thresholds using already-observed live outcomes during this refactor.
- Do not rewrite historical frozen predictions.
- Do not make stale sportsbook prices appear actionable simply to keep the page populated.
