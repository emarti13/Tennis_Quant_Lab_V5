# First-server effect on totals and handicaps (Mohammadi 2026, arXiv 2605.04867)

Status: research. Nothing here is read by production. Data before the sealed period only
(matches to 2026-10-12, fixtures with true start before 2026-10-13).
Code and full numbers: `research_tests/first_server/` (`fs_core.py`, `build_fs_table.py`,
`build_market_table.py`, `run_fs.py`, `results.json`, tests in `test_fs_core.py`).

Roadmap gate: Phase 1 (taker edge search). Benchmark: Pinnacle de-vigged close, plus
BetRivers, DraftKings and Bet365 close prices for execution.

## What the paper claims
Under iid points the match winner's probability does not depend on who serves first, but the
expected total and margin do (by up to about 0.4 games; at most about 9 points on P(over 19.5)).
Its empirical part says matches where the loser served first ran 1.3 to 1.8 games longer than
the model predicted (Table 2), and that stronger players choose to serve first (Table 4, odds
ratio 7.6 ATP). It also says bookmakers never update totals and handicaps after the toss.

## Method
- **Inference.** Serve alternates across the whole match and a tiebreak takes one slot, so the
  first server owns the odd slots. The two hypotheses differ exactly when
  (total games mod 2) != (tiebreaks in sets the first server opened − tiebreaks in the
  others). The result is read from service-game counts, or from break counts when those are
  missing. Determined: ATP 46.5%, Challenger 45.8%, WTA 45.1% (the paper: 42 to 45%). The two
  routes agree on 99.0% of 76k matches where both apply; 0.1% fit neither (dropped).
- **Model.** Exact DP for the iid point model (games, 7- and 10-point tiebreaks,
  final-set rules per Slam and year), conditioned on the first server, tracking the
  determinability event. Checked against point-by-point simulation and the paper's
  identities; it reproduces the paper's numbers (max shift 8.8 points on P(over 19.5)
  at (0.70, 0.59); margin up to 0.36 games).
- **Pre-match inputs only.** Serve-point probabilities are the leak-free Barnett-Clarke
  values from `research_tests/features` (event ordering with exact Elo parity); the
  favourite comes from that model. For 2026 markets, the serve level comes from that history and
  the gap is solved from Pinnacle's de-vigged moneyline.
- **The selection matters.** Whether the server can be inferred depends on the score, and so
  on who served: at (0.70, 0.60) it is inferable in 58% of matches when the stronger player
  serves first and 34% when the weaker one does. Every comparison below is against the
  model's prediction under the same selection.

## Results

### 1. The paper's Tables 2 and 4 are mostly a selection artifact
Residual (games over the iid model, in-match serve shares as in the paper), determined
matches:

| Tour | Winner served first | Loser served first | Gap | Gap predicted by iid with a fair toss |
|---|---|---|---|---|
| ATP | +0.11 | +1.91 | 1.80 | 1.70 |
| WTA | +0.54 | +1.54 | 0.99 | 0.77 |
| Challenger | +0.25 | +1.67 | 1.42 | 1.43 |

Conditioning on the winner plus inferability produces almost the whole gap with no special
effect. Likewise the share of determined matches where the winner served first is 64.4% for
ATP; the fair-toss model predicts 62.6% from the selection alone.

### 2. The effect itself is real and about the size the model predicts
Pre-match favourite vs underdog served first, 72,155 determined matches 2010-2026. The slope of
the realised total on the model's predicted server shift is 1 if the shift is as predicted
and 0 if there is no shift:

| Slice | Totals slope | Margin slope | Placebo (random server) |
|---|---|---|---|
| All | 0.84 ± 0.05 | 1.22 ± 0.02 | 0.06 ± 0.05 |
| ATP / WTA / Challenger | 0.91 / 0.69 / 0.74 | 1.31 / 1.16 / 1.15 | ≈0 |
| Win-probability gap < 0.15 | 0.44 ± 0.12 | 1.21 | 0.07 |
| Gap ≥ 0.30 | 1.14 ± 0.09 | 1.49 | −0.04 |
| Best of 5 | 1.23 ± 0.20 | 2.21 | −0.11 |

(± is one standard error.) Knowing the server raises the exact-total log likelihood by
0.003 per match (SE 0.0004).

