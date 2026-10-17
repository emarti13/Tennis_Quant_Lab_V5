# Results sources: TennisMyLife and Kalshi, cross-checked (2026-10-16)

`scripts/check_results_sources.py`; output in `docs/experiments/data/results_sources.json`.
User decisions 2026-10-16: Kalshi as the second results source; Challenger and WTA
qualifying left unpriced where no source settles them.

## What each source publishes

- **TennisMyLife** (all 171 files in its manifest checked): ATP tour, ATP qualifying
  (tour-level and Grand Slam), Challengers and WTA, main draws only. **No Challenger
  qualifying, no WTA qualifying, no WTA 125.**
- **Kalshi** (public API): settled match markets from about **August 10, 2026**, for
  ATP, WTA, Challenger and WTA 125 (`KXWTACHALLENGERMATCH`), **including some qualifying**
  ("ATP Challenger Kingston Qualification Round 1"). One market per player; a fixture is
  settled only when its markets agree (one "yes"). 74 of 2,768 markets settled "scalar"
  (retirements or voids): no result.

## Cross-check: the two must agree

| Where | Fixtures settled by both | Disagreements |
|---|---|---|
| Price-store fixtures | 99 | **0** |
| Every fixture a Kalshi market is tied to (from the registry) | **863** | **0** |

This checks the whole identity chain independently of TennisMyLife: our player ids, the
tournament crosswalks, and which side is player 1 in both the OddsPapi fixture and the
Kalshi match.

## Kalshi matching

- 2,604 of 2,768 markets tied to a fixture (94%), 2 ambiguous, 162 unmatched.
- Fixed while checking:
  - Kalshi marks namesakes "Kenta Miyoshi (b. 2004)" where OddsPapi writes
    "Miyoshi, Kenta (2004)": now the same name;
  - the window around Kalshi's scheduled time is now ±72 h (was ±36 h; about ten matches
    were 45–48 h off after schedule moves). A pair must still be unique in the window;
    rematches weeks apart stay separate;
  - links are rebuilt on every run from all stored markets
    (`market_history/kalshi/fixture_map.csv`), so a market stored before its fixture was
    known gets linked later.
- Most of the unmatched are matches OddsPapi doesn't list at all, so there are no OddsPapi
  odds to price them with.

## Coverage, all months, both sources

ATP 99.8%, Challenger 70%, WTA 69%, WTA 125 2% (Kalshi only, from August). The gap is
qualifying (TennisMyLife has none outside ATP) and WTA 125 before August. As the
backfill fills August 10 onward, Kalshi settles more of both.

## Correction to earlier notes

The January–August stored backfill **ends on August 9**, not September 1. Its fixture index
ran to September 1, but its price history stopped at August 9. The gap backfill fills
August 10 onward.
