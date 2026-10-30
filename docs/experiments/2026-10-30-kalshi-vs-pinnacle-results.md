# Kalshi priced against Pinnacle: results of the pre-registered tests

Run once on 2026-10-30, under the rules locked in `2026-10-30-prereg-kalshi-vs-pinnacle.md`
(commit `0dbcb67`, made before any outcome was loaded). Code: `research_tests/kalshi_pinnacle/`.
QA checks pass.

**Data:** sealed fixtures from 2026-10-13 to 2026-10-21 that have a Kalshi match market and a
Pinnacle moneyline: 354 fixtures for test T. For test M, 708 Kalshi markets (346 fixtures)
also have a trade tape in the `market-raw-2026-10` release.

## Kalshi tracks Pinnacle closely
At the checkpoints, the median gap between Kalshi's mid and Pinnacle's no-vig price
(λ 1.5) is **0.5 to 0.6c**. Kalshi tennis prices are effectively Pinnacle's line.

## Test T, take liquidity: FAIL (not enough signals)
- **Signals:** Kalshi's ask was at least 2c below Pinnacle's fair after the taker fee in **2
  of 354 fixtures** (pass needs 100).
- **Sensitivity at 1c:** 12 entries. Closing-line value vs Pinnacle +0.4c (−0.5, +1.1); vs
  Kalshi's own close −1.5c.
- **Verdict:** there is nothing to take. Closed.

## Test M, make around Pinnacle's fair: PASS on the pre-registered rule
Quotes at Pinnacle fair ± h from each checkpoint (24h, 12h, 6h, 1h) to the next. They are
cancelled at the start, or when Kalshi's mid is more than 10c from the fair (that cancelled 11
trades). Fills use the conservative replay rules, 100 contracts a side and at most 300 net.
Fills are marked at Pinnacle's no-vig close, minus Kalshi's maker fee.

| Half-width | Matches with fills | Contracts | Marked profit | Cents per contract (95% range) | Held to result |
|---|---|---|---|---|---|
| 3c | 49 | 10,160 | +$116 | **+1.14 (0.51, 1.72)** | −$123 |
| 5c | 17 | 3,011 | +$108 | **+3.57 (2.59, 4.51)** | −$58 |

Diagnostics (not part of the pass rule):
- **Positive every day,** 13 to 20 Oct.
- **Not one lucky match:** without the top 3 matches, +0.9c (3c) and +2.8c (5c) per contract.
- **Mostly Challenger, then WTA.** ATP contributes almost nothing. This matches the August replay,
  where Challenger was the one positive tier.
- **How it earns:** fills happen when Kalshi trades 3 to 5c away from Pinnacle's last line, and
  by the close Kalshi has moved back toward Pinnacle. The book's noise reverts toward the
  sharper line.

## Read with care
- **Small money:** about $14 a day at 100-contract quotes over 8 days, from a few dozen matches.
  It shows the mechanism, not a business.
- **One 8-day window.** It needs a second, forward window under the same rules.
- **Held to the result it lost** (−$123 / −$58). With 49 and 17 matches that is luck either way
  (the pre-registered measure is the close mark), but real money would see that swing.
- **The fill model is approximate:** 1-minute candles, and queue position is approximate. Live,
  our orders would change the book.
- **Live needs Pinnacle in real time.** Here the fair was Pinnacle at fixed checkpoints, read
  afterwards. Live quoting needs a fresh Pinnacle price whenever quotes are placed; today we
  fetch OddsPapi once a day. A stale fair is exactly the "can't price" case, so quotes must stop
  whenever Pinnacle's price is not fresh.
- **Unconfirmed:** whether Kalshi's maker fee on tennis is 0.0175·P·(1−P).

## Next (per the pre-registration)
A forward paper run with live quotes and no orders, on the user's machine. It needs:
- Pinnacle polled at least every few hours via OddsPapi, within quota (`v5_live_prices.is_actionable`
  as the freshness rule);
- Kalshi's book read live, with paper fills from the live tape;
- the same settings (h 3c and 5c, 10c cancel gap) and the same measure.

After that, real money is the user's decision. No agent sends orders.
