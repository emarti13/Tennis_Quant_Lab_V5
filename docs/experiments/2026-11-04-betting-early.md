# Betting early: do the signals get ahead of the close? (2026-11-04)

**Status:** exploratory. All data is before 2026-11-01.

**Test:** `research_tests/open_clv/run_open_clv.py`, pre-registered and pushed (`38e6c5a`) before any result.

**Why:** the user will not bet at the close. A signal the close already knows can still pay a bettor who acts earlier, if the price moves toward that signal's side between the open and the close.

**Prices:**
- **Open:** the Bet365 opening price, median overround 6.67%.
- **Close:** the "Betfair"-labelled sportsbook close, overround 3.16%.
- The Kaggle "Betfair" opening column is unusable (median overround 1.88; both sides near 1.01) and is not used.

**Sample:** 82,199 matches, 2016–25. Test years 2022–25.

**Inputs:** the same code as the incentives, travel, blend and scout tests, all sharing one orientation.

**Checks:** swap-source on the prices; planted edge (found −0.0022 vs −0.0024 planted); market null; known answers; orientation agrees across builds. All pass.

**Benchmark:** log loss on 2022–25 is 0.61465 at the Bet365 open and 0.60738 at the sportsbook close. The open is 0.0073 behind the close.

## 1. The signals predict how the line moves

**Move** = de-vigged close minus de-vigged open on the flagged side, in points. Ranges resample flagged players.

| flag | move 2016–21 | move 2022–25 | the close moves toward |
|---|---|---|---|
| hangover (finalist last event) | +0.80 (+0.44, +1.13) | **+1.34** (+0.97, +1.69) | the finalist |
| short rest | −0.34 | **−1.60** (−2.38, −0.82) | the rested opponent |
| layoff (returning player) | −0.54 (−0.86, −0.23) | **−1.13** (−1.72, −0.54) | the opponent |
| surface switch | −0.38 (−0.52, −0.24) | **−0.79** (−0.97, −0.61) | the opponent |
| venue (qualifier with matches at the venue) | +0.28 | **+0.78** (+0.47, +1.11) | the qualifier |
| defending | +0.86 | **+0.69** (+0.47, +0.89) | the defender |
| pre-Slam (top 30) | +1.15 | **+0.55** (+0.20, +0.91) | the top-30 player |
| wildcard | −0.28 | **−0.50** (−0.79, −0.22) | the opponent |
| qualifier | −0.10 | +0.54 (+0.35, +0.71) | the qualifier (sign flipped) |
| altitude | +0.13 | −1.18 (−2.23, −0.19) | the acclimatised player (sign flipped) |
| age gap | −0.22 pts per 5 years | −0.60 pts per 5 years | the younger player |

Most moves are significant, and they grow in 2022–25. The market prices fatigue, layoffs and surface changes **between the open and the close**, so these signals are worth more to an early bettor than to one at the close.

Season end, jet lag and the ranking bubbles do not move the line. Their edge at the close (season end and jet lag, about +10% realised in 2022–25) comes from results, not from line moves.

## 2. Bet365's opening margin is larger than the moves

| rule at the Bet365 open, 2022–25 | n | expected ROI from the close (CLV) | realised ROI | move toward the bet | CLV hit |
|---|---|---|---|---|---|
| blend, edge ≥ 2 pts | 834 | −1.6% (−2.4, −0.8) | **+6.5%** (−0.4, +13.1) | +1.79 pts | 63% |
| **PRIMARY** blend, edge ≥ 3 pts | 366 | −0.9% (−2.1, +0.3) | −0.2% (−10.1, +9.6) | +2.12 pts | 64% |
| blend, edge ≥ 5 pts | 71 | +1.8% (−1.1, +4.7) | −7.2% | +3.28 pts | 73% |
| layoff: back the opponent | 532 | −3.0% (−4.5, −1.5) | +1.4% | +1.13 | 59% |
| short rest: back the rested player | 97 | −3.2% | +6.6% | +1.60 | 70% |
| hangover: back the finalist | 1,128 | −3.8% | −6.1% | +1.34 | 63% |
| surface: back the opponent | 4,875 | −4.3% | −3.8% | +0.79 | 57% |

- **Control:** the open recalibrated alone finds no bets at a 2-point edge. Every blend bet comes from the signals.
- **What the blend does:**
  - against the open, log loss −0.00069 (−0.00111 to −0.00027), significant;
  - it closes about 10% of the gap from the open to the close.
- **Where CLV is short:** expected ROI from the close is just short of break-even. **Bet365's opening margin (6.7%) is about 3.5 points more per bet than a ~3% book's.**

## What this means

1. **The signals are real information.** The market adds them between the open and the close (moves of 0.5–1.6 pts per flag; blend picks move 1.8–3.3 pts toward the bet, 63–73% of the time). This is the opposite of a dead end: the signals predict where the price is going.
2. **At Bet365's opening margin, the move is a little too small to pay.**
   - At a book with a ~3% margin, the same bets would have an expected ROI from the close of roughly +2% to +5%.
   - This estimate takes away about 3.5% of margin; it is not measured, because we have no low-margin opening prices on file.
3. **So the edge is in where and when you bet.** It needs a venue with a low margin that is open early:
   - **Kalshi:** the fee is about 1.75 cents per contract at a 50¢ price, or a maker fee if you post orders;
   - **Novig / Polymarket, or a sharp book's early line.**

   The live Kalshi logger (pre-match quotes every 5 minutes since 2026-10-31) can measure the same moves on Kalshi going forward.
4. **Next steps:**
   - register the blend as a forward test on Kalshi, betting when the market opens and measuring CLV against the Kalshi close and Pinnacle;
   - measure Kalshi's opening spread and fee on the logged quotes.
