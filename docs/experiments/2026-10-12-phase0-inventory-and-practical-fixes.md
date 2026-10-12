# Phase 0 inventory and practical fixes (2026-10-12)

Category: Production Reliability. Roadmap gate: **Gate 0** (CI green; collectors and
production running without manual work). No model, feature, or recommendation-policy
change. Nothing here touches the sealed forward period.

## 1. Season files now roll over at the new year

**Problem.** `build_v5_states.py` and `v5_results_cache.py` read hard-coded `2026*.csv`
names, and the Actions history cache key was pinned to `v5-tennis-history-2010-2025-v3`.
On 2027-01-01 the refresh would download `2027*.csv`, the state builder would skip the
missing `2026*.csv` files, and ratings and settlement would run without any 2026 matches
while still reporting `SUCCESS`.

**Fix.**

- `v5_season_files.py` (stdlib only) is the single source for which years are cached
  history (2010 through last year) and which are the current season, the file names, and
  the cache key (`v5-tennis-history-2010-<last year>-v4`).
- `bootstrap_v5_history.py` writes `.v5_history_cache/coverage.json` and rebuilds when the
  covered years change (about 70 s). It refuses to build history that skips last season.
- `refresh_tennismylife_cloud.py` has a 21-day new-season grace window. In early January it
  also downloads last season's files, so late-December results still settle, and it
  tolerates a new-season file that is not published yet. Any skipped file is recorded in
  `v5_refresh_last.json` under `missing_optional`.
- `build_v5_states.py` fails closed if a history aggregate (`ATP.csv`, `WTA.csv`, …) is
  missing instead of silently building on partial history.
- The context warehouse uses a rolling four-season window (`rolling_history_years(4)`).
- The refresh log stops copying the build stdout into every committed line (~6 KB/day → ~2.5 KB).

Verified end to end in a scratch copy: bootstrap → refresh → results cache, 13,122 MEN /
5,085 WTA rating rows, 12,345 current-season result rows. `tests/test_v5_season_rollover.py`
covers the year boundary.

The first CI run after merge rebuilds the history cache once under the new key.
TennisMyLife's yearly Challenger files now dedupe to 73,376 rows (the old cache had
73,536); that is an upstream data change, not this fix.

## 2. Workflows: fewer surprise runs and writers

- `v5_daily_predictions.yml` no longer runs on push. Its freshness check already rebuilds
  in the next scheduled window when context code changed since the forecast's source commit.
- These workflows ran (and most committed to `main`) whenever their own files changed. They
  are now `workflow_dispatch` only, as CLAUDE.md requires for heavy and research jobs:
  `audit_production_handoff`, `export_kalshi_training_dataset`,
  `extract_oddspapi_tournaments`, `oddspapi_fixture_registry_seed`,
  `oddspapi_historical_fixture_probe`, `pinnacle_2026_closing_backfill` (350-min timeout),
  `v5_apply_legacy_court_retirement` (one-shot migration), `v5_tournament_challenger`,
  `v5_calibrated_board_diagnostic`, `v5_joint_score_calibration_diagnostic`,
  `v5_context_join_keys`, `context_warehouse_history_smoke`.
- `v5_actions_budget.py` matched the real schedule poorly (4 live-market runs/day budgeted,
  1 configured; retired CourtSpeed job still counted). It now lists every cron-scheduled
  workflow in `SCHEDULED_WORKFLOWS`, and a test fails if a new schedule appears without a
  budget entry. Projected recurring use: about 1,690 of 3,000 minutes/month. Observed: about
  300 wall-clock minutes from 2026-10-04 to 2026-10-12.

## 3. The 21 pre-existing test failures

| Group | Tests | Resolution |
|---|---|---|
| Real bug | 2 official-settlement tests | `v5_official_performance._clean` called `.fillna` on a scalar when an optional column was missing. Fixed; output on the real ledger is byte-identical. |
| Workflow drift | 2 Actions-budget tests, 1 market-feed test | Fixed by section 2. |
| Broken test | daily-batch cold start | Referenced a non-existent class and an event the authority correctly refuses. |
| Retired surface fallback | 4 surface-fallback tests, 1 UI unification test | Rewritten to assert fail-closed (surface only from `tournament_authority`). |
| Authority naming | Sao Paulo schedule test, city-alias test | Schedule context retries with the authority's official name; the alias test accepts either location-based match method. |
| UI copy | 2 performance-page tests | Updated to the current customer wording (same contract). |
| Retired court conditions | 6 tests | Removed. They asserted CourtSpeed/CPI behavior that `retire_legacy_court_paths.py` removed; `tests/test_v5_legacy_court_retirement.py` guards the retirement. |

Removed court tests: `test_live_target_uses_canonical_courtspeed_snapshot_without_network`,
`test_raw_cpi_never_becomes_internal_court_speed_override_implicitly`,
`test_full_context_runtime_uses_adapter_not_web_calls`,
`test_cpi_is_kept_separate_from_internal_court_speed_state`,
`test_refresh_workflow_is_daily_manual_and_does_not_touch_oddspapi`,
`test_enrichment_builds_historical_prior_court_speed_before_target_match`.

Result: `python -m pytest tests -q` → 421 passed locally (was 397 passed, 21 failed).

## 4. Open findings (not changed; need a decision)

1. **Committed context warehouse is stale.** `context_warehouse/*.parquet` was built from
   the 2026-09-21 results snapshot, and the Streamlit interactive path reads it.
   `v5_context_warehouse.yml` is meant to rebuild on each results commit, but pushes made
   with the default `GITHUB_TOKEN` never trigger other workflows, so it has not run. The
   daily forecast builds its own fresh warehouse on the runner, so the frozen forecast and
   the interactive page can use different context. Options: (a) have the daily forecast
   commit the warehouse it used (one source; about 6 MB of binary added to git per day),
   (b) publish it as a release asset or Actions artifact the app downloads, or (c) drop the
   interactive rebuild path and show only the frozen forecast.
2. **Repository size.** `.git` is 1.4 GB, mostly `oddspapi_history/chunks/*.jsonl.gz` and
   daily CSV ledgers. Long term, raw snapshot archives belong outside git (release assets
   or a free bucket); the append-only ledgers stay.
3. **CLAUDE.md references code not on `main` yet.** `v5_fatigue_features.py`,
   `v5_model_guard.py` and the `v5_fatigue_features.yml` check live in PR #36
   (`repair/fatigue-v1-safety-layer`), which is still open.
