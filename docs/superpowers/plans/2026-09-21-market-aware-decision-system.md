# Market-Aware Decision System Implementation Plan

> **For agentic workers:** Execute this plan task-by-task in order. Keep checkboxes current. Do not skip acceptance gates or replace chronological/OOS validation with retrospective ROI tuning.

**Goal:** Build a market-aware V5 decision layer that preserves the existing independent tennis model, constructs an affordable production market view, learns when V5 adds information beyond that market, and turns only credible mispricing into official recommendations.

**Architecture:** Historical all-book OddsPapi data are the research teacher. A constrained production-book subset is selected from historical evidence and used consistently for both training and live inference. V5 and the production market remain independent inputs to a calibrated decision/meta layer. Moneyline, spread, and total then receive market-specific opportunity logic and one unified evidence-based recommendation policy.

**Tech Stack:** Python 3.12, pandas, numpy, scikit-learn, gzip/json/pathlib, pytest, existing V5/OddsPapi modules, GitHub Actions.

**Spec:** docs/superpowers/specs/2026-09-21-market-aware-decision-system-design.md

## Global constraints
- Preserve the current independent tennis models during this program.
- Historical all-book data may inform research, but live features must match the affordable production book set.
- No raw-EV-only BET rule.
- No arbitrary favorite/underdog or odds cutoff.
- No post-hoc threshold search to manufacture ROI.
- All model/calibration comparisons are chronological and out-of-sample.
- Every artifact carries model/policy/data provenance.
- Raw historical and official ledgers are never destructively rewritten.

---

### Task 1: Inventory and normalize the historical OddsPapi cache

**Files:** Create v5_historical_market_reference.py and tests/test_v5_historical_market_reference.py. Produce v5_research/historical_market_reference.parquet and v5_research/historical_market_reference_qc.json.

**Interfaces:** iter_history_records(chunk_dir), profile_history_cache(chunk_dir), normalize_historical_market_records(...).

- [x] Step 1: Add a deterministic gzip/JSONL cache scanner and schema profiler.
- [x] Step 2: Add synthetic tests for chunk ordering, record counting, top-level schema profiling, bookmaker coverage, fixture coverage, and malformed-line accounting.
- [ ] Step 3: Inspect real retained chunk payload shapes and implement canonical normalization for ML/spread/total.
- [ ] Step 4: Pair opposing sides at the same canonical line and compute implied/de-vigged probabilities and overround.
- [ ] Step 5: Add deduplication/provenance invariants and QC.
- [ ] Step 6: Build the research warehouse from all retained history and report date/book/market coverage.
- [ ] Step 7: Commit normalized warehouse builder and QC contract.

**Acceptance:** one deterministic canonical row per fixture/snapshot/book/market/line/side with explicit provenance and no silent schema drops.

---

### Task 2: Production bookmaker subset analysis
- [ ] Define full-market research benchmark.
- [ ] Enumerate feasible 1-4 book subsets subject to live credit limits.
- [ ] Compare fair-probability RMSE/MAE, main-line agreement, closing-direction agreement, dispersion retention, and executable-price coverage.
- [ ] Report incremental information contribution by bookmaker.
- [ ] Select the smallest stable subset meeting predeclared preservation criteria.
- [ ] Freeze production book-set version and rationale.

**Acceptance:** selected live book set is justified by information preservation, not historical betting ROI.

---

### Task 3: Production market probability engine
- [ ] Implement paired two-sided market construction.
- [ ] Challenger-test proportional no-vig and other justified de-vig methods.
- [ ] Produce P_market, dispersion, book count, price age, movement, and data-quality flags.
- [ ] Keep consensus probability separate from best executable price.
- [ ] Verify live inputs require only the frozen production bookmaker subset.

**Acceptance:** historical training features can be reproduced identically from live production inputs.

---

### Task 4: V5 calibration and reliability harness
- [ ] Load only OOF/walk-forward V5 forecasts.
- [ ] Compare raw, existing, logistic/Platt, isotonic, and beta calibration where supported.
- [ ] Score Brier, log loss, calibration/reliability curves, and later-period stability.
- [ ] Estimate prediction reliability/uncertainty with shrinkage.
- [ ] Diagnose probability region, tour, surface, state-confidence, disagreement, and favorite/underdog behavior without tiny-bucket overfitting.
- [ ] Freeze accepted calibration/reliability version.

