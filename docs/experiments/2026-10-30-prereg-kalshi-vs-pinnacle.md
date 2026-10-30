# Pre-registration: Kalshi priced against Pinnacle's no-vig line (take and make)

**DRAFT — pending user approval** (asked for in chat 2026-10-30: "find some alpha and take
liquidity, make a good price model and market make around it, cancel when you can't price the
market right"). Locked by this commit, before any sealed outcome, Kalshi fill or Pinnacle
close for the test fixtures was loaded. Nothing below changes after the results are seen.

## Why
- No model of ours beats Pinnacle's close with a correct de-vig (`2026-10-24-gate1-gaps.md`).
- Kalshi taker rules lost after fees (`research_tests/README.md`). Making around Kalshi's own
  mid earned about nothing after the maker fee (`2026-10-20-kalshi-paper-run.md`, which ends:
  "market making here needs a fair price that knows more than the book").
- Untested so far: Pinnacle as the fair price for Kalshi. Before the seal the two never
  overlapped (August and September: Kalshi 2,496 fixtures, Pinnacle 707, overlap 0). From
  2026-10-13 they overlap (486 fixtures to 2026-10-21 as of this writing), all inside the
  sealed period, so this can only be a single pre-registered evaluation.

## Data
- Fixtures with both a Kalshi match market (`market_history/kalshi/price_points/`) and a
  Pinnacle moneyline (`market_history/price_points/`), checkpoint at or after 2026-10-13,
  winners from `v5_market_results.load_fixture_winners`. Voids (walkovers, retirements before
  two completed sets) are excluded from settled P&L but kept for closing-line value.
- **Fair price at a checkpoint c in {t24h, t12h, t6h, t1h}:** Pinnacle's moneyline standing at
  c, de-vigged with `v5_devig.devig(odds, book_lam("pinnacle"))`, the measured λ (1.5).
- **Kalshi at c:** the best bid and ask for each side's market at c (`t24h_bid`, `t24h_ask`, …).
- **Kalshi taker fee per contract:** 0.07·P·(1−P), P = the price paid. Kalshi rounds the fee
  per order up to the cent; per-contract unrounded is used, which slightly flatters results.
  This is stated as a limitation, not adjusted.

## Test T: take liquidity on Kalshi when it is off Pinnacle
- **Signal:** at checkpoint c, buy side s at Kalshi's ask if
  fair_s − ask_s − fee(ask_s) ≥ 0.02 (2c after the fee).
- **Can't-price filter (no trade):**
  - either price is missing;
  - |fair_s − Kalshi mid_s| > 0.10: a gap that large usually means news one side has not
    priced (injury, withdrawal, wrong match), so it is skipped, not taken;
  - Kalshi spread at c above 0.05.
- **One entry per fixture:** the earliest checkpoint that signals (t24h, then t12h, t6h, t1h).
  One contract per entry; results are per contract.
- **Primary measure:** closing-line value per contract = Pinnacle no-vig close fair_s −
  (ask_s + fee). Mean over entries, with a 95% interval from 2,000 fixture-resampled
  bootstraps.
- **Pass:** at least 100 entries, and the interval's lower bound above zero.
- **Secondary (reported, no pass rule):**
  - settled P&L per contract (1 − ask − fee if s wins, −ask − fee otherwise);
  - closing-line value against Kalshi's own close mid;
  - each split by tour family (ATP, Challenger, WTA, WTA125) and by checkpoint, and with the
    thresholds 0.01 and 0.03 in place of 0.02 as sensitivity only (the 0.02 result is the
    test).

## Test M: make around Pinnacle's fair price
Run only if Kalshi's trade tape for these fixtures can be read (the monthly raw release). If it
cannot, M is reported as not run, with no substitute.
- **Quotes:** from each checkpoint until the next checkpoint (or the start), rest a buy at
  fair − h and a sell at fair + h, rounded away from fair to the cent, never crossing Kalshi's
  book at c. h ∈ {0.03, 0.05}, fixed from the August replay (no other values). 100 contracts a
  side, at most 300 net per market.
- **Cancel (can't price):**
  - at the next checkpoint, when the fair is re-read;
  - at the start (true start or Kalshi's event start, whichever is earlier);
  - immediately if Kalshi's mid moves more than 0.10 from the fair: the book knows something
    we do not.
- **Fills:** only Kalshi trades that went through our price, or reached it while ours was
  strictly the best, the same conservative rule as `scripts/simulate_kalshi_making.py`.
- **Primary measure:** fills marked at Pinnacle's no-vig close, minus Kalshi's maker fee
  0.0175·P·(1−P), in cents per contract, with a fixture-resampled 95% interval.
- **Pass:** at least 1,000 contracts filled, and the lower bound above zero, for h = 0.03 or
  0.05 (a single pre-declared pair; both reported).

## What follows a pass or a fail
- **Fail:** recorded as closed in `research_tests/README.md`; no variant is re-tested on the
  same period.
- **Pass:** a forward paper run with live quotes on the user's machine (no orders), then a
  decision by the user. Nothing is sent to Kalshi with real money by an agent.
