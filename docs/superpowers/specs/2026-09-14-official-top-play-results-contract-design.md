# Official Recommendations, Ancillary Markets, and Results Contract

## Purpose
Keep the Decision Feed, official ledger, settlement, Results & Accuracy, Performance, and research history semantically separate and internally consistent.

## Production contract
A fixture has no arbitrary recommendation quota. Moneyline, spread, total, or other supported markets are evaluated independently by the validated production signal policy. If several independent markets reach an actionable production tier (`BET` or `LEAN` under the current policy), each is eligible to become an official recommendation. Markets that do not reach an actionable tier remain ancillary observations.

The card may still rank one market first for presentation. That display ranking is not a rule limiting how many markets from the fixture can become official recommendations.

### Official recommendation semantics
- Identity/immutability boundary is `market_key`, not `fixture_id`.
- Multiple distinct actionable market keys may become official for the same fixture.
- The first qualifying observation for a market is frozen with its pre-match probability, price, EV, edge, timestamp, model versions, and market identity.
- A frozen `BET` is immutable through later repricing.
- A frozen `LEAN` may upgrade to `BET` for the same market key before match start.
- No recommendation may be created or changed at or after match start; missing/invalid timing fails closed.
- Performance may therefore contain multiple recommendations from one match and must report them as separate economic decisions while retaining fixture clustering/correlation diagnostics.

### Ancillary market semantics
Every repriced market row is research data, including `REVIEW`, `PASS`, and other non-official observations. The complete pre-match snapshot history is appended to `v5_daily_ready/market_snapshot_history.csv`, deduplicated only by identical `snapshot_utc + market_key`, and is not age-pruned. Daily board rollover must not erase ancillary observations.

This history exists so future analysis can evaluate rejected/secondary signals, threshold changes, market-family performance, calibration, and policy changes without contaminating the official betting record.

## Results & Accuracy
Results & Accuracy measures the frozen tennis forecast independently of betting decisions. Its headline unit is one settled fixture. It grades predicted winner, Brier score, expected versus actual game margin, expected versus actual total games, and calibration when source fields exist. Multiple official or ancillary markets from one fixture do not multiply the fixture-level accuracy observation.

## Performance
Performance measures only economic results of rows frozen into `v5_daily_ready/official_recommendations.csv`. Each distinct official market key is settled at its frozen recommendation price. Supporting ancillary observations never create wins, losses, units, or ROI. Multiple official markets from one fixture are allowed and fixture clustering remains visible so correlated exposure is measurable rather than hidden.

## Data flow
1. Repricing produces the complete long-form market snapshot and signal for every priced market.
2. Every independently actionable market row is handed to the official ledger; display ranking is separate.
3. Every repriced row is appended to permanent market snapshot history for research, including ancillary rows.
4. Settlement updates official recommendations and frozen fixture forecasts from canonical results.
5. Results & Accuracy collapses settled forecasts to one observation per fixture.
6. Performance summarizes settled official market recommendations and also exposes fixture concentration/correlation diagnostics.

## Failure handling
- Missing/stale prices: no new official recommendation.
- Missing fixture, start time, snapshot time, or malformed timestamps: fail closed.
- Missing accuracy fields: retain the fixture and omit only unavailable metrics.
- Missing canonical results: preserve frozen artifacts and report the blocker.

## Required tests
1. Two or more distinct actionable markets from one fixture can all become official recommendations.
2. Repricing cannot duplicate the same official market key; its first BET remains immutable and its LEAN may upgrade to BET before start.
3. Post-start or timing-incomplete recommendations are blocked.
4. Ancillary REVIEW/PASS rows remain in market snapshot history beyond daily rollover and are not age-pruned.
5. Results & Accuracy still produces exactly one observation per settled fixture.
6. Performance counts every distinct official market recommendation and preserves fixture clustering diagnostics.
7. UI wording does not imply that the first displayed market is the only possible official recommendation.
