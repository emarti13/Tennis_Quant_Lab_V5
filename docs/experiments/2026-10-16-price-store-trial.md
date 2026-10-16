# Price store trial (2026-10-16)

Two trial runs of `scripts/pull_market_history.py` on branch `research/step3a-trial`
(never merged) before the price-store PR. Each: one stored chunk converted (no API), then
3 minutes of live `/historical-odds` calls with Pinnacle, Bet365 and BetRivers.

## What it showed

- **Fixture discovery counts against the quota:** one `/fixtures` call (one 9-day window)
  moved `request_count` from 71 to 72 of 250. The daily job makes one such call; a
  one-off `--discover-from 2026-09-01` for the September gap makes about 6.
- **Discovery matters.** One window added 34 fixtures the live job never saw and filled
  in the true start time for 598. Before that, closes could only be cut at the scheduled
  start.
- **Queue:** 579 fixtures waiting in the 8-day daily window, 4,801 in the backfill (no
  stored history). At one call per 5 s, 29 fixtures in 3 minutes, so the backfill needs
  about 8 hours of calls: about 3 weeks at the 22 minutes a day the daily job leaves.
- **Live pull, 29 October fixtures:** every one resolved to our edition and player ids;
  492 of 510 rows cut at the true start. Pinnacle moneyline overround at the close: median
  3.3% (1.8–4.4%).
- **Stale closes** (the book withdrew its price more than 60 min before the start; spec
  §5.4), among rows with a close: Bet365 12.6%, Pinnacle 4.6%, BetRivers 0% (October);
  0.4–0.6% in January.
- **Stored January data:** chunk 4 (481 fixtures, 3,964 rows). **Pinnacle has no
  pre-start price in 69% of these rows**: the January download holds mostly in-play
  Pinnacle quotes. BetRivers and DraftKings have closes in more than 99%. Measure this over
  all 30 chunks before treating January–February Pinnacle closes as a benchmark.
- **Size:** about 230 bytes per price row, about 4 KB per fixture, about 9 MB of CSV a
  month at 70 fixtures a day. The spec's "about 1 MB a month" was an underestimate.
- Two bugs found and fixed before the PR: `identify()` reported every fixture as
  NO_HISTORY when no ratings were loaded, and an empty queue raised a KeyError.
