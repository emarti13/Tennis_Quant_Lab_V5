# Fixture resolution vs the old engine's lookups

Date: 2026-10-15 · Rebuild plan Step 2 · No model or price change (the old engine is untouched);
no market benchmark applies.

`v5_fixture_resolution.FixtureResolver` was run on every fixture the old engine froze a
prediction for (1,192 fixtures), and compared with what the old
engine used (`tournament_authority` surface; name-matched players).

| Outcome | Fixtures |
|---|---|
| Resolved | 1,135 |
| Not in the stored OddsPapi fixture list | 56 (US Open, before the collection gap closed on Sept 13) |
| Placeholder participant (WQF1) | 1 |

**Surface: the old engine was wrong on 100 fixtures.** Nine clay-court events were priced
as hard court: the Porto, Genoa (two), Seville, Tulln and Biella Challengers (TennisMyLife
results confirm clay for all six) and three WTA 125 events (Antalya 4, Montreux, Tolentino;
the master schedule says clay, no results yet to confirm). The other 1,035 agree.

**Players:** 2,162 player slots the old engine rated keep a rating; 98 it priced from the
1500 default are `no_history` (shown, never recommended); 10 it priced from the default now
resolve to a rated player.

Reproduce: `FixtureResolver.from_repo(".", ratings_by_tour=...)` over
`v5_daily_ready/frozen_predictions.csv` (script in the PR description).

Daily refresh: `python scripts/refresh_identity.py` takes about 75 s; a rerun leaves the
stored tables unchanged (decision dates are kept when a decision does not change).
