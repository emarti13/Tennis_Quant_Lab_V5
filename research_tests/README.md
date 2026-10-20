# Edge search, 2026-10-20: three test families (research)

Run by three parallel agents on data before the sealed period (2026-10-13), chronological
splits, fees included, ranges resampled by fixture or match. Scripts and full results here;
they read caches from the session scratchpad (rebuild from the repo's market_history and
match files).

| Family | Script | Verdict |
|---|---|---|
| Execution books (BetRivers, DraftKings, Bet365) vs Pinnacle fair, moneyline/totals/spreads, checkpoints t24h..close (about 400 cells) | `books/run_books.py` | No cell credibly positive; first-half winners turn negative in the second half; totals "edges" significantly negative. One spread cell (t12h, EV>2%, n=23, +57%) is a chance-level hypothesis, not a finding. Kalshi vs Pinnacle untestable before the seal (no overlapping dates). Pinnacle's close beats its open by 0.0055 log loss; almost nothing arrives after t24h. |
| ML on top of Pinnacle (LightGBM, L2 logistic; Elo, fatigue, serve/return, pace, book gaps, line moves, totals/spread lines) at t12h/t6h/t1h | `ml/run_ml.py` | No model beats Pinnacle at the decision time or at the close (LightGBM stops after 1-6 rounds). Positive betting cells have negative CLV (luck); CLV-positive "stale soft book" bets lost money on small samples. |
| Kalshi in-play: LightGBM/logistic on price paths, simple rules (fade favourites, momentum, reversal, take-profit), maker variant | `inplay/run_inplay.py` | Every model worse than Kalshi's mid; every taker rule loses after fees (momentum held: about -3.7%, the fee). Fading 70-90c favourites, one entry per match: -11% (ATP/WTA -7%). The per-sample calibration result of docs/experiments/2026-10-20-inplay-calibration.md does not survive as a tradeable rule. Data: Aug 10-Sep 2 only. |
