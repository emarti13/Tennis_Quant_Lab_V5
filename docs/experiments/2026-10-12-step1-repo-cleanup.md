# Step 1: repo cleanup (2026-10-12)

Plan: `docs/superpowers/plans/2026-10-12-ground-up-rebuild-plan.md`, Step 1 (approved).
Evidence for each removal: `docs/inventory/2026-10-12-repo-inventory.md` (import graph).
Category: Production Reliability. No production module changed; no model or policy change.

## Rule applied

Remove what nothing live depends on. **Keep** anything that produces a file production or the
app reads, even if it lives in a "diagnostic" script, until the step that replaces it:

- `diagnose_v5_advanced_model.py`, `diagnose_v5_context_model.py`, `diagnose_v5_score_distribution.py`
  produce `experiments/acceptance/*production_candidate.json`, which the daily forecast reads.
  They are kept until Step 4 replaces the model.
- `diagnose_v5_settled_performance.py` produces `settled_performance_audit.json`, which the
  Performance page reads. Kept until Step 5.
- `diagnose_v5_tournament_*` and `v5_tournament_challenger*` are kept until Step 2 replaces
  tournament identity.
- The six Phase 1 evaluation helpers (`historical_backtest_engine`, `historical_fixture_matcher`,
  `historical_state_replay`, `v5_experiments`, `v5_market_evaluation`,
  `v5_historical_market_reference`) are kept for review in Phase 1.

## Removed (recoverable from git history)

| Group | Modules | Tests | Workflows |
|---|---|---|---|
| Orphans (nothing imports or runs them) | `historical_v5_replay`, `prediction_store`, `pull_oddspapi_core6`, `should_run_1am_eastern`, `show_v5_refresh_status` | – | – |
| Duplicates of live code | `v5_ensemble`, `v5_residual_model` (live versions in `v5_advanced_model`); `v5_schedule_context` (live: `v5_master_schedule_context`); `v5_weather_context` (live: `v5_weather_features`); `build_context_warehouse` + `context_warehouse/*.py` (live: `build_v5_context_warehouse`; the `context_warehouse/` data files stay) | `test_v5_schedule_context`, `test_v5_weather_context`, `test_context_warehouse`; 3 tests in `test_v5_superpowers_completion` | `context_warehouse_tests`, `context_warehouse_history_smoke`, `v5_weather_context` |
| Retired court conditions | `v5_court_conditions_source`, `v5_court_speed`, `v5_courtspeed_fetch`, `v5_refresh_court_conditions`, `retire_legacy_court_paths` (one-shot, applied); `data/court_conditions/` | `test_v5_court_conditions_{no_network,resolution,snapshot,source}`, `test_v5_court_speed`, `test_v5_courtspeed_refresh` | `courtspeed_conditions_refresh`, `courtspeed_conditions_tests`, `v5_apply_legacy_court_retirement`, `v5_court_speed` |
| OddsPapi probes (one-off) | `probe_fixture_cost`, `probe_oddspapi`, `probe_oddspapi_historical_fixtures`, `probe_relevant_slate` | 1 test in `test_v5_actions_budget` | 4 probe workflows |
| Superseded diagnostics of the current model | `diagnose_calibrated_live_board`, `diagnose_context_join_keys`, `diagnose_fixture_result_fields`, `diagnose_joint_score_distribution_calibration`, `diagnose_margin_calibration`, `diagnose_slam_market_ranges`, `diagnose_state_variation_effect`, `diagnose_total_length_calibration`, `diagnose_v5_score_architecture`, `diagnose_v5_selection_bias`, `diagnose_walkforward_model_scale`, and the two modules only they used: `historical_score_calibration`, `v5_score_architecture` | `test_historical_score_calibration`, `test_v5_score_architecture` | 6 diagnostic workflows + `v5_score_architecture`; 5 steps removed from `v5_model_bias_diagnostics` |
| Broken one-off | `diagnose_market_feed` (crashed on import; searched for two named players) | – | `v5_market_feed_diagnostic` |
| Unused report | `v5_production_readiness` | `test_v5_production_readiness` | references removed from `v5_production_policy` |
| Stray / static files | `context_registry/tournament_authority.csv.csv` (stray copy); `experiments/acceptance/full_regression_status.json` (static "success" that nothing updated) | – | – |

Docs: the five court-condition specs, their three plans and three experiment notes are marked
**Superseded** (kept for history).

## Verification

- Every remaining module imports (92 checked).
- Import graph re-run: 96 modules. **0 orphans**. Test-only: the 6 Phase 1 helpers plus
  `v5_actions_budget` (budget guard). Every `.py` file named in a workflow exists, and every
  workflow parses.
- `python -m pytest tests -q`: **369 passed** (421 before; the 52 removed tests covered only
  removed code).
- Live modules changed: **none**. Only workflow reference lists and tests changed.
- App driven end to end with Playwright on this branch and compared with the 2026-10-12 baseline:
  six of seven pages are byte-identical. **Model Health** now shows "Full regression: Unknown" and
  "Model acceptance: Unknown" instead of a permanent "Success". That is intended: it no longer
  reports a static file as a CI result. Step 6 connects it to real CI status.
