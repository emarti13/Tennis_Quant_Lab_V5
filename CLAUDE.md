# CLAUDE.md: working rules for AI agents in this repo

Status: **DRAFT — pending user approval.**

## Read first, in this order
1. `PROJECT_MANDATE.md`: precedence is mandate > specs > plans > code > fixes.
2. `docs/superpowers/specs/2026-10-12-fair-price-to-market-making-roadmap-design.md`: the program goal and the current phase/gate.
3. Any spec or plan for the area you are touching (`docs/superpowers/specs/`, `docs/superpowers/plans/`).

The goal: a fair-price engine that beats the market, proven first as a taker and then used for market making. Any work that doesn't move a roadmap gate forward or keep production safe needs a reason.

## Git
- Never push to `main`. One logical change per branch and PR.
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
- **Surface comes only from `tournament_authority`** (`resolve_fixture_surface`). Court-condition modules are retired.

## Required checks before asking for merge
- `python -m pytest tests -q`, all green (CI runs it and posts failures as annotations).
- For feature/model/production changes, also:
  - `tests/test_v5_fatigue_features.py`, including the real-data leak/parity tests (CI workflow `v5_fatigue_features.yml`).
  - `python v5_model_guard.py --selftest`, plus a guard run on any new prediction file.
- The PR description says which roadmap gate it serves, what was measured, and against what benchmark.

## Environment notes
- PyPI is blocked in the chat workspace. Rely on the GitHub Actions CI loop for full tests. Actions log downloads are blocked, so read check-run annotations instead.
- Actions budget: 3,000 minutes/month. Heavy or research workflows are `workflow_dispatch` only. No new scheduled jobs without a budget note.
- Do not try to route around blocked network hosts.
- No paid data sources. Collectors use free public endpoints and must fit the Actions budget (roadmap §5.1); no continuous polling jobs. ITF is out of scope.

## Repo map (main pieces)
- Data: `bootstrap_v5_history.py` → `.v5_history_cache/`; `refresh_tennismylife_cloud.py`; `v5_results_ready/`.
- Features: `v5_fatigue_features.py` (leak-free, research candidate); `v5_workload_features.py` (**leaky, being retired**).
- Warehouse/production: `build_v5_context_warehouse.py`, `v5_daily_batch.py`, `v5_interactive_production.py`, `v5_official_performance.py`.
- Safety: `v5_model_guard.py`, `v5_fatigue_validation.py`.
- Ledgers: `v5_daily_ready/official_recommendations.csv` (frozen; never rewrite), `market_snapshot_history.csv` (append-only).
- Experiments are recorded in `docs/experiments/YYYY-MM-DD-*.md`.
