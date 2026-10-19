# Pre-registered: near-even favourites win less often than Pinnacle says

Status: hypothesis locked 2026-10-19, at the user's request in chat. Not tested yet. Do not
change the band, books, prices or pass rules below after today; a changed rule is a new
hypothesis with its own date.

Script: `scripts/measure_favourite_bands.py`. Numbers it came from:
`docs/experiments/data/favourite_bands.json` (2026-01-01 to 2026-10-12).

## Where it came from
For every 2026 fixture before the sealed period with a closing price and a result, the
favourite's win rate by Pinnacle closing price band (7,156 fixtures):

| Pinnacle favourite at close | n | Price says | Favourite won | Back every underdog |
|---|---|---|---|---|
| −1250 or shorter | 239 | 92.7% | 95.8% | −37.8% |
| −1250 to −667 | 377 | 86.5% | 85.9% | +3.5% |
| −667 to −400 | 741 | 80.6% | 82.5% | −13.2% |
| −400 to −250 | 1,333 | 72.9% | 74.9% | −10.1% |
| −250 to −167 | 1,990 | 64.6% | 66.3% | −7.8% |
| **−167 to −125** | **1,771** | **57.5%** | **55.5%** (95% range 53.2–57.8%) | **+0.6%** (−4.8% to +5.9%) |
| −125 to −100 | 706 | 52.0% | 52.3% | −3.9% |

Heavy favourites win a little more often than priced (the usual long-shot bias). The one band
going the other way is −167 to −125: favourites won 2.1 points less than priced (95% range
−4.4 to +0.2 points). It was picked as the best of seven bands after looking, so chance
alone could explain it. Backing the underdog there at execution books: BetRivers −1.6%
(1,412), DraftKings −0.6% (1,441). No Kalshi prices are linked to fixtures before the sealed
period.

## The hypothesis
Fixtures where Pinnacle's closing moneyline favourite is priced above 1.60 and at most 1.80
decimal (−167 to −125):

- **H1 (pricing):** the favourite wins less often than Pinnacle's de-vigged closing price
  (Pinnacle lam, `v5_devig`). Passes if the 95% bootstrap range of (won − price) is entirely
  below zero.
- **H2 (money):** backing the underdog makes money at an execution book (CLAUDE.md:
  Pinnacle is information only). BetRivers at its close, and Kalshi at the best ask standing
  at the start plus the taker fee (`v5_devig.kalshi_fee`, 100-contract orders). Passes for a
  book if the 95% bootstrap range of its return per dollar is entirely above zero.

Only H2 would justify money. H1 alone would be a pricing fact for the market-making work.

## The test
- Data: fixtures starting from 2026-10-13 (the sealed period, never looked at for this),
  same result join as the baseline measurement.
- Evaluated once, when the band has at least 1,800 sealed fixtures (about the in-sample
  size; at about 190 a month this is around October 2027). No early looks.
  `python scripts/measure_favourite_bands.py --from 2026-10-13 --to <that date>`.
- Expectation, honestly: H2 is unlikely to pass. The in-sample return at execution books is
  already below zero, and the band was chosen after looking.

## A faster independent check (needs network access)
tennis-data.co.uk publishes free ATP and WTA main-tour results with Pinnacle closing odds
back to 2010 (roughly 4,000 matches a year in this band). That would test H1 on tour-level
matches that played no part in choosing the band. The host is blocked in this workspace.
