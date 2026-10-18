# Leak-free baseline Elo on our player ids (2026-10-17)

`v5_baseline_elo.py`; measured by `scripts/measure_baseline_elo.py` (output
`docs/experiments/data/baseline_elo.json`). Rebuild plan Step 4: the production probability
becomes a leak-free Elo + surface baseline, keyed by our `player_id`; later model changes
must beat it out of sample, with the market reported next to every number.

## What changed against the current engine's Elo

| | Current engine (`build_v5_states.py`) | This baseline |
|---|---|---|
| Order of updates | `tourney_date` + file order: a first-round match can see later rounds of the same event (CLAUDE.md "no leakage") | `v5_fatigue_features` rules: rounds in order, same round concurrent, other events only once their last week is past |
| Player key | name string | our `player_id` (registry), TennisMyLife id otherwise |
| Unknown player at pricing time | quiet 1500 | raises; the match count travels with every rating |
| K | fixed 28 | shrinks with experience: 0.6 × 250 / (n + 5)^0.4 (about 51 at 10 matches, 23 at 100) |
| Surface blend | 0.65 surface | 0.2 surface (chosen on 2025) |
| Walkovers | counted | neither priced nor rated |

## Method

- Data: the files production reads (`.v5_history_cache` 2010–2025 and the current season),
  196,000 matches, 6,031 players, every player linked to a registry id.
- Settings chosen on 2025 log loss only, from a grid of K scale (0.3, 0.45, 0.6, 1.0) and
  surface weight (0.1, 0.2, 0.3, 0.5): best K 0.6, surface 0.2 (inside the grid; 2025 log
  loss 0.6389 against 0.6455 for the first default of 1.0 and 0.5). The newcomer rating
  cancels out (everyone starts at the same value), so it was not tuned.
- Test: 2026 matches from events that started before 2026-10-06, dated before the sealed
  period (2026-10-13). Nothing from 2026 was used to choose anything.
- Current engine: its accepted baseline (serve/return + Elo, calibrated on 2025) for the
  same matches, from `v5_*_walkforward.csv` (joined by names and date). Its Elo uses the
  old ordering. The full context stack has no historical record to compare.
- Market: Pinnacle close (not stale), de-vigged with its measured lam 1.5, joined to the
  match by our two player ids and the event window.

## Result (2026, out of sample; log loss, lower is better)

| Sample | n | This Elo | Current engine | Market (Pinnacle close) |
|---|---|---|---|---|
| All 2026 matches | 12,192 | **0.6262** | 0.6288 | – |
| With a Pinnacle close | 7,132 | 0.6288 | 0.6296 | **0.5964** |

Differences, paired bootstrap 95% intervals:
- this Elo minus current engine, all matches: −0.0026 [−0.0053, +0.0002];
- this Elo minus market: +0.0324 [+0.0271, +0.0377];
- current engine minus market: +0.0332 [+0.0277, +0.0386].

By family (matches with a Pinnacle close):

| | n | This Elo | Market |
|---|---|---|---|
| ATP | 2,030 | 0.619 | 0.600 |
| Challenger | 3,731 | 0.636 | 0.599 |
| WTA | 1,371 | 0.624 | 0.583 |

By the less experienced player's rated matches:

| | n | This Elo | Market |
|---|---|---|---|
| fewer than 10 | 802 | 0.618 | **0.529** |
| 10–29 | 1,069 | 0.643 | 0.603 |
| 30–99 | 1,885 | 0.627 | 0.596 |
| 100 or more | 3,376 | 0.628 | 0.611 |

## Reading

- The leak-free Elo is at least as good as the current engine's baseline (better by 0.0026,
  the interval just touching zero) while being simpler, leak-free and keyed by our ids. It
  becomes the baseline every later change must beat.
- Both are far behind the market: 0.032 of log loss. The biggest gap is where our data is
  thinnest: when one player has fewer than 10 rated matches the market knows far more
  (0.529 vs 0.618), and the gap is smallest for experienced players (0.017). The pricing
  function's minimum history (fail closed) and better inputs for newcomers (ranking, ITF
  and lower-tier results we do not have) are where the next gains are.
- Calibration is fine (model guard: worst bucket z = 2.3, under 3).

## Minimum history (user decision 2026-10-18: 18 rated matches)

A model price needs both players to have a rating built on enough matches (fail closed).
The threshold was chosen on January–June 2026 and checked on July–October 12, on the
matches that also have a Pinnacle close. "Gap" = this Elo's log loss minus the market's on
the same matches.

| Minimum (less experienced player) | Priced, Jan–Jun | Gap, Jan–Jun | Priced, Jul–Oct 12 | Gap, Jul–Oct 12 |
|---|---|---|---|---|
| none | 100% | 0.0319 | 100% | 0.0343 |
| 10 | 89.6% | 0.0253 | 85.5% | 0.0250 |
| 12 | 88.0% | 0.0250 | 83.3% | 0.0231 |
| 14 | 86.3% | 0.0243 | 81.7% | 0.0186 |
| 15 | 85.3% | 0.0243 | 80.9% | 0.0176 |
| 16 | 84.7% | 0.0238 | 80.0% | 0.0176 |
| 17 | 83.9% | 0.0234 | 79.0% | 0.0174 |
| **18** | **83.2%** | **0.0232** | **77.9%** | **0.0164** |
| 19 | 82.5% | 0.0235 | 77.2% | 0.0162 |
| 20 | 81.8% | 0.0232 | 76.3% | 0.0176 |

Matches where a player has 10–19 rated matches are clearly worse than the rest (gap about
0.05 against 0.02); the gap falls steadily up to 18 and then stops improving, in both
halves. Each single step moves only 40–50 matches, so neighbouring thresholds are within
noise; the trend is clear. This is a safety rule, not an edge: the baseline is behind the
market at every threshold.

## Model guard (`python v5_model_guard.py`, 2026 test predictions)

- PASS: orientation, too good to be true, hidden answer, missing history, drift.
- WARN: calibration (worst bucket z = 2.3), no feature timestamps (none are used).
- FAIL "backwards segments": 13 of 299 events score better flipped. If the model were
  exactly right, 3–12 would by chance (200 simulations); the 13 are Challengers and small
  events where the weaker player had a median of 8–33 rated matches (overall 70), and the
  market also scored badly on several. Read as thin information, not swapped players.
- A first guard run with our ids as player names failed "player1 == player2": the guard
  folds names to letters, so "M-003344" and "M-001401" both become "m". Run it with names.

## Limits

- The current engine's walk-forward Elo uses the leaky order, so its numbers are, if
  anything, flattered; the comparison is still close.
- Surfaces come from the TennisMyLife files for history; live fixtures take theirs from the
  master schedule (`v5_fixture_resolution`). Same labels, different source.
- Best-of-five, retirements and margin of victory are not used yet; candidates for later,
  each against this baseline.
