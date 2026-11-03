# Registration: back the favourite against Kalshi tennis long shots

Registered 2026-11-03 under `docs/superpowers/specs/2026-11-01-rolling-forward-test-amendment.md`.
This file is never edited; a changed rule is a new registration.

## Hypothesis and the decision it would change

Kalshi tennis long shots are overpriced by more than Kalshi's taker fee, so buying the favourite
when the long shot trades at 20¢ or less makes money after fees. If it passes, it becomes the
first candidate for small real stakes (after the research_kit checks and a second forward
window, as the amendment requires). If it fails, the long-shot idea is dropped for Kalshi
pre-match.

Where it came from (data before 2026-11-01): `docs/experiments/2026-11-03-kalshi-taker-side.md`
(1.03M pre-start trades, Aug-Oct 2026: in markets where YES traded at 20¢ or less, takers backing
the favourite made +7.0¢ per contract after the taker fee, range 5.2 to 8.3; the 20¢ cut was
chosen after looking at about 20 cuts, which is why it needs this forward test).

## The rule (scored by `scripts/track_longshot_rule.py` at commit `74e9fe9552362ea6015819fdd07271feb4b34843`, branch `feat/vm-runner`)

- **Markets:** Kalshi series KXATPMATCH, KXATPCHALLENGERMATCH, KXWTAMATCH.
- **Window opens:** matches whose scheduled start (Kalshi milestone `start_date`) is after
  **2026-11-03T15:00:00Z**, set in the code before this registration was committed, so nothing
  from before the registration counts.
- **Decision snapshot:** the latest 5-minute pre-match snapshot from the server's logger
  (`market_history/kalshi/live_scores/prematch/`) taken between 6 hours and 60 minutes before the
  scheduled start, and before the match first appears in the live log.
- **Long shot:** the market whose YES bid is 0.20 or less in that snapshot, with both of the
  match's markets quoted (bid and ask) and the long shot's YES spread at most 0.05. Exactly one
  such market, or the match is skipped.
- **Bet (paper):** 100 contracts on the favourite at the cheaper executable price of NO on the long
  shot (1 − long shot YES bid) and YES on the favourite (its YES ask).
- **Fee:** Kalshi taker fee, rounded up to the cent per order:
  ceil(0.07 × 100 × P × (1 − P) × 100) / 100 dollars for the 100-contract order.
- **Result:** the long shot's Kalshi market result. `yes` or `no` count; any other settlement
  (for example `scalar`) is void and left out.

## Metric, pass rule, sample, end

- **Metric:** mean P&L per contract after the fee.
- **Pass:** the 95% range (2,000 resamples of settled matches, seed 20261103) is wholly above
  zero.
- **Minimum sample:** 300 settled matches.
- **Ends:** at 300 settled matches, or on 2027-01-31 if fewer, then scored once. If it ends
  with fewer than 300, it is recorded as inconclusive, not as a pass.
- **Reported alongside (not part of the pass rule):** result by series, by long-shot price
  (≤0.10, 0.10-0.20), the favourites' win rate against the average price paid, and the dollars
  at 100 contracts per match.

## Not allowed during the window

Changing the price cut, the snapshot timing, the series, the size, the fee model or the void
rule. Watching the running number is allowed; acting on it is not.
