# Fair Price to Market Making: Program Roadmap

Date: 2026-10-12
Status: **DRAFT — pending user approval.** Not binding until approved in chat.
Category: Model Profitability (program-level), with Production Reliability prerequisites.
Subordinate to: `PROJECT_MANDATE.md`. Builds on (does not replace): `2026-09-01-full-context-tennis-model-design.md`, `2026-09-21-market-aware-decision-system-design.md`, `2026-09-08-self-functioning-production-pipeline-design.md`.

## 1. Goal

Build **one fair-price engine** for tennis match winners that:

1. beats the market on a sealed, forward period (better Brier / log loss than the sharp close in at least one tradeable segment), then
2. makes money as a **taker** at prices the user can actually get (positive closing-line value after fees), and later
3. powers **market making** on venues that allow resting orders (Kalshi first), where profit comes from fair price + spread capture − adverse selection − fees.

The same engine feeds the taker strategy, market making, and the paid product. There is no separate "market-making model"; a market maker is a fair-price engine plus a model of which fills are toxic.

## 2. Where we are (evidence, 2026-10-12)

- **Live record:** 1,007 official picks, 436 W / 526 L, ROI −0.40%, median price +118, 692 of the picks on underdogs. The +121 to +200 band runs at −6.9% ROI. That is consistent with no real edge plus a favorite-longshot bias toward underdogs.
- **Backtest vs live gap:** the walk-forward showed Brier ≈ 0.21 / ~80% winners, but live did not hold up. The root cause has been found: `v5_workload_features.py` orders matches by `tourney_date` (the tournament start date) and then by file order. Because the source files list the winner first, workload features leak the result in history and flip sign live. Train/serve drift does the rest.
- **Benchmark gap:** the base model's Brier is about 0.225 against the market's 0.209 on the same matches. The model is not currently better than the market on its own.
- **Leak-free replacement exists:** `fatigue_v1` (PR #36) shows parity 377/377 between history and live, 0 out-of-order pairs in about 470k clock checks, and leak-signature AUCs inside the safe band.
- **CI was hiding failures:** 21 pre-existing test failures (retired court tests, workflow drift, one performance-report robustness bug, and a few broken tests) are now visible (PR #37).
- **Holdout contaminated:** 2026 results have already been used for model selection, so they are no longer a clean test set.

## 3. Principles (apply to every phase)

1. **The market is the benchmark, not the enemy.** Every model claim is measured against the no-vig sharp price at the same timestamp.
2. **Executable prices only for money claims.** A Pinnacle edge is information, not profit. Profit is measured at Bet365 / BetRivers / Kalshi / Polymarket / Novig prices, including fees.
3. **One feature at a time, out of sample.** A feature enters only if it improves chronological OOS log loss over the current engine on data it never saw.
4. **Same code for history and live.** A feature that cannot be computed identically at serve time does not exist.
5. **Fail closed.** Unknown players, unknown events, stale prices, and missing timestamps produce no price, never a default.
6. **Gates are fixed before the data is seen.** Thresholds and metrics for each gate are written down before the evaluation window opens.

## 4. Phases and gates

### Phase 0: Foundation (now)

Goal: a trustworthy pipeline and a clean evaluation clock.

- Get CI green: triage the 21 failures (retire dead court tests with a spec note, fix workflow drift, fix the `_clean` robustness bug, repair the broken tests).
- Make the leak/parity tests and `v5_model_guard.py` **required checks** on any PR that touches features, models, or production.
- Switch production probabilities to the leak-free baseline (Elo + surface, plus `fatigue_v1` only after it passes its own gate). Label the old workload features as retired.
- **Seal a forward period** starting on the date this spec is approved. No model selection, tuning, or threshold choices may use results from inside it until the Phase 2 gate evaluation.
- **Start collecting data that cannot be recovered later:**
  - Kalshi tennis order books (top of book plus depth) and trades, on a fixed cadence, stored raw.
  - Raw OddsPapi snapshots, including the **first available (opening) line** and the last pre-start line for each fixture.
  - Match start/end timestamps from OddsPapi fixtures.

**Gate 0:** CI green on main for 7 consecutive days; guard and parity checks required; collectors writing at least 95% of scheduled snapshots for 14 days.

### Phase 1: Honest benchmark

Goal: learn where, if anywhere, the market is beatable before building more model.

- Measure Pinnacle close efficiency (calibration, favorite-longshot bias) from tennis-data.co.uk history and OddsPapi 2026, broken down by tour/tier, surface, price range, and (2026 only) time before start.
- Measure whether the leak-free V5 probability adds information beyond the market: fit `logit(p_final) = a·logit(p_market) + b·logit(p_v5)` chronologically; report `b` and its interval by segment.
- Measure the gap between opening and closing lines (how much the market learns, and when).

Output: a ranked list of **candidate segments** (for example, Challenger qualifying or early rounds of lower-tier events) where the market is least efficient. If no segment shows a reliable `b > 0`, Phase 2 focuses on the segments with the largest open-to-close movement.

**Gate 1:** written segment report reviewed and approved by the user; candidate segments and Phase 2 metrics fixed in writing before Phase 2 starts.

### Phase 2: Fair-price engine

Goal: a calibrated probability that beats the close in at least one candidate segment.

- Layer 1, base strength: Elo / surface Elo with a cold-start rule (1500 plus uncertainty), leak-free.
- Layer 2, fatigue_v1, then one context feature at a time (travel, injury/retirement history, motivation proxies such as ranking-point defence or home event). Each must pass the out-of-sample rule in §3.
- Layer 3, combination with the market: a calibrated blend of model and market inputs available at decision time (opening line for early decisions, current line later), per the market-aware design spec.
- Bridge for missing historical timestamps: a frozen round→day schedule estimator calibrated on 2026 clock data and used identically in history and live; an exact-rest-hours residual layer is allowed on 2026+ data only.

**Gate 2:** on the sealed forward period, the engine's log loss beats the no-vig sharp close in at least one pre-declared segment, with a bootstrap interval that excludes zero, and at least 300 matches in that segment. If it fails, return to Phase 1 with the evidence. Do not tune on the sealed period.

### Phase 3: Taker validation (shadow, then small stakes)

Goal: prove that the edge survives real prices and fees.

- In shadow mode, freeze each decision with its price, venue, and timestamp; track closing-line value (CLV) against the sharp close.
- Model fees exactly, including Kalshi taker fee = ceil(0.07 · C · P · (1 − P)) per order.
- Selection policy and thresholds are fixed before the window opens.

**Gate 3:** at least 500 shadow decisions with mean CLV > 0 after fees (interval excludes zero), and no segment-level calibration failure in the guard. Only then do small real stakes start.

### Phase 4: Market-making research (offline)

Goal: learn whether quoting around the fair price is profitable on Kalshi.

Uses the order-book and trade data collected since Phase 0.

- Fill model: probability a resting quote at distance *d* from fair fills, by segment and time to start.
- Adverse-selection model: price move after a fill (markout at 1 min, 5 min, close). Toxic flow = fills followed by moves against us.
- Simulator: quote both sides around the fair price with an inventory skew and position limits; include maker fees where they apply (some sports markets charge 0.0175 per contract); report P&L, inventory risk, and worst day.
- In-play is out of scope until the pre-match simulation is positive.

**Gate 4:** simulated net P&L positive on the sealed collection window after fees and adverse selection, positive markouts on average, and drawdown within limits the user sets.

### Phase 5: Live market making (small)

- Small size, hard position and daily-loss limits, and kill switches (stale fair price, stale book, feed gap, guard failure, start-time reached).
- Compare live fills to the Phase 4 simulator weekly; stop if they diverge beyond a pre-set tolerance.

**Gate 5:** 30 trading days within limits with live performance inside the simulator's interval before any size increase.

## 5. Data requirements

| Data | Source | Starts | Why |
|---|---|---|---|
| Match results 1968–today | TennisMyLife | have | Base strength, fatigue, history |
| Fixture timestamps (start/true start/end) | OddsPapi | 2026 | Clock validation, rest hours |
| Opening + closing lines | OddsPapi raw snapshots | Phase 0 (opening lines are not recoverable later) | Benchmark, CLV, early-decision inputs |
| Historical closes + results | tennis-data.co.uk | have | Market efficiency history |
| Kalshi order books + trades | Kalshi API | Phase 0 | Fill, toxicity, and MM simulation |
| ITF / WTA 125 | none yet | gap | Not priced until a source exists |

## 6. Out of scope for this roadmap

- In-play models (revisit after Gate 4).
- Spread and total markets (stay under the market-aware spec; not a gate here).
- Any change to the official recommendation ledger semantics.

## 7. Open questions for the user

1. Bankroll and loss limits for Phases 3 and 5.
2. Whether Polymarket / Novig order-book collection should start alongside Kalshi in Phase 0 or wait.
3. Budget for a paid data source for ITF / WTA 125, if those tiers turn out to be the least efficient.
