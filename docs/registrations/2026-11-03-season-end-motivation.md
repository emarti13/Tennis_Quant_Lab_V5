# Registration: late in the season, back the opponent of a player ranked 31-90

Registered 2026-11-03 under `docs/superpowers/specs/2026-11-01-rolling-forward-test-amendment.md`.
This file is never edited; a changed rule is a new registration.

## Hypothesis and the decision it would change

After October 20, players ranked 31-90 often have nothing left to qualify for and are tired.
Their opponents are often chasing points before the cut-offs. The market prices both on ranking as
usual, so backing the opponent makes money after Kalshi's fee. If it passes, it joins the
candidates for small real stakes (after the research_kit checks and a second forward window). If it
fails, the motivation idea is dropped for this flag.

Where it came from (data before 2026-11-01): `docs/experiments/2026-11-03-incentives.md`. Seven
pre-registered flags were tested on 84,956 matches from 2016-2025, and all checks pass. On this
flag, the flagged player won 4.1 points less than Betfair's close (−6.4 to −1.6). Backing the
opponent in 2022-2025 made +12.3% after Betfair's commission (+0.6% to +25%, 678 bets). It was the
one flag of seven that crossed the bar, so it needs this forward test. The effect was clear on the
ATP main tour and Challengers but not on the WTA (−1.7, −6.6 to +3.2), and the rank source below is
ATP only, so the rule covers ATP only.

## The rule (scored by `scripts/track_season_end_rule.py` at commit `adaf98fe2459bc5b8e3e34d0cac2a896903616a1`, branch `feat/vm-runner`)

- **Markets:** Kalshi series KXATPMATCH and KXATPCHALLENGERMATCH.
- **Window:** matches whose scheduled start (Kalshi milestone `start_date`) is after
  **2026-11-03T15:00:00Z** (set in the code before this registration was committed) and falls
  between October 20 and December 31 of any year.
- **Decision snapshot:** the latest 5-minute pre-match snapshot from the server's logger taken
  between 6 hours and 60 minutes before the scheduled start, and before the match first appears
  in the live log. Both of the match's markets must be quoted with a bid and an ask.
- **Rank:** each player's rank at their most recent ATP event dated on or before the decision day,
  from `v5_results_ready/tennismylife_results.csv` on `main` (refreshed daily by the ratings
  workflow). Names are matched after removing accents, case, hyphens and spaces. A player who is
  not found means no bet.
- **Flag:** exactly one player is ranked 31-90; the other's rank is known and outside 31-90.
- **Bet (paper):** 100 contracts on the other player, at the cheaper executable price of YES on that
  player (its ask) and NO on the flagged player (1 − the flagged player's YES bid).
- **Fee:** Kalshi taker fee, rounded up to the cent per order:
  ceil(0.07 × 100 × P × (1 − P) × 100) / 100 dollars.
- **Result:** the flagged player's Kalshi market result. `yes` or `no` count; anything else is void.

## Metric, pass rule, sample, end

- **Metric:** mean P&L per contract after the fee.
- **Pass:** the 95% range (2,000 resamples of settled matches, seed 20261103) is wholly above zero.
- **Minimum sample:** 300 settled matches. About 130-200 qualify per season, so this spans the 2026
  and 2027 season ends.
- **Ends:** at 300 settled matches, or on 2027-12-31 if fewer, then scored once. If it ends with
  fewer than 300, it is recorded as inconclusive.
- **Reported alongside (not part of the pass rule):** by series, by the flagged player's rank band
  (31-60, 61-90), by the opponent's rank (above or below the flagged player), and the dollars at
  100 contracts per match.

## Not allowed during the window

Changing the rank band, the dates, the series, the snapshot timing, the size, the fee model, the
name matching or the void rule. Watching the running number is allowed; acting on it is not.
