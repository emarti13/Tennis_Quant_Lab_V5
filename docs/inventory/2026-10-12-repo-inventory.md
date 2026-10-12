# Repository inventory (2026-10-12)

Facts only. The plan that acts on this is
`docs/superpowers/plans/2026-10-12-ground-up-rebuild-plan.md`.

## Method

- **Code:** a static import graph of all 134 Python modules, built with `ast`, plus
  file-name references such as `subprocess` calls to `build_v5_states.py`. Entry points
  are the scheduled production workflows, `v5_context_warehouse.yml`, the Streamlit app
  (`tennis_quant_app_v5.py`, `pages/`) and every manual workflow. Nothing in the repo
  uses `importlib` or `__import__`, so the graph is complete.
- **Classes:**
  - **PROD:** reachable from a scheduled production workflow.
  - **APP:** reachable from the Streamlit app.
  - **PROD+APP:** both.
  - **MANUAL:** only reachable from `workflow_dispatch` workflows.
  - **TEST-ONLY:** imported only by tests.
  - **ORPHAN:** nothing references it.
- **Data:** every tracked non-code file, matched by file name against code and workflows.
- **Live check:** the app was launched in a scratch copy and every page was driven with
  Playwright (2026-10-12, about 19:20 UTC).

## 1. How production actually runs

| Time (UTC) | Workflow | What it does |
|---|---|---|
| 00:02 | `oddspapi_normalized_daily_v2.yml` | Pull OddsPapi odds (quota-aware), normalize, build `v5_market_ready/`, reprice against the frozen forecast, commit, then dispatch the daily forecast |
| 06:00 / 10:00 / 14:00 | `v5_player_ratings_refresh.yml` | Bootstrap history cache, download current-season TennisMyLife files, rebuild ratings (`build_v5_states.py`), build results cache, commit. Later windows skip if fresh |
| 06:45 / 10:45 / 14:45, plus dispatch | `v5_daily_predictions.yml` | Build context warehouse on the runner, `v5_daily_batch.py` → policy postprocess → forecast artifacts → repricing; commit `v5_daily_ready/` |
| 15:30 | `v5_automatic_settlement.yml` | Settle official recommendations from the results cache; write performance |
| (never fires) | `v5_context_warehouse.yml` | Meant to rebuild and commit `context_warehouse/*.parquet` on each results commit. Bot pushes do not trigger workflows, so the committed warehouse dates from the 2026-09-21 results snapshot |

The app reads `v5_daily_ready/latest_repriced_board.csv`, `official_recommendations.csv`,
performance JSON and the market files. Its override run (`RUN ADJUSTED DAILY BOARD`)
reprices through `v5_interactive_production.py` using the **committed** warehouse.

## 2. What the live app showed (2026-10-12)

- Every page renders with no exceptions.
- For a traced fixture (Tjen vs Ito), the app shows exactly the frozen forecast
  (0.603804 → 60.4%) and the three official recommendations in the ledger.
- The Daily Board says **LIVE/ACTIONABLE** while 89 of its 104 fixtures had already
  started and the price snapshot was 15 h old (the freshness limit is 24 h, and the
  started fixtures are not filtered from the board). The Decision Feed shows "Markets Live: 0".
- The override run with **no edits** differed from the frozen forecast by 6.1 points on
  average and up to 42.4 points (Hurkacz vs Davidovich Fokina: frozen 93.2%, override run
  50.8%, market 51.9%). Both are labeled the same model.
- The frozen 93.2% for that fixture became two official BETs (ML −115 at EV +74%; −1.5 at
  +115 at EV +94%). Its model components range over 39 points.
- Model Health's "Full regression: Success" comes from a static file
  (`experiments/acceptance/full_regression_status.json`, 183 tests passed) that nothing updates.
- The board's displayed surface is overwritten at read time by the master schedule
  (`v5_ui_production.py` → `enrich_daily_board_context(year=2026)`), a second surface source
  next to the tournament authority used by the forecast.

## 3. Structural findings

1. **Duplicate implementations of the same job:**
   - Context warehouse builder: `build_v5_context_warehouse.py` (live) vs
     `build_context_warehouse.py` + `context_warehouse/`.
   - Schedule resolver: `v5_master_schedule_context` (app) vs `v5_schedule_context`.
   - Weather: `v5_weather_features` (live) vs `v5_weather_context`.
   - Ensemble/residual: inside `v5_advanced_model` (live) vs `v5_ensemble`, `v5_residual_model`.
2. **Four tournament identity sources:**
   - `context_registry/tournament_authority.csv` (`v5_tournament_authority`)
   - `tennis_master_schedule.csv` (`v5_master_schedule_context`)
   - `v5_tournament_registry`
   - `v5_tournament_context_registry`
3. **Two pricing paths:** the daily batch and the app override run build inputs separately.
4. **Leaky features in production:** `v5_workload_features` is on the live path (PROD+APP).
5. **Hard-coded years on live paths:** 29 lines, including `year=2026` defaults in schedule
   context, `years=(2025, 2026)` in the weather cache, and a fixed 2026 week in
   `v5_canonical_schedule`. Some are model-version metadata and are fine.
