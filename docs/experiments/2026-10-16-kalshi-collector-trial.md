# Kalshi collector trial (2026-10-16)

Read-only runs against Kalshi's public market-data API (no account, no key) on research
branches `research/step3b-kalshi-shapes` and `research/step3b-kalshi-trial` (never merged),
before the Kalshi PR.

## Data shapes

- One market per player ("Cameron Norrie wins"). `yes_sub_title` is the full name;
  `occurrence_datetime` is the scheduled start; `rules_primary` names the tournament and
  round ("2026 ATP Shanghai Round Of 128").
- Series in scope: `KXATPMATCH`, `KXWTAMATCH`, `KXATPCHALLENGERMATCH`, and
  `KXWTACHALLENGERMATCH` (WTA 125).
- 1-minute candles (`period_interval=1`) exist only for minutes with activity. They carry
  the best YES bid and ask (`yes_bid`/`yes_ask` open/high/low/close, in dollars).
- Trades come 1,000 a page with a cursor, newest first, and can be filtered with `max_ts`.
  Trading continues after the start, so every price is cut at the start.

## Collector, 3 minutes

- **298 markets stored** with about 782 API calls (about 2.6 per market). 282 were tied to
  an OddsPapi fixture by both players' full names; 16 were not (their fixture was not in
  the registry yet). The collector now waits up to 3 days for the fixture and its true
  start, as the OddsPapi pull does.
- By family: Challenger 180, WTA 52, WTA 125 50, ATP 16.
- **Bid-ask spread at the start: 1 cent** in the median and the 75th percentile (mean
  1.5 cents).
- Pre-start trades per market: median 42, up to about 18,700 on big ATP matches.

## How far back

- About 9,550 settled markets are listed in all. Checks for January and June 2026 found no
  `KXATPMATCH` markets; September did (1,794 candles and 20,870 pre-start trades on one
  ATP match). Kalshi's tennis match markets seem to start around August 2026, so there is
  no Kalshi history for the first half of the season.
- At about 100 markets a minute, the full backfill is about 1.5 hours of runs.
