# Ground-up rebuild plan

Date: 2026-10-12
Status: **DRAFT — pending user approval**
Serves: roadmap Phase 0 → Gate 0 (`docs/superpowers/specs/2026-10-12-fair-price-to-market-making-roadmap-design.md`).
Evidence: `docs/inventory/2026-10-12-repo-inventory.md`.

## Goal

Rebuild the system one layer at a time, in the order the data flows, so that each layer
is verified before the next is built on it. The app keeps working after every step.

**OddsPapi + TennisMyLife → data warehouse → user overrides (surface etc. when the feeds
don't know) → one simulation/pricing function → frozen forecast → market comparison →
ledger → settlement → performance → app.** Later phases use the same fair price for
taker validation and market making.

## Rules for every step (no stray fixes)

A step is done only when all of these hold:

1. **One implementation per job.** When a step replaces something, the old module, its
   tests, its workflow, and any doc that describes it as current are removed in the
   same PR. Git history keeps them.
2. **Every caller is updated.** The import graph from the inventory is re-run after the
   change, and no module, workflow, or app page still points at the removed path.
3. **The app still works, end to end.** In a scratch copy, run the step's pipeline
   scripts, launch Streamlit, and drive all seven pages plus one override run with
   Playwright. Compare against the previous step's run; any change must be one the
   step intended.
4. **Tests:** `python -m pytest tests -q` green locally and in CI.
5. **Docs:** CLAUDE.md repo map and the inventory are updated in the same PR.
6. **One PR per step**, on its own `fix/…`, `feat/…`, `repair/…`, or `docs/…` branch.
   Each PR says which gate it serves and what was measured.
7. **Protected history:** `official_recommendations.csv` and
   `market_snapshot_history.csv` are never rewritten. The sealed period (results on or
   after 2026-10-13 UTC) is never used for selection or tuning.

## Steps

### Step 1. Clean the repo (no behavior change)

- Delete the 43 modules marked Delete in the inventory (orphans, duplicates, retired
  court-conditions code, one-shot migration, stale probes), with their tests and workflows.
- Delete the retired echo-only workflows, `data/court_conditions/`, and the stray
  `context_registry/tournament_authority.csv.csv`.
- Move the manual diagnostics that Phase 1 still needs into `research/`; delete the rest.
- Mark the 5 court-condition specs and their plans **Superseded**; mark the other
  September specs as superseded by this plan where it replaces them.
- Delete `experiments/acceptance/full_regression_status.json` and the static smoke status;
  Model Health shows CI status from a real source (Step 6) or nothing.
- **Done when:** the app's seven pages show the same content as the baseline run, and
  the production scripts produce byte-identical artifacts from the same inputs.

### Step 2. Data layer: one source per fact

- **Results:** TennisMyLife history and current season (season-year handling already
  done on this branch), then the results cache. Nothing else downloads results.
- **Warehouse:** one builder (`build_v5_context_warehouse.py`), built once per day by the
  production workflow. The forecast and the app read **the same build** (storage
  choice: decision D1).
- **Master tennis schedule (user design, 2026-10-12).** One file holds every tournament
  with its court-specific information: dates, tour/category, city/country, coordinates,
  altitude, time zone, surface, indoor/outdoor, ball, CPI, notes, and OddsPapi IDs. It
  replaces `tournament_authority.csv` and `tennis_master_schedule.csv` (merged; the
  authority's 2026 Challenger rows and coordinates are kept). `v5_master_schedule_context`,
  `v5_tournament_registry` and `v5_tournament_context_registry` are removed; one module
  reads the file.
  - **Stable event id** per tournament (for example `atp-250-brisbane`) that stays the same
    across years, so a new year's event links to its history.
  - **ISO dates** (`2026-04-05`) and **IANA time zones** (`Australia/Brisbane`, not
    `UTC+10`, so daylight saving is correct).
  - **2026 reconciliation report:** every 2026 row checked against TennisMyLife 2026
    results (tournament name, surface) and OddsPapi fixtures (tournament names and IDs).
    Output lists events with no match, surface disagreements, and missing OddsPapi IDs.
- **Resolving a fixture to an event**, in order, with the method shown in the app:
  1. this year's row (OddsPapi tournament ID, then tour + name/city + date window);
  2. **carried forward**: no row for this year, but the same event id exists in an
     earlier year, so surface, setting, time zone, altitude and coordinates are copied
     and labeled "from <year>";
  3. **unknown**: no match. The fixture gets no price (fail closed) and is listed in the
     app as needing an override.
- **Overrides:** set in the app when the choice is wrong or unknown. An override is stored
  only for a value the user changed, keyed by event id and year, and labeled as an
  override. Overrides are kept in a reviewable file and can be promoted into the master
  schedule so the next year carries them forward.
- No hard-coded years on live paths (everything goes through `v5_season_files.py`).

### Step 3. Market data layer (roadmap Phase 0 collection)

- OddsPapi feed with a **start-time-aware freshness rule**: a price is actionable only if
  the snapshot is recent **and** the match has not started. Started fixtures leave the
  live board.
- Keep the first-seen (opening) line and the last pre-start line for each fixture.
- Kalshi trades and 1-minute candles, one daily pull after settlement (≤ 3 min); order-book
  depth only inside existing runs. Budget entries added to `v5_actions_budget.py`.

### Step 4. Model: leak-free baseline and one pricing function

- Review and merge PR #36 (fatigue_v1, parity/leak tests, `v5_model_guard.py`).
- Production probability = leak-free baseline (Elo + surface). `v5_workload_features`
  is removed from every path. fatigue_v1 enters only after it passes its own
  out-of-sample gate against this baseline, with the market benchmark reported.
- **One function** prices a fixture from (fixture, warehouse, overrides, ratings). The
  daily batch and the app override run both call it. Parity test: with no overrides,
  the override run reproduces the frozen forecast exactly.
- The model guard runs before anything is frozen or published: extreme model-vs-market
  gaps and wide component disagreement block a price (the Hurkacz case in the inventory).

### Step 5. Pricing, ledger, settlement, performance

- Keep ledger semantics (roadmap §6). Verify repricing, the official recommendation
  ledger, settlement and performance on the rebuilt inputs.
- EV and ROI claims only at executable prices, with fees (CLAUDE.md).

### Step 6. App

- Every status shown is computed from real timestamps or real CI results: freshness,
  "actionable", Model Health, regression status.
- The override run uses the Step 4 function; the page explains which values were overridden.
- Remove UI paths that read retired fields (court speed, CPI, etc.).

### Then: Gate 0

CI green on `main` for 7 consecutive days; guard and parity checks required on PRs;
collectors writing at least 95% of scheduled snapshots for 14 days. Then Phase 1
(honest benchmark).

## Decisions needed from the user

- **D1. Where the shared daily warehouse lives.** (a) Commit it daily (about 6 MB per day
  added to git); (b) upload it as a GitHub release asset that the app downloads; (c)
  build it in the app's host on a schedule. Recommendation: (b).
- **D2. Old PRs and branches.** Close #28, #30, #31, #32 (pre-roadmap) and delete
  merged or stale remote branches? Review #36 as part of Step 4?
- **D3. OddsPapi raw history (1.46 GB in git).** Stop adding new chunks to git and
  store future ones as release assets? Existing history stays (rewriting git history is
  destructive and not proposed).
- **D4. Branch for this work.** This session was assigned
  `claude/bootstrap-v5-history-setup-3pxlyr`. CLAUDE.md asks for one branch and PR per
  step. OK to open one branch per step with CLAUDE.md names?
- **D6. Master schedule source and editing.** Start from the repo's
  `tournament_authority.csv` (has Challengers and coordinates) and add the user's new
  columns (Country Code, Category, Currency, Prize Money, Scheduling / Notes)? Who edits
  it and how: the user in a spreadsheet, exported as "CSV UTF-8"?
- **D7. Filling location columns automatically.** Coordinates, altitude and IANA time zone
  can be filled from Open-Meteo's free geocoding API (the repo already uses Open-Meteo for
  weather). It needs `geocoding-api.open-meteo.com` allowed in this environment. Ball,
  CPI and notes stay manual.
- **D5. Commits already on the session branch.** Six commits (season-year rollover,
  workflow triggers, budget model, test fixes). Keep them as the first PR, or fold them
  into Steps 1–2?
