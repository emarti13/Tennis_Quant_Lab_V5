# De-vig measurement on our 2026 closes (2026-10-16)

`scripts/measure_devig.py`; full output in `docs/experiments/data/devig_measurement.json`.
Spec §2.5, rebuild plan Step 3 (user decision 2026-10-13).

## Data

- Price store (`market_history/`), moneyline, Pinnacle, BetRivers and DraftKings: the
  January–August backfill plus the first live pulls. Bet365 has too few results before the
  sealed period yet.
- **Only fixtures that started before 2026-10-13** (sealed period; CLAUDE.md).
- Closes whose book stopped quoting more than 60 minutes before the start are left out
  (spec §5.4). Also measured 6 hours before the start.
- Winners joined through our ids (`v5_market_results`): same master-schedule edition and
  same two `player_id`s. 41,731 book × fixture × point pairs.
- **Winner coverage: 8,515 of 12,366 resolved fixtures (69%)**, 63–76% a month. The
  missing 31% are a gap in the results join, to look at before Step 5's re-simulation.
- Earliest 60% (by start time) to fit lam, latest 40% to test; paired bootstrap (1,000)
  against multiplicative.

## Results (test-set log loss)

| Book, point | n test | fitted lam | fitted | multiplicative | additive | power | fitted − mult., 95% CI |
|---|---|---|---|---|---|---|---|
| Pinnacle, close | 3,058 | 5.0 (edge) | 0.6067 | 0.6056 | **0.6055** | 0.6056 | +0.0012 [−0.0008, +0.0030] |
| Pinnacle, T-6h | 2,915 | 5.0 (edge) | 0.6084 | 0.6076 | **0.6074** | 0.6074 | +0.0008 [−0.0013, +0.0029] |
| BetRivers, close | 2,745 | 1.35 | **0.6082** | 0.6087 | **0.6082** | 0.6083 | −0.0005 [−0.0022, +0.0012] |
| BetRivers, T-6h | 2,563 | 5.0 (edge) | 0.6112 | 0.6099 | 0.6093 | **0.6092** | +0.0013 [−0.0016, +0.0044] |
| DraftKings, close | 2,715 | 1.10 | 0.6081 | 0.6082 | **0.6081** | 0.6083 | −0.0001 [−0.0012, +0.0010] |
| DraftKings, T-6h | 2,644 | 1.05 | 0.6054 | 0.6062 | 0.6054 | **0.6051** | −0.0009 [−0.0019, +0.0002] |

By family (closes), fitted lam: Pinnacle ATP 5.0, Challenger 5.0, WTA 0.05; BetRivers ATP
5.0, Challenger 1.55, WTA 0.95; DraftKings ATP 0.95, Challenger 1.55, WTA 0.7. No
family's fitted lam beats multiplicative significantly.

## What it means

- **On our data the methods cannot be told apart.** Every difference is at most 0.003 log
  loss and every 95% interval includes zero. The fit curve is nearly flat (Pinnacle close,
  fit set: 0.5921 at lam 0 to 0.5911 at lam 5), so the fitted lam drifts to the edge of the
  range and does worse on the test set. That is noise, not a real setting.
- **Additive (lam = 1) is best or tied at the close for every book.** It is the setting for
  every book (`v5_devig.DEFAULT_LAM`) until more data separates them: September–October
  closes, Bet365, and tennis-data.co.uk once that domain is allowed. vigged.com's
  Pinnacle-tennis lam of about 2.0 is not contradicted, just not detectable here.
- The cautious edge rule judges every edge against the least favourable of
  multiplicative, additive and power, so this choice cannot create an edge.
- **Benchmark for the model (Phase 1):** the market's test-set log loss is about 0.606
  at the close and 0.607–0.611 six hours before the start on these fixtures. Pinnacle's
  close is calibrated within noise in every probability bucket.
