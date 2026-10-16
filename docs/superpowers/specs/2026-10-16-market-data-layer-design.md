# Market data layer (rebuild plan Step 3)

Date: 2026-10-16
Status: **DRAFT — pending user approval.**
Serves: roadmap Phase 0 (collection) and Phase 1 (honest benchmark). Plan: rebuild plan Step 3.
Builds on: tournament and player identity (Step 2), so every price is stored against our
own edition and player ids.

## 1. What exists today (inventory 2026-10-16)

- **Live prices:** one OddsPapi pull per day (cron 00:02 UTC; it actually runs 03:30–05:45
  UTC): Pinnacle every day, BetRivers on Sundays only. Raw payloads are thrown away; per-book
  prices (`all_book_prices.csv`) are overwritten each run.
- **Price history:** `market_snapshot_history.csv` keeps only the best price per selection,
  and only for markets the old engine priced (it is the repriced board). Each market appears
  in about 1.1 snapshots, a median 6.4 h before the start: no opening line, no closing line,
  no line movement.
- **OddsPapi historical odds** (`/v4/historical-odds`): one call per fixture returns every
  price change (for example 296 ticks on one Pinnacle moneyline) for Pinnacle, BetRivers
  and DraftKings, the three books OddsPapi covers here. The repo treats this endpoint as not
  counting against the request quota (to be verified, §4.1). Stored for 13,227 fixtures up
  to 2026-09-01 (1.4 GB of raw files in git); nothing after that.
- **Two different "closing price" rules** exist (`historical_odds_normalizer.select_snapshot`:
  scheduled start, inactive ticks included; `build_pinnacle_closing_2026.py`: true start,
  active ticks only).
- **Freshness:** the whole feed is fresh if its newest snapshot is under 24 h old; a price is
  dropped only once the match starts. Duplicated in `eligible_pre_match` and
  `future_market_rows`.
- **Kalshi, Polymarket, Novig, Bet365:** no code. `export_kalshi_training_dataset.py` reads
  OddsPapi data and has a syntax error.
- **Margin removal:** "same share off each side", then averaged across books, in three copies.

## 2. Design

### 2.1 One price store, independent of any model

`market_history/` holds prices, never model output. It is keyed by our ids: `edition_key`,
`player_id`, OddsPapi `fixture_id`, book, market, selection, line. The model joins to it; it
never filters what is stored.

### 2.2 Prices after the fact: daily historical pull (the closing-price answer)

Once a day, after matches finish, fetch `/historical-odds` for every relevant fixture that
started in the last 48 hours (about 60–100 a day), for Pinnacle, BetRivers and DraftKings.
From each fixture's ticks, one function derives:

- **open:** first quote seen;
- **close:** last active quote strictly before the true start time (scheduled start if the
  true start is unknown). This replaces both current rules;
- **checkpoints:** last active quote before T−24 h, T−12 h, T−6 h, T−1 h;
- tick count and the quote's own time for each, so staleness is visible.

Stored: a compact table `market_history/price_points_<year>.csv` (append-only, in git;
about 1 MB a month), and the raw ticks as a monthly GitHub release file (decision D3: no new
raw OddsPapi history in git).

The same code fills the gaps, as a manual workflow in batches: about 1,500 fixtures before
2026-09-01 that the earlier backfill never fetched, and about 3,600 since (roughly 80 a day).
At one call every 5 seconds that is about 7 hours of runs, spread over several days.

### 2.3 Live prices: start-time-aware freshness

One function decides whether a live price may be acted on: the quote is under a set age
**and** the match has not started (scheduled start, or true start once known), with the
quote's own change time used where OddsPapi gives it. Started fixtures leave the live board.
Every live snapshot keeps all books' prices (not only the best), so first-seen and last-seen
live prices exist too. The old engine keeps its rules until Step 4 switches it to this one.

### 2.4 Kalshi: daily, after settlement

Kalshi's public market-data API (no account needed for reading): once a day, list settled
tennis match markets, and store their trades and one-minute candles (price, volume, bid/ask)
in `market_history/kalshi_<year>/`. Markets are tied to our fixtures through the player ids
and date. Order-book depth only inside existing runs, never by polling (CLAUDE.md).
Polymarket and Novig: later, once Kalshi works.

### 2.5 Margin removal (approved 2026-10-13)

One function with a setting per book on the Box-Cox scale (0 = same share, 1 = additive, about
1.5 = power), the cautious edge rule built in, measured on §2.2's closes and checkpoints
(fit on the earliest 60%, test on the latest 40%, men / women / Challengers, closing and 4–8 h
before the start). Replaces the three copies and the cross-book average.

### 2.6 Budget (Actions, minutes per month)

| Job | Now | After |
|---|---|---|
| Weekly bulk backfill reserve | 193 | 0 (replaced) |
| Daily historical pull (~8 min) | 0 | 240 |
| Kalshi daily (~3 min) | 0 | 90 |
| Everything else | 1,560 | 1,560 |
| **Total** | **1,753** | **1,890** (limit 2,100) |

Optional saving: the old engine's daily heavy forecast and its retries cost 780 minutes a
month. Its output is untrusted (owner decision 2026-10-13) and, once §2.1 exists, nothing
else depends on it; it could be paused until Step 4.

## 3. Acceptance

- One close definition; the backfill reproduces the stored 2026 Pinnacle closes it overlaps.
- Every relevant fixture that started yesterday has open, close and checkpoints for each book
  that quoted it, or is listed with the reason (no quotes, not found).
- No live price for a started match reaches the board.
- Kalshi markets for yesterday's settled matches are stored and tied to fixtures, or listed.
- Budget test passes with the new jobs.

## 4. Open questions for the user

1. Approve this design?
2. A small probe run first (manual workflow, about 3 minutes, about 20 OddsPapi
   historical calls): it checks that historical odds really do not count against the quota,
   reads the real quota limit, and checks that Kalshi's API answers and which tennis series it
   lists. OK to run it?
3. Pause the old engine's daily heavy forecast until Step 4 (saves about 780 minutes a month)?