**Acceptance:** chosen calibration improves or preserves untouched future-period probability quality; ROI is not the selection criterion.

---

### Task 5: Joined historical decision dataset
- [ ] Join frozen/OOF tennis predictions to production-subset market snapshots strictly before match start.
- [ ] Add calibrated tennis probability, reliability, market probability/dispersion, model-market deltas, context quality, and actual result.
- [ ] Prohibit future/closing information from training-time features.
- [ ] Track join coverage and exclusion reasons.

**Acceptance:** no look-ahead leakage; every feature is available at the historical decision timestamp.

---

### Task 6: Chronological decision/meta-model experiments
- [ ] Establish V5-only, market-only, and simple blend baselines.
- [ ] Train interpretable logistic/residual candidates first.
- [ ] Challenger-test more flexible models only with strict chronological validation.
- [ ] Calibrate final P_decision independently.
- [ ] Compare Brier, log loss, calibration, stability, and incremental value versus market-only.
- [ ] Reject complexity that does not survive later-period validation.

---

### Task 7: Moneyline opportunity engine
- [ ] Compute fair price from calibrated P_decision.
- [ ] Compute raw and reliability-adjusted edge/EV.
- [ ] Represent evidence that the edge remains positive under uncertainty.
- [ ] Preserve favorite and underdog opportunities; prohibit no side by arbitrary price rule.
- [ ] Keep opportunity identification separate from best-price execution.

---

### Task 8: Spread probability calibration
- [ ] Price exact spread lines from the game-margin distribution.
- [ ] Validate sign/side conventions exhaustively.
- [ ] Calibrate cover/push/loss probabilities chronologically.
- [ ] Evaluate line-specific and grouped reliability.
- [ ] Emit uncertainty-aware spread opportunity probabilities.

---

### Task 9: Total probability calibration
- [ ] Price exact total lines from the total-games distribution.
- [ ] Calibrate over/push/under probabilities chronologically.
- [ ] Evaluate line-specific/grouped reliability.
- [ ] Emit uncertainty-aware total opportunity probabilities.

---

### Task 10: Unified recommendation policy
- [ ] Define evidence fields common to ML/spread/total.
- [ ] Derive BET/LEAN/PASS/REVIEW from credible advantage and reliability rather than raw EV alone.
- [ ] Preserve one official selection per market family per fixture.
- [ ] Freeze policy version with every recommendation.
- [ ] Lock thresholds before sealed forward evaluation.

**Acceptance:** a larger raw EV can rank below a smaller but much more credible edge; policy is coherent across favorites, underdogs, spreads, and totals.

---

### Task 11: Shadow-mode production
- [ ] Run new decision outputs beside current official recommendations without affecting official Performance.
- [ ] Persist every shadow decision and required provenance.
- [ ] Surface comparison UI/audit only; no production cutover.
- [ ] Verify daily pipeline reproducibility and live OddsPapi credit use.

### Task 12: Closing-line tracking
- [ ] Capture permitted late/closing observations under the credit budget.
- [ ] Store closing consensus/line/best price separately from pre-match decision features.
- [ ] Add CLV/error-to-close metrics to shadow evaluation.
- [ ] Never feed closing information into historical decision features.

### Task 13: Sealed forward evaluation
- [ ] Freeze model, calibration, production book set, and selection policy.
- [ ] Run untouched forward.
- [ ] Evaluate probability quality, units/ROI, CLV, drawdown, market/tour/probability bands, and tiers.
- [ ] Diagnose failures without retroactively changing the sealed sample.

### Task 14: Production cutover
- [ ] Cut over only after acceptance criteria pass.
- [ ] Preserve legacy artifacts for audit.
- [ ] Make the new decision layer the sole official recommendation authority.
- [ ] Keep independent tennis prediction and market probability visible separately.
- [ ] Continue permanent forward monitoring and versioned recalibration.

## Current status
Task 1 Steps 1-2 began on 2026-09-21. No predictive-model or recommendation-policy behavior has been changed.