6. **Repository size:** `.git` is 1.45 GB; `oddspapi_history/chunks/` is 1.46 GB of it.
7. **Retired code still present:** CourtSpeed/court-conditions modules, `data/court_conditions/`,
   two echo-only workflows, the one-shot `retire_legacy_court_paths.py`, and a stray
   `context_registry/tournament_authority.csv.csv`.
8. **Open PRs:**
   - #36: fatigue_v1 + model guard; CLAUDE.md already depends on it.
   - #28, #30, #31, #32: September; predate the roadmap.
   - About 45 other remote branches.

## 4. Modules

| Class | Module | Lines | Test files | Proposed action |
|---|---|---:|---:|---|
| PROD+APP | `build_v5_context_matchups.py` | 171 | 4 | Keep (live path); review in its rebuild step |
| PROD+APP | `build_v5_weather_cache.py` | 179 | 1 | Keep (live path); review in its rebuild step |
| PROD+APP | `v5_advanced_model.py` | 192 | 1 | Keep (live path); review in its rebuild step |
| PROD+APP | `v5_context_model.py` | 273 | 1 | Keep (live path); review in its rebuild step |
| PROD+APP | `v5_core.py` | 265 | 3 | Keep (live path); review in its rebuild step |
| PROD+APP | `v5_daily_batch.py` | 729 | 4 | Keep (live path); review in its rebuild step |
| PROD+APP | `v5_full_context_live.py` | 281 | 4 | Keep (live path); review in its rebuild step |
| PROD+APP | `v5_live_market.py` | 258 | 3 | Keep (live path); review in its rebuild step |
| PROD+APP | `v5_matchup_features.py` | 163 | 1 | Keep (live path); review in its rebuild step |
| PROD+APP | `v5_model_calibration.py` | 99 | 1 | Keep (live path); review in its rebuild step |
| PROD+APP | `v5_player_identity.py` | 66 | 1 | Keep (live path); review in its rebuild step |
| PROD+APP | `v5_player_state.py` | 183 | 1 | Keep (live path); review in its rebuild step |
| PROD+APP | `v5_results_cache.py` | 127 | 2 | Keep (live path); review in its rebuild step |
| PROD+APP | `v5_results_reset.py` | 40 | 1 | Keep (live path); review in its rebuild step |
| PROD+APP | `v5_rolling_stats.py` | 129 | 1 | Keep (live path); review in its rebuild step |
| PROD+APP | `v5_score_distribution.py` | 132 | 3 | Keep (live path); review in its rebuild step |
| PROD+APP | `v5_score_walkforward.py` | 143 | 1 | Keep (live path); review in its rebuild step |
| PROD+APP | `v5_season_files.py` | 91 | 2 | Keep (live path); review in its rebuild step |
| PROD+APP | `v5_settlement.py` | 237 | 5 | Keep (live path); review in its rebuild step |
| PROD+APP | `v5_strength_conditioning.py` | 62 | 1 | Keep (live path); review in its rebuild step |
| PROD+APP | `v5_tournament_authority.py` | 265 | 1 | Keep (live path); review in its rebuild step |
| PROD+APP | `v5_tournament_registry.py` | 186 | 1 | Review (one of four tournament identity sources) |
| PROD+APP | `v5_travel_features.py` | 170 | 1 | Keep (live path); review in its rebuild step |
| PROD+APP | `v5_venue_metadata.py` | 186 | 1 | Keep (live path); review in its rebuild step |
| PROD+APP | `v5_weather_features.py` | 337 | 3 | Keep (live path); review in its rebuild step |
| PROD+APP | `v5_workload_features.py` | 226 | 1 | Replace (leaky; roadmap Phase 0 retires it) |
| PROD | `bootstrap_v5_history.py` | 218 | 1 | Keep (live path); review in its rebuild step |
| PROD | `build_v5_context_warehouse.py` | 271 | 3 | Keep (live path); review in its rebuild step |
| PROD | `build_v5_market_board_input.py` | 103 | 0 | Keep (live path); review in its rebuild step |
| PROD | `build_v5_states.py` | 488 | 1 | Keep (live path); review in its rebuild step |
| PROD | `fetch_oddspapi_markets.py` | 19 | 0 | Keep (live path); review in its rebuild step |
| PROD | `normalize_oddspapi_snapshot.py` | 222 | 0 | Keep (live path); review in its rebuild step |
| PROD | `oddspapi_client.py` | 71 | 1 | Keep (live path); review in its rebuild step |
| PROD | `oddspapi_fixture_registry.py` | 245 | 1 | Keep (live path); review in its rebuild step |
| PROD | `pull_oddspapi_quota_aware.py` | 214 | 1 | Keep (live path); review in its rebuild step |
| PROD | `refresh_tennismylife_cloud.py` | 415 | 2 | Keep (live path); review in its rebuild step |
| PROD | `v5_build_daily_forecast_artifacts.py` | 118 | 0 | Keep (live path); review in its rebuild step |
| PROD | `v5_context_schema.py` | 23 | 0 | Keep (live path); review in its rebuild step |
| PROD | `v5_daily_forecast.py` | 83 | 1 | Keep (live path); review in its rebuild step |
| PROD | `v5_daily_policy_postprocess.py` | 79 | 2 | Keep (live path); review in its rebuild step |
| PROD | `v5_forecast_context.py` | 122 | 1 | Keep (live path); review in its rebuild step |
| PROD | `v5_history_freshness.py` | 78 | 1 | Keep (live path); review in its rebuild step |
| PROD | `v5_market_feed.py` | 72 | 0 | Keep (live path); review in its rebuild step |
| PROD | `v5_official_performance.py` | 157 | 2 | Keep (live path); review in its rebuild step |
| PROD | `v5_production_artifacts.py` | 110 | 1 | Keep (live path); review in its rebuild step |
| PROD | `v5_production_policy.py` | 55 | 1 | Keep (live path); review in its rebuild step |
| PROD | `v5_recommendation_ledger.py` | 127 | 3 | Keep (live path); review in its rebuild step |
| PROD | `v5_recommendation_policy.py` | 51 | 1 | Keep (live path); review in its rebuild step |
| PROD | `v5_reprice_markets.py` | 60 | 3 | Keep (live path); review in its rebuild step |
| PROD | `v5_run_repricing.py` | 84 | 1 | Keep (live path); review in its rebuild step |
| PROD | `v5_settle_official_recommendations.py` | 147 | 2 | Keep (live path); review in its rebuild step |
| APP | `pages/3_Results_Accuracy.py` | 10 | 0 | Keep (live path); review in its rebuild step |
| APP | `results_accuracy_page.py` | 303 | 2 | Keep (live path); review in its rebuild step |
| APP | `tennis_quant_app_v5.py` | 1932 | 4 | Keep (live path); review in its rebuild step |
| APP | `v5_active_board.py` | 45 | 1 | Keep (live path); review in its rebuild step |
| APP | `v5_canonical_schedule.py` | 116 | 1 | Review (hard-coded 2026 week) |
| APP | `v5_context_transaction.py` | 101 | 1 | Keep (live path); review in its rebuild step |
| APP | `v5_fixture_accuracy.py` | 164 | 1 | Keep (live path); review in its rebuild step |
| APP | `v5_interactive_production.py` | 312 | 4 | Rebuild: override run must call the same pricing function as the daily batch |
| APP | `v5_master_schedule_context.py` | 123 | 1 | Merge into tournament authority (second surface source in the app) |
| APP | `v5_signal_tracking.py` | 79 | 1 | Keep (live path); review in its rebuild step |
| APP | `v5_tournament_context_registry.py` | 75 | 1 | Review (one of four tournament identity sources) |
| APP | `v5_ui_all_markets.py` | 119 | 2 | Keep (live path); review in its rebuild step |
| APP | `v5_ui_daily_board.py` | 192 | 1 | Keep (live path); review in its rebuild step |
| APP | `v5_ui_health.py` | 185 | 2 | Keep (live path); review in its rebuild step |
| APP | `v5_ui_host.py` | 105 | 6 | Keep (live path); review in its rebuild step |
| APP | `v5_ui_match_detail.py` | 204 | 2 | Keep (live path); review in its rebuild step |
| APP | `v5_ui_navigation.py` | 29 | 1 | Keep (live path); review in its rebuild step |
| APP | `v5_ui_performance.py` | 249 | 3 | Keep (live path); review in its rebuild step |
| APP | `v5_ui_production.py` | 121 | 2 | Keep (live path); review in its rebuild step |
| APP | `v5_ui_theme.py` | 221 | 1 | Keep (live path); review in its rebuild step |
| APP | `v5_ui_today.py` | 474 | 3 | Keep (live path); review in its rebuild step |
| MANUAL | `backfill_oddspapi_2026.py` | 317 | 1 | Keep as manual tool (data collection / research); review |
| MANUAL | `build_context_warehouse.py` | 106 | 2 | Delete (duplicate warehouse builder) |
| MANUAL | `build_v5_venue_registry.py` | 48 | 1 | Keep as manual tool (data collection / research); review |
| MANUAL | `context_warehouse/io.py` | 62 | 1 | Delete (duplicate warehouse builder) |
| MANUAL | `context_warehouse/normalize.py` | 202 | 1 | Delete (duplicate warehouse builder) |
| MANUAL | `diagnose_calibrated_live_board.py` | 159 | 0 | Delete or move to research/ (manual diagnostic) |
| MANUAL | `diagnose_context_join_keys.py` | 73 | 0 | Delete or move to research/ (manual diagnostic) |
| MANUAL | `diagnose_fixture_result_fields.py` | 65 | 0 | Delete or move to research/ (manual diagnostic) |
| MANUAL | `diagnose_joint_score_distribution_calibration.py` | 151 | 0 | Delete or move to research/ (manual diagnostic) |
| MANUAL | `diagnose_margin_calibration.py` | 170 | 0 | Delete or move to research/ (manual diagnostic) |
| MANUAL | `diagnose_market_feed.py` | 20 | 0 | Delete or move to research/ (manual diagnostic) |
| MANUAL | `diagnose_slam_market_ranges.py` | 61 | 0 | Delete or move to research/ (manual diagnostic) |
| MANUAL | `diagnose_state_variation_effect.py` | 222 | 0 | Delete or move to research/ (manual diagnostic) |
| MANUAL | `diagnose_total_length_calibration.py` | 159 | 0 | Delete or move to research/ (manual diagnostic) |
| MANUAL | `diagnose_v5_advanced_model.py` | 236 | 0 | Delete or move to research/ (manual diagnostic) |
| MANUAL | `diagnose_v5_context_model.py` | 168 | 1 | Delete or move to research/ (manual diagnostic) |
| MANUAL | `diagnose_v5_score_architecture.py` | 233 | 0 | Delete or move to research/ (manual diagnostic) |
| MANUAL | `diagnose_v5_score_distribution.py` | 216 | 1 | Delete or move to research/ (manual diagnostic) |
| MANUAL | `diagnose_v5_selection_bias.py` | 255 | 0 | Delete or move to research/ (manual diagnostic) |
| MANUAL | `diagnose_v5_settled_performance.py` | 178 | 2 | Delete or move to research/ (manual diagnostic) |
| MANUAL | `diagnose_v5_tournament_authority.py` | 12 | 0 | Delete or move to research/ (manual diagnostic) |
| MANUAL | `diagnose_v5_tournament_challenger.py` | 137 | 0 | Delete or move to research/ (manual diagnostic) |
| MANUAL | `diagnose_v5_tournament_score_challenger.py` | 78 | 0 | Delete or move to research/ (manual diagnostic) |
| MANUAL | `diagnose_walkforward_model_scale.py` | 153 | 0 | Delete or move to research/ (manual diagnostic) |
| MANUAL | `historical_market_mapper.py` | 70 | 1 | Keep as manual tool (data collection / research); review |
| MANUAL | `historical_odds_normalizer.py` | 93 | 1 | Keep as manual tool (data collection / research); review |
| MANUAL | `historical_score_calibration.py` | 133 | 1 | Keep as manual tool (data collection / research); review |
| MANUAL | `probe_fixture_cost.py` | 112 | 0 | Delete or move to research/ (manual diagnostic) |
| MANUAL | `probe_oddspapi.py` | 131 | 0 | Delete or move to research/ (manual diagnostic) |
| MANUAL | `probe_oddspapi_historical_fixtures.py` | 40 | 0 | Delete or move to research/ (manual diagnostic) |
| MANUAL | `probe_relevant_slate.py` | 261 | 0 | Delete or move to research/ (manual diagnostic) |
| MANUAL | `retire_legacy_court_paths.py` | 216 | 0 | Delete (one-shot migration, already applied) |
| MANUAL | `scripts/audit_production_handoff.py` | 195 | 0 | Keep as manual tool (data collection / research); review |
| MANUAL | `scripts/build_pinnacle_closing_2026.py` | 402 | 0 | Keep as manual tool (data collection / research); review |
| MANUAL | `scripts/export_kalshi_training_dataset.py` | 317 | 0 | Keep as manual tool (data collection / research); review |
| MANUAL | `sync_oddspapi_registry_history_status.py` | 89 | 1 | Keep as manual tool (data collection / research); review |
| MANUAL | `v5_score_architecture.py` | 67 | 1 | Keep as manual tool (data collection / research); review |
| MANUAL | `v5_tournament_challenger.py` | 269 | 1 | Keep as manual tool (data collection / research); review |
| MANUAL | `v5_tournament_score_challenger.py` | 89 | 1 | Keep as manual tool (data collection / research); review |
| TEST-ONLY | `context_warehouse/__init__.py` | 4 | 1 | Delete (duplicate warehouse builder package) |
| TEST-ONLY | `historical_backtest_engine.py` | 57 | 1 | Review in Phase 1 (evaluation helper; no production use) |
| TEST-ONLY | `historical_fixture_matcher.py` | 48 | 1 | Review in Phase 1 |
| TEST-ONLY | `historical_state_replay.py` | 31 | 1 | Review in Phase 1 |
| TEST-ONLY | `v5_actions_budget.py` | 62 | 1 | Keep (budget guard; test enforces schedules) |
| TEST-ONLY | `v5_court_conditions_source.py` | 244 | 4 | Delete (retired court conditions) |
| TEST-ONLY | `v5_court_speed.py` | 301 | 2 | Delete (retired court conditions) |
| TEST-ONLY | `v5_courtspeed_fetch.py` | 155 | 1 | Delete (retired court conditions) |
| TEST-ONLY | `v5_ensemble.py` | 50 | 1 | Delete (duplicate of logic in v5_advanced_model) |
| TEST-ONLY | `v5_experiments.py` | 64 | 1 | Review in Phase 1 (promotion helper; unused) |
| TEST-ONLY | `v5_historical_market_reference.py` | 106 | 1 | Review in Phase 1 (reads OddsPapi history) |
| TEST-ONLY | `v5_market_evaluation.py` | 109 | 1 | Review in Phase 1 (market benchmark helper) |
| TEST-ONLY | `v5_production_readiness.py` | 71 | 1 | Delete (unused readiness report) |
| TEST-ONLY | `v5_refresh_court_conditions.py` | 194 | 2 | Delete (retired court conditions) |
| TEST-ONLY | `v5_residual_model.py` | 51 | 1 | Delete (duplicate of logic in v5_advanced_model) |
| TEST-ONLY | `v5_schedule_context.py` | 241 | 1 | Delete (duplicate of v5_master_schedule_context) |
| TEST-ONLY | `v5_weather_context.py` | 143 | 1 | Delete (duplicate of v5_weather_features) |
| ORPHAN | `context_warehouse/schema.py` | 93 | 0 | Delete (orphan) |
| ORPHAN | `historical_v5_replay.py` | 68 | 0 | Delete (orphan) |
| ORPHAN | `prediction_store.py` | 205 | 0 | Delete (orphan) |
| ORPHAN | `pull_oddspapi_core6.py` | 101 | 0 | Delete (orphan; superseded by pull_oddspapi_quota_aware) |
| ORPHAN | `should_run_1am_eastern.py` | 33 | 0 | Delete (orphan) |
| ORPHAN | `show_v5_refresh_status.py` | 23 | 0 | Delete (orphan) |

