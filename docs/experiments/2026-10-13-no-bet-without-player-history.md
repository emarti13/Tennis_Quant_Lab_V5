# No BET or LEAN without both players' history

Date: 2026-10-13 · Production safety (Gate 0) · User approval: chat, 2026-10-13.

## Finding

- A player with no history in our data is priced from a default state (1500 Elo,
  confidence 0). The daily batch decided a market's confidence from the *selected*
  player only, so a bet on a known player against a no-history opponent kept the known
  player's confidence and could reach BET. The app already used the weaker of the two
  players (`min(p1_conf, p2_conf)`); the batch had drifted from it.
- Feed placeholders for undecided draw slots ("WQF1", "Qf3", "WSF2", "R16P14") were
  priced as players.
- Saved predictions: 24,547 rows, 1,495 with a no-history player, 9 of them BET. All 9
  are in the official ledger, e.g. vs Katarina Kuzmova (no rows in our WTA history; her
  results are ITF) at a 37-point edge, and vs "WQF1" at a 63-point edge.

## Change

- `v5_daily_batch._confidence_for_market`: the weaker player's confidence for every market,
  as in the app. A no-history player (confidence 0) always gives REVIEW.
- `v5_live_market.is_placeholder_participant`: placeholders raise in `_prepare_fixture`,
  so the fixture gets no price and is logged with the batch errors.
- `v5_reprice_markets`: rows frozen before this change carry the old confidence, so the
  cold-start flags also hold them at REVIEW.

## Replay on saved predictions (reporting only; nothing re-tuned)

Of 566 BET/LEAN rows, 46 become REVIEW: 9 with a no-history player, 37 where the
opponent's confidence is below the existing 0.45 threshold. In the official ledger
(never rewritten) these are 40 of 1,809 rows; 13 have settled, for -2.77 units, against
+5.10 units over the 1,351 settled rows that stay. Thirteen bets are far too few to
judge the rule by results; it is accepted because it removes a silent default (CLAUDE.md:
fail closed), not because of this number. Threshold 0.45 is unchanged.
