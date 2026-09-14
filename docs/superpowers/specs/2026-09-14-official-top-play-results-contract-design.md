# Official Top Play and Results Contract Design

## Purpose

Make the Decision Feed, official recommendation ledger, settlement, Results & Accuracy, and Performance pages tell the same story and measure different things correctly.

## Production contract

For every fixture, the production pricing engine may expose several market candidates whose raw signal is `BET`, `LEAN`, `REVIEW`, or `PASS`. Those raw market signals are evidence that a market clears a pricing threshold; they are not all official recommendations.

The Decision Feed selects exactly one **primary market** for the fixture using the same deterministic policy already used by the card: signal tier first (`BET` before `LEAN` before `REVIEW` before `PASS`), then highest expected value within the tier, then a stable deterministic tie-break. If the selected primary market is `BET` or `LEAN`, that one market is eligible to become the fixture's official recommendation.

### Official recommendation semantics

- At most one official recommendation may exist per fixture.
- The first qualifying primary market for a fixture is frozen with its pre-match model probability, price, EV, edge, timestamp, model versions, and market identity.
- A frozen `BET` remains immutable through later repricing.
- A frozen `LEAN` may be superseded before match start if the fixture's primary market later becomes `BET`; the replacement may be a different market because the fixture-level decision changed.
- No recommendation may be created or changed at or after match start.
- Non-primary market rows remain in repricing/audit artifacts and may still display their raw `BET`/`LEAN` signals, but they must never be inserted into the official ledger.
- Existing open ledgers that contain several recommendations for one fixture are normalized deterministically to the strongest frozen candidate before further updates. Settled historical rows are not rewritten by migration logic.

### Decision Feed wording

The card header represents the official/top selection. The market-output section represents pricing candidates. The UI must state that distinction explicitly so multiple `BET` labels cannot reasonably be interpreted as multiple official bets.

## Results & Accuracy semantics

Results & Accuracy measures the quality of the frozen tennis forecast, independent of which market was officially recommended.

It uses one settled record per fixture from the frozen forecast ledger and reports, when the required inputs are available:

- predicted winner and actual winner;
- match-winner accuracy;
- Brier score for the frozen player-1 match probability;
- expected margin versus actual game margin from player 1's perspective;
- absolute margin error;
- expected total games versus actual total games;
- absolute total error;
- calibration buckets across settled fixture forecasts.

Market-level settlement rows remain available as audit detail, but they are not the headline unit of observation for Results & Accuracy.

## Performance semantics

Performance measures only the economic results of official recommendations.

- Source of truth: `v5_daily_ready/official_recommendations.csv` after settlement.
- Unit of observation: one official recommendation per fixture.
- Price and model values are the frozen pre-match values from recommendation time.
- WIN/LOSS/PUSH/VOID settlement produces units and ROI from that frozen official price.
- Supporting market candidates do not create additional wins, losses, or units.
- Fixture clustering remains available as an audit check, but with the one-top-play contract the maximum recommendations per fixture should be 1 for new production recommendations.

## Data flow

1. Repricing creates the full long-form market snapshot and raw signals.
2. A shared primary-selection policy selects one market row per fixture.
3. Only the selected `BET`/`LEAN` row is handed to the official recommendation ledger.
4. Settlement updates both the frozen market audit ledger and the official recommendation ledger from the canonical results cache.
5. Results & Accuracy collapses settled frozen predictions to one fixture record and grades the forecast.
6. Performance summarizes only settled official recommendations.

## Failure handling

- Missing or stale prices: no new official recommendation.
- Missing start time or malformed timestamps: fail closed; do not create a post-start recommendation.
- Missing model forecast fields for Results & Accuracy: retain the fixture row, show available metrics, and omit only the unavailable metric rather than inventing values.
- Missing canonical results: preserve existing frozen artifacts and report the settlement blocker.

## Testing requirements

1. Multiple `BET` rows for one fixture produce one official recommendation: the same row selected as the Decision Feed primary market.
2. Two fixtures can each produce one official recommendation in the same snapshot.
3. A later repricing cannot add a second official `BET` for a fixture.
4. A fixture-level `LEAN` can be superseded by a later primary `BET` before start.
5. Existing duplicate open recommendations collapse to one deterministic row per fixture.
6. Results & Accuracy produces exactly one record per settled fixture and correctly computes winner accuracy, Brier score, game-margin error, and total-games error.
7. Performance ignores supporting market candidates because they never enter the official ledger.
8. UI copy identifies the header as the official/top play and the lower rows as pricing candidates.
