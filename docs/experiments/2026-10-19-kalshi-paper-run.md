# Kalshi Challenger paper market making (forward test of edge search 3)

Status: built and trialled, 2026-10-19. Not yet running anywhere for real. Script:
`scripts/paper_kalshi_making.py`. Rules: `v5_kalshi_making.py`. Follows
`docs/experiments/2026-10-19-kalshi-making-sim.md`. Roadmap Phase 4 (Gate 4: positive
net P&L after fees and adverse selection on the forward window, positive markouts).

## What it does
Quotes computed live from Kalshi's public market data. **No order is ever sent**: the script
has no order or portfolio call and needs no account or keys (a test checks this).

Settings, fixed before the run starts. Nothing here may be tuned on its results, since they
fall in the sealed period (roadmap §4, Phase 0):
- ATP Challenger match markets only (`KXATPCHALLENGERMATCH`), the one family with a
  positive replay result.
- Half-widths 3¢ and 5¢ around Kalshi's own mid, both run side by side. 100 contracts a
  side, at most 300 net per market.
- The same quote and fill rules as the replay, from the same code (`v5_kalshi_making`; a
  test feeds both the same data and checks the fills match): the mid only when the book is
  two-sided and at most 20¢ wide; never crossing the book. A real trade fills us only if it
  went through our price, or hit our price while we were strictly the best.
- Stop one minute before the start.

Each poll (every 10 s by default, about 3 to 5 API calls) lists the open Challenger markets
with their best bid/ask, asks Kalshi's live match feed whether each match has started, and
checks the new trades of every market whose volume moved against the quotes standing from
the snapshot taken before them.

## The start time (found in the trial)
Kalshi's `occurrence_datetime` is **not** the start: on every open Challenger market checked
on 2026-10-19 it was the match milestone's scheduled start plus exactly 3 h. One match
(Jasika v Matsuda, Guangzhou qualifying) was already in its second set while
`occurrence_datetime` was still 2 h away. A first version that stopped there recorded
in-play fills. Matches also often start later than scheduled.

The run therefore uses Kalshi's live match feed (`/milestones` and `/live_data`, both free
and public). A trade counts only once a later poll has seen the match still `not_started`
at least one minute after the trade. Any other status, no milestone, or no answer means no
quote (fail closed). In the trial, one match (`KXATPCHALLENGERMATCH-26OCT19SAMDEM`) went from `not_started` to
`live` between two 10 s polls and was cut there. The report drops any fill after the true
start in the price store as a second check, once the daily Kalshi pull knows that start.

The same issue exists in the price store: 230 of 3,378 stored Kalshi markets have no matched
fixture and are cut at `occurrence_datetime` (`cutoff_source = kalshi_occurrence`, in
`v5_kalshi_history.kalshi_cutoff`), so their "pre-start" points may hold in-play trades. On
the 3,134 markets with a true start, `occurrence_datetime` is a median 1.3 h after it (range
−53 h to +24 h). The replay used only fixtures with the OddsPapi start, so its numbers are
not affected. This is a separate fix, not made here.

## Trial (2026-10-19, about 15 minutes in a cloud session)
82 Challenger markets quoted. The poll rate stayed under Kalshi's limit after one change: a
new market's trades from before our first snapshot are never fetched. The trial logs were
not kept; they are not evidence.

## How to run it (the user's machine)
```
python scripts/paper_kalshi_making.py run              # until stopped (Ctrl-C); restart any time
python scripts/paper_kalshi_making.py report           # settled markets so far -> report.json
```
Needs Python with `pandas`, `numpy` and `requests`, and internet access to
`api.elections.kalshi.com`. The logs go to `paper_trading/kalshi_making/`, which git
ignores: `markets.csv`, `snapshots.csv`, `status.csv`, `trades.csv` and `fills.csv`. All are
append-only. A restart keeps positions and the trades already counted. Trades during a gap
are not counted (no book snapshot). Actions cannot run this (no continuous polling,
CLAUDE.md), and a cloud session's container does not last.

The report counts each half-width marked at Kalshi's last mid before the stop (the test, as
in the replay), held to settlement, with and without the maker fee (0.0175 × P × (1 − P),
unconfirmed for tennis), with markouts at 1 and 5 minutes and bootstrap 95% intervals over
markets.

## What would count as a pass: DRAFT — pending user approval (to fix before any result)
Over at least 4 weeks of running: marked P&L after the maker fee above zero with the 95%
interval above zero at the half-width carried forward (5¢, the stronger replay row), and
mean 5-minute markout not negative. Divergence from the replay's 0.7 to 2.2¢ a contract is
reported either way.

## Not done
- The read-only balance check of the demo keys (`KALSHI_DEMO_KEY_ID`,
  `KALSHI_DEMO_PRIVATE_KEY_B64` on `demo-api.kalshi.co`). Both are set and the key decodes
  as an RSA private key, but the signed request was blocked in this session. The paper
  run does not need the keys.
- Pinnacle fair and the model lean (sim "Next" 1): waiting on the price-store backfill.
