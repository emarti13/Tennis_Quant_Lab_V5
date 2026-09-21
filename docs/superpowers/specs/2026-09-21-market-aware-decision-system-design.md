# Market-Aware Decision System Design

## Purpose
Turn V5 from an independent tennis forecaster plus a raw-EV filter into a coherent decision system that preserves the independent tennis model, learns what the market knows, measures uncertainty in both, and only recommends wagers when the combined evidence supports a credible pricing error.

## Core principle
V5 predicts the match first. The market is treated as a second forecasting system, not as ground truth and not as an adversary. A separate decision layer learns when V5 adds information beyond the production market view. EV is a pricing test on a credible probability estimate; raw EV alone is never sufficient for BET.

## Non-goals
- Do not rewrite the existing winner, Elo, surface, form, court, altitude, state, or score-simulation models during this program.
- Do not ban favorites, underdogs, plus-money bets, or betting against the modal winner by arbitrary rule.
- Do not optimize thresholds by repeatedly searching historical ROI.
- Do not train live inference on a full-book feature set that production cannot afford to reproduce.
- Do not use bookmaker prices inside the independent tennis forecasting engine.

## System architecture

### 1. Independent tennis engine
The existing V5 predictive stack remains sportsbook-independent and produces raw match-win probability, expected game margin and margin distribution, expected total games and total distribution, state/context confidence, model/component agreement, model version/prediction timestamp, and data-quality/context flags. This is the canonical P_tennis_raw source.

### 2. Historical market reference
Historical OddsPapi data are normalized to one canonical observation per fixture_id × snapshot_utc × bookmaker × market_group × canonical_line × selection.

The research warehouse retains bookmaker, fixture/event identity, snapshot/start timestamps, market family, canonical line, selection/side, American/decimal price, paired opposite-side price when available, implied probability, de-vigged probability, vig/overround, main-line indicator if provided, time to match, and provenance.

Historical broad-book data are research/reference data. They are not assumed to be available in live production.

### 3. Production book subset
Because live OddsPapi credits are constrained, production will use the smallest bookmaker subset that retains the most useful market information.

Historical full-market data are used to evaluate candidate 1-, 2-, 3-, and 4-book subsets on fair probability, main line, market direction, closing probability, market dispersion, line movement, and executable pricing information.

The selected production subset must be the same subset used to construct market features during decision-model training. No train/serve mismatch is permitted.

#### Executable-book constraint
The decision system must distinguish **information books** from **execution books**.

- Pinnacle remains a high-value market-information candidate because it was intentionally chosen as the sharp reference book; its usefulness must still be measured historically rather than assumed.
- The user's currently executable sportsbook set is **Bet365 and BetRivers**.
- **Kalshi, Polymarket, and Novig** may also be executable venues when they list a compatible tennis market, but exchange/prediction-market prices, fees, liquidity, contract settlement, and line definitions must be normalized separately rather than treated as ordinary sportsbook quotes.
- DraftKings may remain useful as historical/reference information, but it is not currently an execution venue for the user.
- A production recommendation must never present an unavailable book's quote as the user's executable price.
- Research may use non-executable books to improve market-state estimation only when the resulting feature can be reproduced within the production data budget.
- Final execution pricing and reported actionable EV must be computed from an actually accessible venue. If no accessible venue offers the required market/line at a positive credible edge, the opportunity is not an actionable BET even if a non-executable reference book does.

### 4. Market engine
The production market model creates P_market, book count, market dispersion, sharp-anchor probability if justified by research, opening/current/closing probability where available, price age, line movement, and data-quality flags.

Market consensus and best executable price are separate concepts. Consensus is information; best price is execution.

### 5. Calibration and tennis reliability
Raw V5 probabilities are challenger-tested chronologically against existing calibration, no recalibration, logistic/Platt-type calibration, isotonic calibration, and beta calibration when dependency support is acceptable.

Selection is based on untouched chronological/OOS probability quality, not historical ROI. The chosen layer emits P_tennis_calibrated, reliability/uncertainty, and calibration metadata.

Reliability may use model agreement, player-history depth, state confidence, tour, surface, probability region, volatility, and context coverage, with shrinkage to avoid tiny unstable buckets.

### 6. Decision/meta model
A chronological meta-model learns when V5 contributes information beyond the production market.

Candidate inputs include P_tennis_raw, P_tennis_calibrated, P_market, signed/absolute disagreement, tennis uncertainty/reliability, market dispersion, component-model agreement, state confidence, data coverage, tour, surface, price/probability region, line movement, and time to match.

The model target is the actual match result for moneyline decisions. It produces P_decision, then receives independent chronological calibration. Interpretable benchmarks remain mandatory; complexity is accepted only if it survives later-period validation.

### 7. Market-specific opportunity engines
Moneyline, spread, and total are separate predictive targets.

Moneyline uses calibrated P_decision against the available market price.
Spread uses the calibrated game-margin distribution at the exact main line.
Total uses the calibrated total-games distribution at the exact main line.

Each engine computes raw edge, reliability-adjusted edge, EV from the decision probability, uncertainty-adjusted EV, and evidence that the true edge remains positive.

### 8. Selection policy
BET/LEAN/PASS/REVIEW are evidence tiers, not simple EV thresholds.

BET requires a credible edge after uncertainty and acceptable model/market/data reliability.
LEAN represents positive but weaker evidence.
PASS means no supported economic advantage.
REVIEW means reliability/data disagreement prevents a defensible automated decision.

Large model-market disagreement is not automatically stronger evidence. Extreme disagreement can increase uncertainty unless historical OOS evidence shows V5 is reliable in that region.

### 9. Execution
Opportunity selection happens before price shopping. The engine first identifies the market and line it wants to express, then selects the best currently available price among the affordable production books.

### 10. Audit and validation
Every frozen decision preserves raw/calibrated tennis probability, market probability, decision probability, uncertainty/reliability features, selected market/line, offered/selected price, bookmaker, signal, model/policy versions, close probability/line/price when later available, final result, and profit/loss.

Performance is evaluated on accuracy, Brier/log loss, calibration, margin/total calibration, units/ROI, closing-line value/movement, drawdown, favorite/underdog, probability/edge bands, tour, and market type.

## Research-to-production boundary
Historical all-book data are a teacher/reference set. Production inference may consume only market inputs that can be recreated under the live OddsPapi credit budget. Full-market consensus may evaluate the production subset but must never silently become a training feature unless it is also available live.

## Acceptance gates
1. Historical market warehouse has deterministic normalization, provenance, duplicate handling, and coverage QC.
2. Production-book subset is selected by predeclared information-preservation metrics, not ROI.
3. Calibration choices are selected only on chronological OOS probability metrics.
4. Decision/meta candidates are compared chronologically against V5-only and market-only baselines.
5. Spread and total probabilities are calibrated at exact lines before recommendation use.
6. Selection-policy thresholds are fixed before sealed forward evaluation.
7. New decision engine runs in shadow mode before replacing the existing official recommendation path.
8. Closing-line and outcome audit data are retained permanently from activation forward.
9. No underlying tennis-model change is bundled into this decision-layer program without a separate validated design.

## Implementation sequence
A. Historical market warehouse
B. Production-book subset optimization
C. Production market probability model
D. V5 calibration/reliability analysis
E. Joined tennis + market decision dataset
F. Chronological meta-model experiments
G. Moneyline opportunity engine
H. Spread probability calibration
I. Total probability calibration
J. New BET/LEAN/PASS/REVIEW policy
K. Shadow-mode production
L. Closing-line tracking
M. Sealed forward evaluation
N. Production cutover only after acceptance gates pass
