# Order-book walls on Kalshi tennis: first look (2026-11-06)

**Status:** exploratory. **Result: void.** The data cannot measure the move to the close.

**Idea:** a large resting order offering one side is someone holding the other, and the price follows it. It comes from an r/algobetting post the user shared on 2026-11-05: totals and spreads worked there, moneylines did not.

**Test:** `research_tests/orderbook/run_topbook_wall.py`, pre-registered and pushed (`d55cfcc`) before the run.

**Data:** the paper trader's best-price sizes (`depth_*.csv.gz`) from before 2026-11-01. That is only:
- Oct 20, 00:40–14:38 UTC;
- Oct 31.

It covers only Challenger match-winner markets, top of book only: 98 matches with both markets logged.

## What happened

- 62 matches had a decision poll 6 hours to 60 minutes before the start.
  - 36 of them met the wall rule: support at least 3× the other side and at least 300 contracts.
- **The decision poll was almost always also the last poll before the start.** The median time before the start was 91.9 minutes for both. On those days the paper trader's runs ended hours before many matches began: the last poll was a median 174 minutes before the start.
- So the "move to the close" is close to zero by construction:

| side | move | range |
|---|---|---|
| wall side | +0.05 pts | −0.10 to +0.22 |
| random side | −0.02 pts | |

- CLV (the close minus the cost) is just the spread and the fee, about −1.8¢ for both the wall and the random side.
- The correlation of the log support ratio with the move is 0.09 (n = 62).

**Label:** not measurable from this data. This is neither a pass nor a fail.

## What replaces it

Since 2026-11-06, commit `91f9212` on `feat/vm-runner` has the server's live logger record the full Kalshi order book every 5 minutes:
- 10 levels nearest the best price per side, and each side's total resting size;
- for every open tennis market: winner, game spread, total games and set winner;
- up to the start and through play.

The spread and total quotes are logged too. Once a few weeks of these logs exist, the wall rule (adapted from the post: one rung at least 55% of its side and 3× the next, the backing side at least 2× the other, a minimum size, a one-sided wall rather than a two-sided market maker) gets a registered forward test, scored on CLV against the Kalshi close.

The first real sweep (2026-11-06 04:39 UTC) already showed what a wall looks like: on the Fritz–Alcaraz winner market there were 66,183 contracts of NO on Fritz bid at 70¢, against 4,000–7,000 at the neighbouring prices.