### 3. Who serves first: a small, real tilt toward the favourite
Full likelihood (inferable matches give the server; the others contribute through the score's
likelihood under each server), P(A serves first) = sigmoid(β · Elo logit):
β = 0.12 ± 0.008 (naive fit on inferable matches only: 0.34). That puts a 75% favourite at
53.3% to serve first (ATP 54.5%, WTA 54.9%, Challenger 50.5%, so zero there). Stable out of
sample: β = 0.13 for 2010-21 and 0.10 for 2022-26. The paper's "odds ratio 7.6" is not supported.

### 4. Strength-weighted prior in the totals model: no measurable value
The prior (β fit on 2010-2021) moves pre-match expected totals by a mean 0.0015 games.
History 2022-2026: exact-total log likelihood +0.0003 per match. 2026 Pinnacle main totals
(6,458 settled): log loss 0.6921 with and without the shift (difference 0.0000). It is a
real effect but worth nothing pre-match: the toss is close to a coin flip.

### 5. Markets (2026, 7,934 fixtures joined, 3,680 with the server determined)
- **Does the close price the toss?** Partly, at Pinnacle and BetRivers. Pinnacle's close is a
  median 4.8 minutes before the first ball (after the toss). From its 1-hour price to its close,
  the main-line fair probability moves toward the server shift: totals slope 0.58 ± 0.07,
  handicaps 0.23 ± 0.02 (controlling for the realised result; placebo server 0.08 / 0.00).
  The open→1-hour window, before any toss, shows nothing (−0.14 ± 0.23, −0.02 ± 0.04).
  BetRivers: totals 1.07 ± 0.16, handicaps 0.14 ± 0.03. DraftKings: no measurable move
  (0.09 ± 0.29, −0.03 ± 0.06; small samples). **The paper's "never updated after the toss" is
  false for Pinnacle and BetRivers**; most of the handicap shift is left in the price.
- **Model check against the market.** On inferable 2026 fixtures the realised outcomes carry the
  predicted shift relative to Pinnacle: totals slope 1.32 ± 0.26, handicaps 0.91 ± 0.08.
- **Post-toss bets at the close** (market fair + model shift, any EV > 0):
  - Realised returns can only be measured on inferable fixtures, and that selection is
    correlated with the result. Handicaps at Pinnacle: 712 bets, +18.3% realised (SE 3.4%)
    against a model expectation of +21.5% for the same selection. That checks the model; it
    is NOT an achievable return.
  - The return for a bettor who sees every toss can only come from the model: handicaps at
    Pinnacle, bets on 22.5% of fixtures at +2.9% expected value per bet; BetRivers 17.5% at
    +3.4%; DraftKings 10.8% at +3.6%; Bet365 (106 fixtures) +4.9%. Totals: bets on 0.1 to
    3.6% of fixtures, +0.6 to +5.0% (DraftKings 991 fixtures, +5.0%). These overstate a little
    at Pinnacle and BetRivers, which already move part of the way at the close.

### Side finding
Given the moneyline, the iid model runs long: 2026 server-blind expectation 24.6 games against
23.1 realised (Pinnacle's main line averages 21.6). Totals from the iid model need a level
correction; only the server shift is taken from it here (read at the line on the same quantile
as the market's).

## Verdict
- Pre-match first-server prior: closed. A real effect, worth nothing pre-match.
- **Post-toss handicaps (and DraftKings totals): unresolved, plausibly positive.**
  The ingredients are measured (the shift is real, about the size predicted, and largely
  unpriced at the close), but the return cannot be measured on past data without the server
  for every match. Next step: a forward paper test that records the first server live and
  prices handicaps between the toss and the first point (needs a free live score feed that
  shows the server, and books that still take pre-match bets in that window; neither is
  established here). Kalshi has no handicap or totals match markets in our data.

## Kaggle bookmaker totals (added after the download worked)
See `2026-10-21-kaggle-odds-edge-search.md`: on 2014-2025 Bet365, Ladbrokes and Unibet totals
the realised totals carry the server shift (slope 0.86 to 0.94), the books do not move between
open and close with the server, and at their main lines the shift is too small to beat the
margin. The file's handicaps are unusable, so the handicap question stays open.
