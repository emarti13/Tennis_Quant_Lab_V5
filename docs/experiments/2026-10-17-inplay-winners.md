# Winners from the last in-play prices (2026-10-17, research)

User-approved research: OddsPapi's stored price history includes in-play quotes to the end of
each match, so the last ones may name the winner. That would settle the matches TennisMyLife
does not publish (Challenger and WTA qualifying, WTA 125) for all of 2026, and identify lucky
losers for the stage label. Scripts: `scripts/research_inplay_winners.py`,
`scripts/research_inplay_retirements.py`; outputs in `docs/experiments/data/inplay_*`.

## Method

Stored January–August backfill, 13,227 fixtures; moneyline only (market 121); Pinnacle,
BetRivers and DraftKings. Each book's last active quote per side after the start. A book
calls the match when one side is at or below 1.10 and the other at or above 5.0; otherwise
"unclear". Answer key: TennisMyLife winners joined through our ids (8,516 fixtures).

## Three rules

| Rule | Calls among the 8,516 | Wrong | Settles, of the 4,711 without a TennisMyLife result |
|---|---|---|---|
| Loose: any book calls, none names the other side | 7,393 (87%) | 31 (0.42%) | 4,100 (87%) |
| Middle: the books that call agree and none is unclear | 3,892 (46%) | 3 (0.08%) | 2,569 (55%) |
| Strict: at least two books agree, none unclear | 2,748 (32%) | 1 (0.04%) | 1,741 (37%) |

## Retirements (user: "not a full completed 2 sets, at a minimum")

TennisMyLife scores classify each match (RET, DEF, W/O and completed sets):

| Class | Matches | Loose: called / wrong | Middle: called / wrong | Strict: called / wrong |
|---|---|---|---|---|
| Completed | 6,652 | 5,828 / 7 | 3,131 / **0** | 2,138 / 0 |
| Retired or defaulted, < 2 sets completed | 185 | 102 / 4 | 51 / 1 | 25 / 0 |
| Retired or defaulted, ≥ 2 sets completed | 61 | 28 / 1 | 7 / 1 | 5 / 1 |
| Walkover | 30 | 1 / 0 | 1 / 0 | 0 / 0 |

- Most wrong calls are retirements: the in-play prices point to the player who was
  leading, who then retired. Most of the rest: one book calls while the others are unclear.
- About 3.6% of matches end in a retirement, default or walkover (276 of 6,928 classified;
  185 of them before 2 completed sets). In-play prices cannot tell a retirement from a
  completed match.

## Decisions (user, 2026-10-17: "Yes to all recommendations")

- **The middle rule is the third results source** (`v5_market_results.inplay_call`),
  after TennisMyLife and Kalshi. A missing result is better than a wrong one.
- **Matches that ended before two completed sets, and walkovers, are void for measuring the
  model** wherever the score is known (`void_for_measurement`). In-play and Kalshi results
  carry `outcome = unknown` (about 3% of them will be unflagged retirements). Settling real
  bets follows each book's own retirement rules (Step 5).