## 5. Workflows

| Workflow | Triggers | Entry modules |
|---|---|---|
| `audit_production_handoff.yml` | workflow_dispatch | `scripts.audit_production_handoff` |
| `context_warehouse_history_smoke.yml` | workflow_dispatch | `bootstrap_v5_history`, `build_context_warehouse`, `v5_season_files` |
| `context_warehouse_tests.yml` | push, workflow_dispatch | — |
| `courtspeed_conditions_refresh.yml` | workflow_dispatch | — |
| `courtspeed_conditions_tests.yml` | workflow_dispatch | — |
| `export_kalshi_training_dataset.yml` | workflow_dispatch | `scripts.export_kalshi_training_dataset` |
| `extract_oddspapi_tournaments.yml` | workflow_dispatch | — |
| `fixture_registry_tests.yml` | push, workflow_dispatch | — |
| `historical_validation_tests.yml` | push, workflow_dispatch | — |
| `oddspapi_2026_backfill.yml` | workflow_dispatch | `backfill_oddspapi_2026`, `sync_oddspapi_registry_history_status` |
| `oddspapi_fixture_cost_probe.yml` | workflow_dispatch | `probe_fixture_cost` |
| `oddspapi_fixture_registry_seed.yml` | workflow_dispatch | `oddspapi_fixture_registry`, `sync_oddspapi_registry_history_status` |
| `oddspapi_historical_fixture_probe.yml` | workflow_dispatch | `probe_oddspapi_historical_fixtures` |
| `oddspapi_normalized_daily_v2.yml` | schedule, workflow_dispatch | `build_v5_market_board_input`, `fetch_oddspapi_markets`, `normalize_oddspapi_snapshot`, `pull_oddspapi_quota_aware`, `v5_run_repricing` |
| `oddspapi_probe.yml` | workflow_dispatch | `probe_oddspapi` |
| `oddspapi_relevant_slate_probe_v2.yml` | workflow_dispatch | `probe_relevant_slate` |
| `pinnacle_2026_closing_backfill.yml` | workflow_dispatch | `scripts.build_pinnacle_closing_2026` |
| `streamlit_app_smoke.yml` | push, pull_request, workflow_dispatch | — |
| `v5_advanced_model.yml` | push, workflow_dispatch | — |
| `v5_apply_legacy_court_retirement.yml` | workflow_dispatch | `retire_legacy_court_paths` |
| `v5_automatic_settlement.yml` | schedule, workflow_dispatch | `v5_settle_official_recommendations` |
| `v5_calibrated_board_diagnostic.yml` | workflow_dispatch | `diagnose_calibrated_live_board` |
| `v5_context_diagnostic.yml` | workflow_dispatch | `build_v5_context_warehouse`, `build_v5_venue_registry`, `build_v5_weather_cache`, `diagnose_v5_advanced_model`, `diagnose_v5_context_model`, `diagnose_v5_score_distribution` |
| `v5_context_join_keys.yml` | workflow_dispatch | `diagnose_context_join_keys` |
| `v5_context_matchups.yml` | push, workflow_dispatch | — |
| `v5_context_model.yml` | push, workflow_dispatch | — |
| `v5_context_warehouse.yml` | push, workflow_dispatch | `build_v5_context_warehouse` |
| `v5_court_speed.yml` | push, workflow_dispatch | — |
| `v5_daily_predictions.yml` | schedule, workflow_dispatch | `build_v5_context_warehouse`, `v5_build_daily_forecast_artifacts`, `v5_daily_batch`, `v5_daily_policy_postprocess`, `v5_history_freshness`, `v5_run_repricing` |
| `v5_full_test_suite.yml` | pull_request, workflow_dispatch | — |
| `v5_joint_score_calibration_diagnostic.yml` | workflow_dispatch | `diagnose_joint_score_distribution_calibration` |
| `v5_margin_calibration_diagnostic.yml` | workflow_dispatch | `diagnose_margin_calibration` |
| `v5_market_feed_build.yml` | workflow_dispatch | `build_v5_market_board_input` |
| `v5_market_feed_diagnostic.yml` | workflow_dispatch | `diagnose_market_feed` |
| `v5_matchup_features.yml` | push, workflow_dispatch | — |
| `v5_model_bias_diagnostics.yml` | workflow_dispatch | `diagnose_fixture_result_fields`, `diagnose_slam_market_ranges`, `diagnose_state_variation_effect`, `diagnose_v5_selection_bias`, `diagnose_v5_settled_performance`, `diagnose_walkforward_model_scale` |
| `v5_model_calibration_tests.yml` | push, workflow_dispatch | — |
| `v5_player_ratings_refresh.yml` | schedule, workflow_dispatch | `bootstrap_v5_history`, `refresh_tennismylife_cloud`, `v5_history_freshness`, `v5_results_cache`, `v5_season_files` |
| `v5_player_state.yml` | push, workflow_dispatch | — |
| `v5_production_policy.yml` | push, workflow_dispatch | — |
| `v5_rolling_stats.yml` | push, workflow_dispatch | — |
| `v5_score_acceptance.yml` | workflow_dispatch | `build_v5_context_matchups`, `build_v5_context_warehouse`, `build_v5_venue_registry`, `diagnose_v5_context_model`, `diagnose_v5_score_distribution` |
| `v5_score_architecture.yml` | push, workflow_dispatch | — |
| `v5_score_architecture_diagnostic.yml` | workflow_dispatch | `diagnose_v5_score_architecture` |
| `v5_superpowers_completion.yml` | workflow_dispatch | — |
| `v5_total_length_diagnostic.yml` | workflow_dispatch | `diagnose_total_length_calibration` |
| `v5_tournament_authority.yml` | push, workflow_dispatch | `diagnose_v5_tournament_authority` |
| `v5_tournament_challenger.yml` | workflow_dispatch | `build_v5_context_warehouse`, `diagnose_v5_context_model`, `diagnose_v5_tournament_challenger`, `diagnose_v5_tournament_score_challenger` |
| `v5_tournament_registry.yml` | push, workflow_dispatch | — |
| `v5_travel_features.yml` | push, workflow_dispatch | — |
| `v5_venue_metadata.yml` | push, workflow_dispatch | — |
| `v5_weather_context.yml` | push, workflow_dispatch | — |
| `v5_weather_features.yml` | push, workflow_dispatch | — |
| `v5_workload_features.yml` | push, workflow_dispatch | — |

