# Ground-up rebuild plan

Date: 2026-10-12
Status: **Approved by the user in chat, 2026-10-12.** Decisions recorded below.
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
  altitude, time zone, surface, indoor/outdoor, ball, CPI, notes, and OddsPapi IDs. The
  user's column layout (2026-10-12) is the target: Year, Date, End Date, Circuit Tour,
  Tournament Name, City, State, Country Code, Country, Time Zone, Category, Currency,
  Prize Money, Latitude, Longitude, Altitude, Surface Code, Surface, Setting,
  Scheduling / Notes, OddsPapi Tournament ID, OddsPapi Season ID, ball and CPI columns.
  It is **rebuilt**, not copied: `tournament_authority.csv` (V1) has known errors and
  `tennis_master_schedule.csv` is partial, so both are used only as cross-checks and the
  differences are listed for review. Both are retired when the new file is in use.
  `v5_master_schedule_context`,
  `v5_tournament_registry` and `v5_tournament_context_registry` are removed; one module
  reads the file.
  - **Identity across sources** follows `docs/superpowers/specs/2026-10-12-tournament-identity-design.md`
    (approved, including amendment A of 2026-10-13): canonical event and edition ids owned by the master schedule, one stored
    crosswalk per source (OddsPapi, TennisMyLife), a resolver that matches on tour, date
    window, location and player overlap (names only as a tiebreaker), a confirmation loop
    from results, and review/override in the app. No source's own id or name is the key.
  - **ISO dates** (`2026-04-05`) and **IANA time zones** (`Australia/Brisbane`, not
    `UTC+10`, so daylight saving is correct).
  - **2026 reconciliation report:** every 2026 row checked against TennisMyLife 2026
    results (tournament name, surface) and OddsPapi fixtures (tournament names and IDs).
    Output lists events with no match, surface disagreements, and missing OddsPapi IDs.
- **Crosswalks (done 2026-10-12):** `context_registry/master_schedule/crosswalk_oddspapi.csv`
  and `crosswalk_tennismylife.csv`, written by `scripts/reconcile_master_schedule.py`,
  confirmed by shared matches, read with `v5_tournament_identity.resolve_edition`.
  Production does not read them yet; replacing the four old lookups is next.
- **Player identity (built 2026-10-13: `v5_player_registry.py`, `context_registry/players/`).** Same approach as tournaments: a
  stored crosswalk from OddsPapi participant ids to one TennisMyLife player, proven by
  results (same edition, same opponent), user decisions never overwritten, unclear links
  give no price. Today the live resolver refuses 15 players whose names appear twice in
  our own history (de Minaur, De Jong, Ruse, Kessler...), refuses 97 spelling variants,
  and prices at least 9 known players as new (extra given names, e.g. Maria Carle). The
  history duplicates are merged into one player; that changes ratings, so it is measured
  against the current engine before going live.
- **Fixture resolution (built 2026-10-15: `v5_fixture_resolution.py`).** One function turns an
  OddsPapi fixture into its edition (court attributes from the master schedule, user
  overrides on top) and two player ids, or a reason it cannot (fail closed). Refreshed
  daily by `scripts/refresh_identity.py` in the ratings workflow, which also writes
  `context_registry/identity_status.json` with the "schedule needs attention" flags (D6).
  The old engine is its only would-be caller and is replaced in Step 4, so the switch-over
  and the removal of the old lookups happen there, in one change (no patching of the old
  engine; owner direction 2026-10-13).
- **Resolving a fixture:** through the crosswalk (spec §2.2–2.5). Unmatched or ambiguous
  → no price, listed for review (fail closed). No row for this year → carried forward from
  the same event, labeled "from <year>".
- **Overrides:** set in the app when the choice is wrong or unknown. An override is stored
  only for a value the user changed, keyed by event id and year, and labeled as an
  override. Overrides are kept in a reviewable file and can be promoted into the master
  schedule so the next year carries them forward.
- No hard-coded years on live paths (everything goes through `v5_season_files.py`).

### Step 3. Market data layer (roadmap Phase 0 collection)

