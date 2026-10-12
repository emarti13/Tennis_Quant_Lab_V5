# fatigue_v1: leak-free fatigue / schedule features (research candidate)

**Category:** Research + Model Profitability (PROJECT_MANDATE §7)
**Status:** Candidate only. Not wired into any production workflow, and it changes no production artifact.
**Promotion gate:** it may replace the workload inputs of the context layer only after a retrained model using it beats the Elo/accepted baseline on untouched out-of-sample data, with every test below passing.

## Why

The production handoff audit (2026-10-12) found that the full-context layer degrades a sound Elo/baseline model. The largest coefficient, `ctx_matches_3d_diff`, comes from `v5_workload_features.py`. That module orders a player's same-date matches by original row order, which comes from hashed match ids. TennisMyLife dates are tournament-start dates in most files, so every match in an event shares one date, and a first-round row could count the same player's later rounds.

Rebuilding the feature exactly as the pipeline does on 2025 data:

| Ordering | Winner had MORE "recent matches" | Winner had FEWER |
|---|---|---|
| Pipeline (hash order) | 50% | 24% |
| True round order | 26% | 48% |

The leak flips the sign. In reality, more matches already played this event (often qualifiers) predicts *losing*, which matches the live over-rating of underdogs and qualifiers. The existing test `test_future_match_does_not_change_earlier_features` only appends a far-future match, so it never exercised same-date ordering.

## What fatigue_v1 does differently

- **Ordering uses only event, stage and round, plus week anchors.** It never uses row order or a raw date as a match day. A tennis week is the Monday-based week of (date + 2 days). Same-round matches never see each other. Qualifying comes before the main draw.
- **One feature function for history and live.** `LiveFeatures(history).features(fixture)` takes a market-board row and raises instead of silently defaulting: unknown or ambiguous player, ambiguous event, or a name mismatch while a player is still alive in a running event.
- **Reads the same files production reads.** `.v5_history_cache/*.csv` (`bootstrap_v5_history.py`) and `v5_results_ready/tennismylife_results.csv`. No second copy of the data.

Features (per player, plus `d_` differences):
- **This event:** `ev_matches_before`, `ev_quali_matches_before`, `ev_sets/games/minutes_before`, `prev_in_event_*`
- **Earlier events:** `weeks_since_prev_event`, `prev_event_matches/reached_final/won_title`, `events_last_4w`, `matches_last_4w/8w`, `layoff_8w_plus`
- **Injury proxies:** `retired_last_match`, `retired_or_wo_last5`
- **History depth:** `n_prior_matches`

QC flag (not a feature): `qc_conflict_weeks_8w`.

## Data defects found in the feeds and how they are handled

| Defect | Handling |
|---|---|
| Date meaning varies: per-match in 2026 ATP main draws and ongoing feeds, tournament-start elsewhere | Only week-level event anchors use dates; test proves both conventions give identical features |
| `tourney_id` reused (2026-416 = Munich in April **and** Rome Masters in May; 5 ids) | Split on internal date gaps > 10 days, before de-duplication |
| Same match under two ids (Munich 2026: 2026-308 and 2026-416) | Same players + round + week = one match (149 rows) |
| Overlapping files and main-draw rows inside the 2026 qualifying file | De-duplicated on (tour, event, round, players) |
| Same player under several ids (Khachanov KE29 / 106421) | Merged when name + nationality + birth date agree (274 ids) |
| Different players filed under one name ("Keegan Smith" ids from 4 countries) | Never merged; live picks a dominant id only if the others are tiny, recorded in `id_notes`, otherwise refuses |
| ~7% of player-weeks show two events in one week | Same-week events never see each other; flagged by `qc_conflict_weeks_8w` |

## Verification (audit bundle 2026-10-12, then repeated in the repo layout)

| Check | Result |
|---|---|
| Unit tests (hand-computed schedules, concurrency, walkovers, re-runs, loud failures, id splitting, identity merge) | all pass |
| Shuffle input rows | 0 differing cells / ~38.7k matches |
| Delete later events and rounds | 0 differing cells / ~22.9k earlier matches |
| Flip a match's own result | 0 differing values / 300 matches |
| Per-match vs tournament-start dates | 0 differing cells |
| Leak signature (within-event features must not favour the eventual winner) | max within-event AUC 0.445 |
| Parity: live code fed only pre-first-serve data, on real OddsPapi fixture strings, vs training row | 375/375 identical, 0 mismatched, 25 refused loudly |
| Ordering vs real OddsPapi start/end times (2026) | 0 of ~470k same-player pairs counted "before" when they happened after |
| Today's market board end to end | 103/104 fixtures built, 1 ambiguous player refused |

Reproduce:

```bash
python bootstrap_v5_history.py                       # once, builds .v5_history_cache
V5_FATIGUE_PARITY_N=400 python -m pytest tests/test_v5_fatigue_features.py -v -s
python diagnose_fatigue_ordering_vs_clock.py        # must report 0 leak-risk pairs
```

Or run the manual workflow **V5 Fatigue Features (research validation)**.

`v5_model_guard.py` is a model-agnostic report for any predictions file. It covers orientation leaks, too-good-to-be-true results, the hidden-answer signature, calibration, backwards segments, future-dated features, leaky features, train/live skew, drift, and version-to-version jumps.

## Known limitations

- TennisMyLife has no ITF or WTA 125 results, so recent load is undercounted for players active there.
- Rest is resolved at week level only. OddsPapi clock times exist from 2026 onward. Bridge plan: a frozen round-to-day schedule estimator, calibrated on 2026 clock data and used identically in history and live, plus a separate 2026+-only residual layer for exact hours, promoted only if it beats the base out of sample.
- Effects should be small. If a fatigue feature dominates a model again, treat it as a bug until proven otherwise.
