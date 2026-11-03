# Idea-scout batch 1: post-final, short rest, altitude, venue days, layoff, surface switch, free pass (2026-11-03)

**Status:** exploratory. The data is all before 2026-11-01, so it does not count as a forward test.

**What was tested:** seven flags from the idea-scout report (ideas 1–5, 7, 8), chosen by the user.

**Pre-registration:** the rules were written in the docstring of `research_tests/scout/run_scout.py` and committed (`3901865`) before any outcome or price was looked at for these flags.

**Data:**
- the Kaggle odds join with the sportsbook close ("bf", about 3.2% overround) and the Bet365 close, 2016–25;
- the leak-free match order from `v5_fatigue_features.load_repo_matches`;
- venue elevations from opentopodata SRTM90m (`research_tests/scout/data/elevations_srtm90m.csv`).

The geocoder placed seven sea-level venues on high ground, so they were set to 0 m before any result: Gran Canaria, Tenerife, Maui, Reunion, Los Cabos, Santo Domingo and Montemar.

**Sample:** 85,032 matches (Challenger 41,085; ATP main 22,599; WTA main 21,348). Every match found its canonical row.

**Checks:** swap-source, planted edge (it found −0.0025 against the −0.0024 planted), market null and known answers all pass.

**Start-time check (idea 2):** 0.02% of matches start before the player's previous match at the event ended, and 0.08% start within an hour of it. So the tennisexplorer times behave like actual start times, not schedule slots.

## Primary result

The model with all nine inputs, minus the market alone, in log loss on 2022–25 (n = 39,747): **+0.00003** (range −0.00010 to +0.00014). There is no gain as a group. By level:

| level | change in log loss | range |
|---|---|---|
| ATP main | −0.00006 | −0.00032 to +0.00019 |
| WTA main | −0.00001 | −0.00042 to +0.00039 |
| Challenger | +0.00009 | −0.00003 to +0.00020 |

## Each flag

**Residual** = the flagged player's result minus the close, in probability points. Ranges resample flagged players.

**MDE** = the smallest residual the sample could detect (80% power, 5% significance).

The labels follow `docs/RESEARCH_REPORTING.md`.

| flag | n | residual (pts) | range | MDE | 2016–21 | 2022–25 | label |
|---|---|---|---|---|---|---|---|
| **layoff** (91+ days out, top 100, first 3 back) | 1,630 | **−3.52** | −5.65 to −1.40 | 3.0 | −4.37 (−6.76 to −2.00) | −1.78 (−5.71 to +1.96) | **candidate**: overpriced on return, mostly WTA (see the caveat) |
| **surface** (first match on a surface after 56+ days) | 11,442 | **−0.82** | −1.66 to −0.05 | 1.1 | −1.17 | −0.40 (n.s.) | small bias; too small to bet at a ~3% margin |
| altitude (1,400 m+, not acclimatised) | 237 | −4.66 | −10.99 to +1.38 | 8.8 | −3.32 | −6.84 | inconclusive below ~9 pts; the direction fits the idea |
| venue (qualifier with 2+ matches vs a direct entrant fresh from another event) | 2,021 | +0.81 | −1.17 to +2.72 | 2.8 | +0.69 | +0.96 | inconclusive below ~3 pts; same sign as the qualifier candidate |
| hangover (finalist last event, first match next) | 2,489 | −0.22 | −1.86 to +1.40 | 2.3 | +0.49 | −0.99 | ruled out above ~2.3 pts |
| free pass (won the previous round by walkover or early retirement) | 2,625 | +0.09 | −1.71 to +1.88 | 2.6 | −0.30 | +0.52 | ruled out above ~2.6 pts |
| short rest (< 18 h vs ≥ 30 h) | 280 | +0.42 | −4.84 to +5.60 | 7.5 | +3.63 | −5.43 | inconclusive below ~7.5 pts; the two periods disagree in sign |

Slices fixed in advance (exploratory, wide ranges):

| slice | n | residual (pts) | range |
|---|---|---|---|
| hangover, champion | 1,263 | −0.28 | −2.46 to +2.00 |
| hangover, champion, ATP main | 488 | −3.19 | −6.97 to +0.26 |
| hangover, runner-up | 1,256 | −0.16 | −2.61 to +2.34 |
| hangover, moving up a level (Challenger final, then ATP main) | 135 | +5.23 | −2.22 to +12.85 |
| venue, opponent came from another surface | 276 | +1.48 | −3.82 to +7.10 |
| layoff, protected ranking | 29 | +4.02 | −13.42 to +20.27 |

By level, the layoff residual is:
- WTA main −4.17 (−6.90 to −1.54, n = 1,070);
- ATP main −1.96 (−5.50 to +1.24, n = 439);
- Challenger −3.38 (n = 121).

The continuous rest difference has a slope of +0.13 pts per day of extra rest (n = 37,099): no effect.

## Money (2022–25)

The money test runs only for flags whose 2016–21 residual was beyond 2 points.

| rule | book | n | ROI | range |
|---|---|---|---|---|
| back the opponent of a returning player (layoff) | sportsbook close | 539 | +1.7% | −8.5% to +13.5% |
| | Bet365 close | 532 | −2.1% | −11.5% to +7.6% |
| back the acclimatised side at altitude | sportsbook close | 90 | +16.3% | −8.2% to +41.3% |
| | Bet365 close | 87 | +13.4% | −10.4% to +38.7% |
| back the short-rest player (2016–21 was +3.6) | sportsbook close | 99 | −19.1% | −40.2% to +2.7% |
| | Bet365 close | 97 | −22.1% | −43.8% to +0.1% |

## What this means

1. **Layoff is a real bias in 2016–25, but it shrank out of sample** (−4.4 pts in 2016–21, then −1.8 in 2022–25, with a range that crosses zero).
   - Betting it in 2022–25 broke even at the sportsbook close and lost at Bet365.
   - **Caveat:** the WTA history has no WTA 125 or ITF events. Some WTA "layoffs" are players who were competing at lower levels, not resting. The cleaner ATP slice (Challengers included, so a gap is a real gap) is −2.0 pts, not significant.
   - Next step: add WTA 125 results and re-run the WTA slice. It could then go into a registered forward test (Kalshi WTA/ATP, return matches).
2. **Altitude points the right way and is large**, but there are only 237 flagged matches (the scout's estimate of about 900 was too high, because the "not acclimatised" filter removes most of the field). It cannot be confirmed from history.
   - It is cheap to watch forward: Bogotá, Quito and the Mexican Challengers come back every year.
   - The flag is pre-registered here, so it can go into a forward test as written.
3. **Hangover and free pass are ruled out** above about 2.3 and 2.6 pts. The close already handles both.
4. **Venue days and short rest are inconclusive.** Venue is the same sign as the qualifier candidate (+1.2), but no stronger, so acclimatisation does not explain the qualifier edge better than plain qualifying form. Short rest flips sign between the two periods, which is what noise looks like at n = 280.
5. **Surface switch** is a small, significant overpricing (−0.8 pts) of players returning to a surface. It is well below the margin, but it can join the blend as one more input.

Results JSON: written by `run_scout.py` (not committed; the run manifest inside it records the inputs and their hashes).
