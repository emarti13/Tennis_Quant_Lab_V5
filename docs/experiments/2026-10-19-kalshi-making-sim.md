# Would quoting both sides of Kalshi tennis markets have made money? (edge search 3)

Status: research result, 2026-10-19. Script: `scripts/simulate_kalshi_making.py`; numbers:
`docs/experiments/data/kalshi_making.json`. Raw input: the `kalshi_*.jsonl.gz` files of the
`market-raw-2026-10` release (every market's 1-minute best bid/ask and every pre-start trade).

## Setup
A replay of a simple market maker on each Kalshi player market ("A wins"): a resting buy at
fair − h and a resting sell at fair + h (to the cent, never crossing the book), 100 contracts
a side, at most 300 net per market, everything cancelled one minute before the start.
Fills only from Kalshi's real trades, conservatively: a trade fills us only if it went
through our price, or hit our price while we were strictly the best. Takers our better price
might have attracted are not counted.

Fair price: Kalshi's own mid standing before each trade. The planned versions (Pinnacle's
line as fair, plus the open+Elo+fatigue lean from the open-close experiment) could not run:
the price store has no Pinnacle prices for these dates (the OddsPapi backfill stopped in
early August when Actions billing locked), and Kalshi markets are linked to fixtures with
prices only from 2026-10-13, which is sealed.

Data: 2,810 markets (1,405 matches), 2026-08-10 to 2026-09-02, before the sealed period.

Three ways to count:
- **Marked**: fills valued at Kalshi's last mid before the start. This is the spread earned
  minus losses to better-informed traders, without the match result's noise. The test.
- **Held**: what is left at the start rides to settlement (very noisy over 3 weeks).
- **Flattened**: what is left at the start closed by crossing the spread and paying the
  taker fee (7% × P × (1 − P)).

## Results (marked, no maker fee unless stated)
| Quote half-width | ATP | Challenger | WTA |
|---|---|---|---|
| 1¢ | −$1,800 (CI −2,411 to −1,234) | −$693 (−1,129 to −265) | −$848 (−1,229 to −471) |
| 2¢ | −$791 (−1,312 to −340) | +$47 (−305 to +391) | −$374 (−673 to −87) |
| 3¢ | −$397 (−839 to −28) | **+$332 (+45 to +640)** on 44,319 contracts | −$202 (−433 to +15) |
| 5¢ | −$101 (−346 to +121) | **+$444 (+211 to +675)** on 20,422 contracts | −$17 (−158 to +134) |

Challenger with Kalshi's maker fee schedule (0.0175 × P × (1 − P)) as a check: 3¢ +$168
(−149 to +449); 5¢ +$368 (+141 to +592).

- **ATP and WTA:** a maker quoting around Kalshi's mid loses. Fills come mostly when a
  better-informed trader moves the price through us. These books are already run by
  professionals at 1¢ spreads.
- **Challenger with wider quotes (3–5¢):** positive after being picked off: about 0.7 to
  2.2¢ a contract, with the 95% range above zero. That is the only positive result in the
  table. It fits the earlier findings: Challenger books are thin, and Challenger lines are
  where our model best predicts the move.
- **Flattening loses everywhere** (the taker fee costs more than the spread earned). A
  maker has to hold what is left to the match and accept that noise. Held to settlement,
  Challenger at 5¢ made +$489, but the range (−1,350 to +2,300) shows how noisy three weeks
  are.

## How much money, honestly
Challenger at 5¢: about $440 over 24 days with 100-contract quotes, roughly $18 a day,
before any lean. Small. It is a sign that the mechanism works where we expected, not a
business yet.

## Caveats
- 16 settings were tried across 4 families. The Challenger rows were not chosen in advance,
  though the pattern (wider is better, Challenger only) is consistent rather than one lucky
  cell.
- Three weeks of data from one part of the season (Toronto, Cincinnati, US Open qualifying).
- 1-minute candles: the "best bid/ask standing" can be up to a minute old, so who was first
  in the queue is approximate.
- No model information in the quotes yet. The lean and a Pinnacle fair price may improve it
  or not. Untested.

## Next
1. When Actions is back: backfill the price store for August to October, then rerun with
   Pinnacle fair and the lean (`--oc-table`).
2. Confirm Kalshi's maker fee on tennis markets.
3. If those hold up: a paper-trading run (quotes computed live, nothing sent) on the user's
   own machine, since Kalshi's API is blocked in this workspace and Actions cannot poll.
   Built: `scripts/paper_kalshi_making.py`, Challenger at 3¢ and 5¢ around Kalshi's mid
   (docs/experiments/2026-10-19-kalshi-paper-run.md). The quote and fill rules of this
   replay now live in `v5_kalshi_making.py`, shared with the paper run (same fills, tested).