## 6. Data files

Size, then the modules and workflows that reference the file by name.

```
 1460.87MB  oddspapi_history/chunks/*                                    code=backfill_oddspapi_2026,v5_historical_market_reference,scripts.build_pinnacle_closing_2026 wf=
   42.23MB  v5_daily_ready/market_snapshot_history.csv                   code=v5_run_repricing,scripts.audit_production_handoff,scripts.export_kalshi_training_dataset wf=v5_daily_predictions.yml,oddspapi_normalized_daily_v2.yml
   30.47MB  v5_daily_ready/frozen_predictions.csv                        code=v5_signal_tracking,diagnose_v5_settled_performance,v5_settle_official_recommendations,results_accuracy_page… wf=v5_daily_predictions.yml,v5_automatic_settlement.yml
   15.78MB  oddspapi_history/fixtures_2026.jsonl                         code=backfill_oddspapi_2026,diagnose_fixture_result_fields,sync_oddspapi_registry_history_status,scripts.build_pinnacle_closing_2026 wf=extract_oddspapi_tournaments.yml,oddspapi_2026_backfill.yml,oddspapi_fixture_registry_seed.yml
   11.34MB  oddspapi_registry/fixtures.csv                               code=oddspapi_fixture_registry,scripts.build_pinnacle_closing_2026 wf=oddspapi_2026_backfill.yml,oddspapi_fixture_registry_seed.yml,oddspapi_normalized_daily_v2.yml
    4.04MB  v5_men_ratings.csv                                           code=refresh_tennismylife_cloud,v5_daily_batch,diagnose_state_variation_effect wf=v5_player_ratings_refresh.yml
    3.57MB  context_warehouse/player_match_rows.parquet                  code=build_v5_context_warehouse,v5_daily_batch,v5_interactive_production,diagnose_v5_context_model… wf=v5_context_warehouse.yml,v5_daily_predictions.yml,context_warehouse_history_smoke.yml
    3.36MB  v5_results_ready/tennismylife_results.csv                    code=v5_results_cache,build_v5_context_warehouse wf=v5_context_warehouse.yml,v5_player_ratings_refresh.yml
    2.87MB  v5_daily_ready/latest_repriced_board.csv                     code=v5_ui_production,v5_run_repricing wf=v5_daily_predictions.yml,oddspapi_normalized_daily_v2.yml
    2.74MB  context_warehouse/matches.parquet                            code=build_v5_context_warehouse,diagnose_v5_tournament_score_challenger,build_v5_venue_registry,build_v5_weather_cache… wf=v5_context_warehouse.yml,context_warehouse_history_smoke.yml
    2.64MB  v5_men_walkforward.csv                                       code=build_v5_context_matchups,diagnose_margin_calibration,diagnose_joint_score_distribution_calibration,diagnose_total_length_calibration… wf=v5_player_ratings_refresh.yml
    2.14MB  v5_daily_ready/daily_market_probabilities.csv                code=v5_build_daily_forecast_artifacts,v5_run_repricing wf=v5_daily_predictions.yml
    1.75MB  v5_daily_ready/latest_board.csv                              code=v5_build_daily_forecast_artifacts,v5_daily_batch,v5_daily_policy_postprocess,diagnose_state_variation_effect… wf=v5_daily_predictions.yml
    1.45MB  v5_wta_ratings.csv                                           code=refresh_tennismylife_cloud,v5_daily_batch,diagnose_state_variation_effect wf=v5_player_ratings_refresh.yml
    1.21MB  v5_daily_ready/official_recommendations.csv                  code=v5_ui_production,v5_settle_official_recommendations,v5_run_repricing wf=v5_daily_predictions.yml,oddspapi_normalized_daily_v2.yml,v5_automatic_settlement.yml
    0.76MB  v5_market_ready/all_book_prices.csv                          code=build_v5_market_board_input,v5_live_market,tennis_quant_app_v5 wf=oddspapi_normalized_daily_v2.yml,v5_market_feed_build.yml
    0.61MB  v5_market_ready/market_board_input.csv                       code=v5_refresh_court_conditions,build_v5_market_board_input,v5_build_daily_forecast_artifacts,v5_live_market… wf=oddspapi_normalized_daily_v2.yml,v5_market_feed_build.yml
    0.60MB  v5_wta_walkforward.csv                                       code=build_v5_context_matchups,diagnose_margin_calibration,diagnose_joint_score_distribution_calibration,diagnose_total_length_calibration… wf=v5_player_ratings_refresh.yml
    0.38MB  oddspapi_history/historical_checkpoint.json                  code=backfill_oddspapi_2026,sync_oddspapi_registry_history_status,scripts.build_pinnacle_closing_2026 wf=
    0.35MB  v5_daily_ready/recommendation_audit.csv                      code=v5_run_repricing wf=v5_daily_predictions.yml,oddspapi_normalized_daily_v2.yml
    0.29MB  exports/v5_settled_moneyline_model_market_results_2026-10-11.csv code= wf=
    0.29MB  exports/kalshi_training_sides.csv                            code=scripts.export_kalshi_training_dataset wf=export_kalshi_training_dataset.yml
    0.26MB  v5_refresh_log.jsonl                                         code=refresh_tennismylife_cloud wf=v5_player_ratings_refresh.yml
    0.24MB  experiments/acceptance/context_model_report.json             code= wf=v5_context_diagnostic.yml
    0.21MB  exports/settled_matches_starting_moneyline_odds.csv          code= wf=
    0.20MB  exports/v5_settled_moneyline_calibration_compact_2026-10-11.csv code= wf=
    0.17MB  exports/kalshi_training_matches.csv                          code=scripts.export_kalshi_training_dataset wf=export_kalshi_training_dataset.yml
    0.16MB  exports/production_handoff_audit.json                        code=scripts.audit_production_handoff wf=audit_production_handoff.yml
    0.09MB  v5_daily_ready/daily_forecasts.csv                           code=v5_build_daily_forecast_artifacts wf=v5_daily_predictions.yml
    0.08MB  context_registry/tournament_authority.csv.csv                code= wf=
    0.08MB  context_registry/tournament_authority.csv                    code=v5_tournament_authority,diagnose_v5_tournament_authority,diagnose_v5_tournament_challenger,retire_legacy_court_paths wf=v5_tournament_authority.yml,courtspeed_conditions_refresh.yml
    0.07MB  oddspapi_history/tournament_identity_registry.csv            code= wf=extract_oddspapi_tournaments.yml
    0.05MB  experiments/acceptance/score_model_report.json               code= wf=v5_context_diagnostic.yml,v5_score_acceptance.yml
    0.05MB  experiments/acceptance/advanced_model_report.json            code= wf=v5_context_diagnostic.yml
    0.03MB  experiments/acceptance/production_candidate.json             code=diagnose_v5_settled_performance,v5_ui_health,results_accuracy_page,diagnose_v5_advanced_model… wf=v5_context_diagnostic.yml,v5_full_test_suite.yml,streamlit_app_smoke.yml
    0.03MB  context_registry/tennis_master_schedule.csv                  code=v5_ui_production,v5_master_schedule_context,v5_schedule_context wf=v5_daily_predictions.yml
    0.02MB  experiments/acceptance/tournament_score_challenger_report.json code= wf=v5_tournament_challenger.yml
    0.02MB  experiments/acceptance/tournament_challenger_report.json     code= wf=v5_tournament_challenger.yml
    0.02MB  experiments/acceptance/context_diagnostic_status.json        code= wf=v5_context_diagnostic.yml
    0.01MB  v5_refresh_last.json                                         code=v5_history_freshness,refresh_tennismylife_cloud,v5_ui_health,show_v5_refresh_status wf=v5_daily_predictions.yml,v5_player_ratings_refresh.yml
    0.01MB  v5_daily_ready/settled_performance_audit.json                code=v5_ui_performance,diagnose_v5_settled_performance wf=
    0.01MB  v5_daily_ready/official_performance.json                     code=v5_ui_performance,v5_settle_official_recommendations wf=v5_automatic_settlement.yml
    0.01MB  v5_daily_ready/latest_summary.json                           code=v5_daily_batch wf=v5_daily_predictions.yml
    0.01MB  oddspapi_history/historical_fixture_probe.json               code=probe_oddspapi_historical_fixtures wf=oddspapi_historical_fixture_probe.yml
    0.01MB  exports/kalshi_training_export_qc.json                       code=scripts.export_kalshi_training_dataset wf=export_kalshi_training_dataset.yml
    0.01MB  experiments/acceptance/score_production_candidate.json       code=v5_ui_health,v5_daily_batch wf=v5_context_diagnostic.yml,v5_full_test_suite.yml,streamlit_app_smoke.yml
    0.01MB  experiments/acceptance/score_acceptance_status.json          code=v5_ui_health wf=v5_score_acceptance.yml
    0.01MB  context_warehouse/source_manifest.json                       code=build_v5_context_warehouse,context_warehouse.io wf=v5_context_warehouse.yml,v5_context_diagnostic.yml,context_warehouse_history_smoke.yml
    0.00MB  v5_results_ready/results_status.json                         code=v5_results_cache,build_v5_context_warehouse,v5_ui_health wf=v5_context_warehouse.yml,v5_automatic_settlement.yml,v5_player_ratings_refresh.yml
    0.00MB  v5_market_ready/market_feed_qc.json                          code=build_v5_market_board_input wf=oddspapi_normalized_daily_v2.yml,v5_market_feed_build.yml
    0.00MB  v5_daily_ready/settlement_summary.json                       code=v5_settlement wf=
    0.00MB  v5_daily_ready/results_reset.json                            code=v5_signal_tracking,v5_ui_performance,v5_results_reset wf=
    0.00MB  v5_daily_ready/repricing_status.json                         code=v5_ui_production,v5_ui_health,v5_run_repricing wf=v5_daily_predictions.yml,oddspapi_normalized_daily_v2.yml
    0.00MB  v5_daily_ready/official_settlement_status.json               code=v5_ui_health,v5_settle_official_recommendations wf=v5_automatic_settlement.yml
    0.00MB  v5_daily_ready/forecast_status.json                          code=v5_build_daily_forecast_artifacts,v5_ui_health wf=v5_daily_predictions.yml
    0.00MB  v5_build_summary.json                                        code=v5_ui_daily_board,build_v5_states,tennis_quant_app_v5,v5_daily_batch… wf=v5_player_ratings_refresh.yml
    0.00MB  oddspapi_history/backfill_summary.json                       code=backfill_oddspapi_2026 wf=oddspapi_2026_backfill.yml
    0.00MB  experiments/acceptance/tournament_challenger_status.json     code= wf=v5_tournament_challenger.yml
    0.00MB  experiments/acceptance/superpowers_contract_status.json      code= wf=
    0.00MB  experiments/acceptance/streamlit_smoke_status.json           code=v5_ui_health wf=streamlit_app_smoke.yml
    0.00MB  experiments/acceptance/full_regression_status.json           code=v5_ui_health wf=
    0.00MB  data/court_conditions/courtspeed_snapshot.csv                code=v5_refresh_court_conditions,v5_court_conditions_source wf=
    0.00MB  data/court_conditions/courtspeed_refresh_status.json         code=v5_refresh_court_conditions,v5_court_conditions_source wf=
    0.00MB  data/court_conditions/README.md                              code= wf=
    0.00MB  context_warehouse/schema.json                                code=build_v5_context_warehouse,context_warehouse.io wf=v5_context_warehouse.yml,v5_context_diagnostic.yml,context_warehouse_history_smoke.yml
    0.00MB  context_registry/player_aliases.csv                          code=v5_daily_batch wf=
    0.00MB  .devcontainer/devcontainer.json                              code= wf=
```

## 7. Documents

- **Specs:** 17 in `docs/superpowers/specs/`. Only the 2026-10-12 roadmap is current. Five
  describe retired court-condition or court-speed work (09-01 and 09-02 amendments, 09-13
  ×2, 09-14 courtspeed refresh). The rest (full-context model, Today UI, self-functioning
  pipeline, decision feed, official top-play contract, schedule/context persistence,
  market-aware decision system, preflight audit) describe the current code and predate the roadmap.
- **Plans:** 14 in `docs/superpowers/plans/`, one per spec above, all September.
- **Experiments:** 6 in `docs/experiments/`; one (`2026-09-13-court-conditions-pr-note.md`) is empty.
