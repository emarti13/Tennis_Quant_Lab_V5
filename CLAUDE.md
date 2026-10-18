# CLAUDE.md: working rules for AI agents in this repo

Status: Approved by the user in chat, 2026-10-12.

## Read first, in this order
1. `PROJECT_MANDATE.md`: precedence is mandate > specs > plans > code > fixes.
2. `docs/superpowers/specs/2026-10-12-fair-price-to-market-making-roadmap-design.md`: the program goal and the current phase/gate.
3. Any spec or plan for the area you are touching (`docs/superpowers/specs/`, `docs/superpowers/plans/`).

The goal: a fair-price engine that beats the market, proven first as a taker and then used for market making. Any work that doesn't move a roadmap gate forward or keep production safe needs a reason.

## Git
- Never push to `main`. One logical change per branch and PR.
- Anything you cannot remove yourself (for example, branch deletion is blocked from agent sessions) goes on the checklist in `manual_cleanup/README.md`, with why it can go and how to remove it. Do not leave it only in chat.
- Branch names: `fix/…`, `feat/…`, `repair/…`, `docs/…`, `research/…`.
- New or changed specs are marked `DRAFT — pending user approval` until the user approves them in chat.
- If `gh pr create` fails with a GraphQL 403 (some sandboxed agent workspaces only allow GitHub's REST API), open the PR with `gh api repos/emarti13/Tennis_Quant_Lab_V5/pulls -X POST` instead.

## Model and feature rules
- **No leakage.** Never order matches by `tourney_date` plus file order: winner-first files leak the result. Use `v5_fatigue_features.py` ordering (tennis week, then stage, then round; same round = concurrent).
- **One code path.** Historical features and live features must come from the same function. Add a parity test for every new feature.
- **Out-of-sample proof.** A feature or model change is accepted only if it improves chronological OOS log loss against the current engine. Report the market benchmark next to every metric.
- **Sealed period.** Do not use results inside the sealed forward period (roadmap §4, Phase 0) for selection, tuning, or thresholds.
- **Fail closed.** Unknown player, unknown event, stale price, missing timestamp → raise or output no price. Never silently default (no quiet 1500 Elo, no `fillna(0)` on features without a flag column).
- **Executable prices only** for EV, ROI, and CLV claims. Pinnacle is information; Bet365, BetRivers, Kalshi, Polymarket, and Novig are execution. Include fees.
- **Surface and court attributes come only from the master schedule** through `v5_fixture_resolution.py` (overrides on top). The old engine still reads `tournament_authority` until rebuild Step 4 removes it; do not add new callers of it. Court-condition modules are retired.

## Required checks before asking for merge
- `python -m pytest tests -q`, all green (CI runs it and posts failures as annotations).
- For feature/model/production changes, also:
  - `tests/test_v5_fatigue_features.py`, including the real-data leak/parity tests (CI workflow `v5_fatigue_features.yml`).
  - `python v5_model_guard.py --selftest`, plus a guard run on any new prediction file.
- The PR description says which roadmap gate it serves, what was measured, and against what benchmark.

## Environment notes
- PyPI is blocked in the chat workspace. Rely on the GitHub Actions CI loop for full tests. Actions log downloads are blocked, so read check-run annotations instead.
- Actions budget: 3,000 minutes/month. Heavy or research workflows are `workflow_dispatch` only. No new scheduled jobs without a budget entry in `v5_actions_budget.py` (`SCHEDULED_WORKFLOWS`; a test enforces it).
- Pushes made by workflows with the default `GITHUB_TOKEN` do not trigger other workflows. Do not design chains that rely on a bot commit firing a `push:` workflow.
- Do not try to route around blocked network hosts.
- No paid data sources. Collectors use free public endpoints and must fit the Actions budget (roadmap §5.1); no continuous polling jobs. ITF is out of scope.

## Repo map (main pieces)
- Data: `bootstrap_v5_history.py` → `.v5_history_cache/` (history through last year); `refresh_tennismylife_cloud.py` (current season); `v5_results_ready/`. Season years and file names come only from `v5_season_files.py`; never hard-code a year.
- Tournaments: master schedule `context_registry/master_schedule/master_schedule_<year>.csv` (user-maintained, official calendars); `v5_tournament_identity.py` matches OddsPapi and TennisMyLife to it and stores the result in `crosswalk_oddspapi.csv` / `crosswalk_tennismylife.csv` (rebuilt by `scripts/reconcile_master_schedule.py`; it never overwrites rows marked `confirmed`, `user` or `rejected`). Not yet read by production.
- Players: `v5_player_registry.py` → `context_registry/players/` (our own `player_id`; TennisMyLife and OddsPapi ids are aliases; built by `scripts/build_player_registry.py`; rows marked `confirmed`, `user` or `rejected` are never overwritten). Not yet read by production; `v5_player_identity.py` (name-only) is retired when the daily batch switches.
- User decisions: only in the decision files listed in `context_registry/DECISIONS.md` (never in the generated crosswalk/alias tables, which the daily rebuild overwrites; it reads decision files and never writes them).
- Fixture resolution: `v5_fixture_resolution.py` (fixture → edition, court, best-of, player ids; fails closed). Tables refreshed daily by `scripts/refresh_identity.py` (ratings workflow); flags in `context_registry/identity_status.json`.
- Baseline model: `v5_baseline_elo.py` (leak-free surface Elo keyed by `player_id`, fatigue ordering; measured in `docs/experiments/2026-10-17-baseline-elo.md`). Not yet read by production.
- Pricing: `v5_pricing.py` (`price_fixture`: the one function from fixture to model price, stage and per-book cautious edge; fails closed with a reason code; minimum 18 rated matches). Not yet read by production (Step 4g switches the daily batch and the override run).
- Features: `v5_fatigue_features.py` (leak-free, research candidate; on `main` since #36, not yet in production); `v5_workload_features.py` (**leaky, being retired**).
- Warehouse/production: `build_v5_context_warehouse.py`, `v5_daily_batch.py`, `v5_interactive_production.py`, `v5_official_performance.py`.
- Safety: `v5_model_guard.py`, `v5_fatigue_validation.py` (on `main` since #36).
- Market prices: `v5_market_history.py` → `market_history/` (fixtures and price points per month, append-only; open, close, checkpoints per book and selection, keyed by our ids). Filled daily by `scripts/pull_market_history.py` (`v5_market_history.yml`) from OddsPapi `/historical-odds`; raw payloads go to monthly `market-raw-YYYY-MM` releases, not git. Kalshi match markets: `v5_kalshi_history.py` → `market_history/kalshi/` (bid/ask and trades before the start, tied to OddsPapi fixtures), same workflow (`scripts/pull_kalshi_history.py`). Live pre-match prices: `v5_live_prices.py` → `market_history/live/` (price standing at fetch time, same code as the close; `is_actionable` is the one freshness rule), filled by `scripts/pull_live_prices.py` in the live workflow. De-vig and the cautious edge rule: `v5_devig.py` (lam per book, measured). Winners: `v5_market_results.py` (TennisMyLife, then Kalshi, then in-play calls from the stored price histories; matches retired before two completed sets, and walkovers, are void for measurement). Fixture stage (main draw or qualifying; a label, not a filter): `v5_fixture_stage.py`. Not yet read by production.
- Ledgers: `v5_daily_ready/official_recommendations.csv` (frozen; never rewrite; rows before the rebuild are not evidence), `market_snapshot_history.csv` (append-only). New official recommendations are paused by `production_switches.json` (fails closed) until rebuild Step 5.
- Experiments are recorded in `docs/experiments/YYYY-MM-DD-*.md`.