Design: `docs/superpowers/specs/2026-10-16-market-data-layer-design.md` (approved
2026-10-16). It chooses option (a) below, a daily OddsPapi historical pull, plus Kalshi daily.

**Status 2026-10-17: built.**
- price store with the daily pull and backfills (#55, #58);
- Kalshi (#56);
- de-vig with the cautious edge rule, lam measured per book (#57);
- winners from TennisMyLife and Kalshi, cross-checked (#59);
- live pre-match prices and the freshness rule (#60);
- in-play calls as the third results source; retirements before two sets void (#62);
- the backfill finds where OddsPapi history starts by date (#64). OddsPapi had already
  deleted Bet365 history through at least 2026-04-05 when the re-pull began, so Bet365 closes
  exist only from about April on (the next run logs the exact date).

The backfills run for several weeks. Open for Step 4: the board's refresh cadence (the
freshness rule's maximum age is 60 min, but the live run is once a day). The stage rule is
settled (#61, lucky losers #63).

- OddsPapi feed with a **start-time-aware freshness rule**: a price is actionable only if
  the snapshot is recent **and** the match has not started. Started fixtures leave the
  live board.
- Keep the first-seen (opening) line and the last pre-start line for each fixture.
- **Closing prices (open item, deferred by the user 2026-10-12).** The September 2026
  OddsPapi backfill covers fixtures from 2026-01-02 to 2026-09-01 only (13,227 with full
  odds histories, including closing prices for Pinnacle, BetRivers and DraftKings). Nothing
  covers 2026-09-01 to 09-13. The daily feed since 09-13 saves snapshots, but the last
  pre-start snapshot is a median 5.6 h before the start (16% within 1 h), so it is not a
  closing price. Choose a daily after-the-fact capture instead of another bulk backfill:
  (a) a small daily OddsPapi historical pull for yesterday's priced fixtures, (b) Kalshi
  candles after settlement (already planned), (c) tennis-data.co.uk closing odds (tour
  events only). Check OddsPapi quota and Actions minutes before choosing.
- **Margin removal (de-vig), user decision 2026-10-13.** One function turns a book's prices
  into no-vig probabilities, with a setting per book on one scale (Box-Cox λ: 0 =
  multiplicative, 1 = additive/Shin, about 1.5 = power). It replaces the three current
  copies (`historical_market_mapper`, the app's `no_vig_probs`, and the cross-book average
  in `build_v5_market_board_input`) and the two copies of the BET/LEAN rule
  (`v5_live_market.signal_row`, the app). Prompted by vigged.com's study of 725,000 closing
  prices (Pinnacle tennis fits λ ≈ 2.0 [1.5, 3.1]; Bet365 on the same matches ≈ 1.2), which
  is not adopted as-is: its tennis data ends in 2019 and has no Challengers.
  - **Measure on our data** before the sealed period: 2026 OddsPapi closing prices to
    Sept 1 (Pinnacle, BetRivers, DraftKings), by men's tour, women's tour and Challengers;
    plus tennis-data.co.uk (Pinnacle and Bet365, free) once the domain is allowed.
    Fit λ per book on closing prices and again 4–8 h before the start; earliest 60% fit,
    latest 40% test; log loss with paired-bootstrap 95% intervals and reliability by
    price bucket; multiplicative and power reported alongside.
  - **Cautious edge rule (approved):** an edge is judged against the least favourable of
    the multiplicative, additive and power no-vig probabilities for the side being bet,
    so the method choice can never create an edge. Built into the same function.
  - Exchanges (Kalshi, Polymarket): midpoint for fair price; the price paid plus fees for EV.
- Kalshi trades and 1-minute candles, one daily pull after settlement (≤ 3 min); order-book
  depth only inside existing runs. Budget entries added to `v5_actions_budget.py`.

### Step 4. Model: leak-free baseline and one pricing function

- Review and merge PR #36 (fatigue_v1, parity/leak tests, `v5_model_guard.py`). Merged 2026-10-17.
- **Baseline built (2026-10-17):** `v5_baseline_elo.py`, leak-free surface Elo keyed by
  `player_id`. 2026 out of sample: log loss 0.626, against 0.629 for the current engine's
  baseline and 0.596 for the Pinnacle close (docs/experiments/2026-10-17-baseline-elo.md).
  Not yet read by production; the pricing function (next) uses it.
- **Pricing function built (2026-10-18):** `v5_pricing.price_fixture` (resolution, baseline
  Elo with the 18-match minimum, stage label, live quotes with the freshness rule, cautious
  edge per execution book). A replay of 2026-10-06 to 10-12 priced 165 of 309 fixtures (58
  with a player we have no history for, 80 thin, 5 unresolved, 1 unrated).
- **4g-1 (2026-10-18):** the daily batch and the app's override run call `price_fixture`
  (one `PricingContext`); the app's edits are saved to `master_schedule/overrides.csv`;
  only the moneyline is modelled. 4g-2 (ratings refresh, Matchup Lab, Model Health) and
  4g-3 (delete the old engine) follow.
- Production probability = leak-free baseline (Elo + surface). `v5_workload_features`
  is removed from every path. fatigue_v1 enters only after it passes its own
  out-of-sample gate against this baseline, with the market benchmark reported.
- **Fixtures resolve through `v5_fixture_resolution`** (edition, court, best-of, player ids).
- **Stage is a label, not a filter** (user decision 2026-10-17, replacing "not priced" of
  2026-10-16): every fixture is priced; fixtures labelled qualifying stay out of official
  recommendations until the model is measured on qualifying results (Kalshi settles some
  from August 2026; TennisMyLife has ATP qualifying only). `v5_fixture_stage.py` infers the
  stage, since OddsPapi has no round: Kalshi's round text, then the edition's calendar by
  level and who already played. It keeps 99.5% of Challenger and 97.6% of WTA main draws
  (docs/experiments/2026-10-17-fixture-stage.md).
  The same change removes every old lookup and its callers, tests and workflows:
  `v5_tournament_authority` (+ `v5_tournament_challenger`, the two diagnose scripts and the
  `v5_tournament_authority` / `v5_tournament_challenger` workflows, `tournament_authority.csv`),
  `v5_master_schedule_context` (+ `tennis_master_schedule.csv`), `v5_tournament_context_registry`
  and the name-keyed override path in `v5_context_transaction`, `v5_player_identity`
  (+ `player_aliases.csv`), and the app override run's own player matcher. Ratings move to
  `player_id` (model check first). `v5_tournament_registry` (historical venue coordinates for
  travel and weather features) goes with the context model if Step 4 retires it, or is
  rebuilt from the schedule if a context feature passes its gate.
- **One function** prices a fixture from (fixture, warehouse, overrides, ratings). The
  daily batch and the app override run both call it. Parity test: with no overrides,
  the override run reproduces the frozen forecast exactly.
- The model guard runs before anything is frozen or published: extreme model-vs-market
  gaps and wide component disagreement block a price (the Hurkacz case in the inventory).

### Step 5. Pricing, ledger, settlement, performance

- **Pre-rebuild bets are not evidence (owner decision 2026-10-13).** New official
  recommendations are paused (`production_switches.json`, fails closed when missing)
  until this step ships; prices, frozen forecasts and results keep being collected. The
  existing `official_recommendations.csv` rows are kept as they are (never rewritten) and
  labeled pre-rebuild in reports; no claim of edge or ROI rests on them.
- **Re-simulate history with the rebuilt engine.** Walk forward through past fixtures in
  time order, pricing each from as-of data only (ratings, schedule, overrides and market
  prices available before the start), through the same pricing function the daily batch
  uses. Fixtures before the sealed period are a backtest; from 2026-10-13 on they are the
  forward test and are never used for tuning.
- Turning recommendations back on is a change to `production_switches.json` in its own PR,
  after the rebuilt engine passes its gate.

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
- **D6. Editing the master schedule.** Generated by code from the sources above, then
  reviewed and finished by the user in a spreadsheet and saved as "CSV UTF-8" (the paste
  of 2026-10-12 shows Excel's non-UTF-8 export garbling accents). Is a spreadsheet the
  way you want to edit it, and which 2026 calendar should be the source for dates and
  categories (the official ATP/WTA calendars, or your own sheet)?
- **D7. Filling location columns automatically.** Coordinates, altitude and IANA time zone
  can be filled from Open-Meteo's free geocoding API (the repo already uses Open-Meteo for
  weather). It needs `geocoding-api.open-meteo.com` allowed in this environment. Ball,
  CPI and notes stay manual.
- **D5. Commits already on the session branch.** Six commits (season-year rollover,
  workflow triggers, budget model, test fixes). Keep them as the first PR, or fold them
  into Steps 1–2?

## Decisions recorded (user, 2026-10-12)

| # | Question | Answer |
|---|---|---|
| Plan | Approve the rebuild plan | Approved |
| D1 | Where the shared daily warehouse lives | **GitHub release file**, downloaded by the app at startup with a read-only token in Streamlit secrets. The app runs on Streamlit Community Cloud for now; a future standalone app can read the same file |
| D2 | Close PRs #28, #30, #31, #32 and delete stale branches; review #36 in Step 4 | Yes |
| D3 | New raw OddsPapi history outside git | Explained (bulk backfills should be rare once closing prices are captured daily, Step 3); rule stands for future backfills |
| D4 | One branch and PR per step, CLAUDE.md names | Yes |
| D5 | Existing session-branch commits | Split into PRs |
| D6 | Maintaining the master schedule | User maintains it in Excel a few times a year or when needed; **the system must raise flags when an update is needed** (Step 2) |
| D7 | Fill coordinates, altitude, time zone from Open-Meteo geocoding | Yes; domain allowed 2026-10-12 |
| Spec | Tournament identity spec | Approved 2026-10-12. Ball/CPI columns are filled by the user later; they are optional inputs |
| Spec Q2 | Team events | Keep in the schedule so fixtures resolve; never priced |
| Spec Q3 | WTA 125 | In the schedule and matching now; pricing decided later |
| Tournament spec A | TennisMyLife ids split by week; confirmation by shared matches | Approved 2026-10-13 |
| Players | Player identity spec (2026-10-13): our own player id, alias tables proven by results, no silent new players; ratings move to the id after the model check; same name + different country kept separate | Approved 2026-10-13 |
| De-vig | One margin-removal function, λ per book measured on our data; cautious edge rule | Approved 2026-10-13 (Step 3) |
| Data | tennis-data.co.uk (free Pinnacle/Bet365 closing prices) | Approved 2026-10-13; the domain must be allowed in the environment |
| Step 3 | Bet365 history for the stored January–August fixtures, re-pulled from OddsPapi in the same oldest-first queue as the gap backfill; Kalshi as the second results source, cross-checked against TennisMyLife | Approved 2026-10-16 |
| Step 3 | Market data layer design; probe run first (done; findings in docs/experiments/2026-10-16-step3-market-source-probe.md) | Approved 2026-10-16; old engine's daily heavy forecast paused until Step 4 (the board is unused; #54) |
| Results | Third results source: the last in-play prices (middle rule); matches ended before two completed sets and walkovers are void for measuring the model; bets settle by each book's own rules | Approved 2026-10-17 |
| Step 4 | Minimum history for a model price: both players need at least **18 rated matches** in the baseline Elo; below that the pricing function gives no model price (reason "thin history"). Chosen on January–June 2026, checked on July–October 12 (docs/experiments/2026-10-17-baseline-elo.md) | Approved 2026-10-18 |
| Step 4g | Switch production to the pricing function in three PRs (batch and override run; ratings refresh and app; delete the old engine). Set and game score predictions are dropped until a score model passes its own gate against the baseline; Matchup Lab stays, priced by the pricing function (match winner only); weather, travel and venue features are deleted and return only if one beats the baseline | Approved 2026-10-18 |
| Approach | Build toward the finished state; no fixes "for today" | User direction 2026-10-13 |

Sheet notes from the user: a Men/Women column will be added; WTA end dates are not in the
official WTA calendar, so the code keeps assuming them (labeled) and can replace them with
the observed last match date once an event finishes.
