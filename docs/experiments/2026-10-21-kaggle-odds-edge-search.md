# Edge search on the Kaggle odds file 2014-2025, re-checked on 2026

Status: research. Nothing here is read by production. No sealed-period data (2026 rows end
before 2026-10-13). Roadmap gate: Phase 1 (taker edge search).
Code: `research_tests/kaggle_odds/` (`join_odds.py`, `run_market_models.py`, `post_bets.py`,
`run_2026_check.py`, `check_dk_open.py`) and `research_tests/first_server/run_fs_kaggle.py`.
Numbers: the `results_*.json` files next to them.

## The file (alimoh89/tennis-results-and-betting-odds-20142025)
One CSV, 300k rows, an OddsPortal-style scrape. Things that matter:
- **Winner-first.** player_a is always the winner. Every a/b column is re-oriented by our key
  hash in the join; nothing keeps the file's order.
- **No Pinnacle.** Books: Bet365, Betfair, Ladbrokes, Unibet (close and open), "best" (max over
  many scraped books; not executable). Benchmark used: the de-vigged consensus of the four
  books (mean logit), plus Betfair alone on its subset.
- **Handicaps unusable.** Line sign and prices are not consistently tied to one player; the
  best-fitting reading puts the favourite's price in the winner's column (a leak). Dropped.
- **Totals usable** (orientation-free), except Ladbrokes 2017-18: lines as low as 2.5, overs
  93-99% (scrape defect, dropped).
- 58% of rows are ITF (out of scope, dropped). 81.3% of the remaining 124,771 rows join to our
  match table (unmatched: mostly events we don't hold, e.g. some WTA 125s and Challengers);
  97,175 completed, non-retired matches with features.

## Leak found and fixed in the shared feature table
`research_tests/features/build_features.py` chose an event's "home country" as the most common
nationality over match rows, so players who went deeper counted more and the country whose
players won most became home: home win rate 54.4% that way vs 50.7% counting each player once
(12% of events change). Fixed (one row per player). It inflated this study's first pass (the
"home player" segments were the top finds) and it bears on the 2026-10-20 feature study's
statement that schedule/context, including home country, is irreplaceable; that study should be
re-run on the fixed table. Also noted, not changed: two global constants of the games-luck
feature are fitted on all years (negligible).

## Step 2: models on top of the market, rolling yearly tests (2017-2025, 72,979 matches)
Train 2014..Y-2, early stopping on Y-1, test Y. Gains are log loss, market minus model
(positive = model better), with 95% match-resampled ranges.

| Model | Close as base | Open as base |
|---|---|---|
| LightGBM on top of the market | +0.0011 (0.0007, 0.0015) | +0.0060 (0.0052, 0.0068) |
| Per tour group | +0.0003 | +0.0048 |
| Logistic with market logit | −0.0002 (ns) | +0.0051 |
| Blend with a model-alone LightGBM | +0.0003 | +0.0054 |
| **Ensemble** | **+0.0013 (0.0010, 0.0017)** | **+0.0064 (0.0056, 0.0072)** |
| Model alone (no market) | −0.0117 | −0.0067 |

The close-base ensemble is positive in every test year (+0.0005 to +0.0020) and beats Betfair's
close alone by +0.0009 (0.0005, 0.0014). The opening consensus is a weak benchmark (Betfair's
opening price is poor), so the open-base gain overstates.

## Step 3: does it make money (2017-2025)?
One bet per match on the larger-EV side; returns per unit staked, margin included.

| Prices | Close base, EV > 0 | Close, EV > 2% | Open base, EV > 0 | Open, EV > 2% |
|---|---|---|---|---|
| Bet365 | **+2.8% (1.0, 4.4)**, n 16,447 | +4.3% (1.6, 6.9) | **+2.4% (1.1, 3.7)**, n 30,932 | +3.5% (1.9, 5.2) |
| Mean of Bet365, Ladbrokes, Unibet | +0.9% (−0.7, 2.6) | +1.5% (ns) | −1.7% (−3.1, −0.4) | −1.7% (ns) |
| Betfair net of 5% commission | −1.2% (ns) | −1.4% (ns) | +1.2% (ns) | +3.0% (ns) |
| File's best odds (not executable) | +1.8% | | +4.4% | |
| Back every side at Bet365 | −9.1% | | | |

- The Bet365 result is not line-shopping: betting Bet365 when it beats the other three books'
  fair price loses (−5.0% close, −8.3% open). On model bets where the other books show no
  value at Bet365, the return is still +4.7%.
- It is not stable over time: by year (close, EV > 2%) −7%, +4%, +3%, −3%, +5% for 2017-21, then
  +8%, +6%, +3%, +11% for 2022-25. It comes mostly from underdogs priced 2.2-4.0 (+8.9%);
  prices above 4.0 lose (−5%).
- Closing-line value of open bets against the close consensus is negative (−6%) at the average
  of the books.
- **Segment search** (rounds, surface, rank bands, home and opponent home, workload, rust,
  qualifiers and qualifying rounds, early season, age, price bands, tour, best-of; singles and
  pairs; flat bets and model-filtered bets): about 2,800 cells per base, ranked on 2017-21, top 15
  checked on 2022-25. After the leak fix the survivors are "deep in the event" (3+ matches
  already played) and Bet365 favourites at the open. At Bet365 prices: deep-in-event, best of 3,
  +9.2% (0.8, 17.2), n 697; Bet365 open favourites +4.4% (2.9, 5.8) in 2022-25 but only +0.5%
  in 2017-21. Both look like slices of the Bet365 pattern above, not separate effects.

## Re-check on 2026 (Pinnacle and execution books, before the seal)
Final models fit on 2014-2024 (early stopping 2025), applied to 2026 fixtures.
- **Against Pinnacle: no significant gain.** At the close with Pinnacle as the base, the
  ensemble's log loss is 0.5912 against Pinnacle's 0.5921, a gain of +0.0009 (−0.0002, +0.0020).
  At the open: +0.0002 (ns). Unresolved, not dead: the sign is right, the sample (7,179) is too small.
- **Bet365 cannot be checked**: it quotes about 130 of our 2026 fixtures.
- **BetRivers: no.** Negative closing-line value in every cell.
- **DraftKings' opener: the one live candidate.** Timing-safe version (the only market input is
  DraftKings' own opener; the consensus and Pinnacle opens are often posted later): ensemble,
  EV > 5%: +8.0% ROI (1.6, 14.7), n 633, closing-line value vs Pinnacle's close +2.3% (1.3, 3.4).
  The logistic model gives +9.0% (3.0, 15.2), closing-line value +1.3% (0.5, 2.1). It decays: ROI
  +16.6% in Jan-May vs −3.1% in Jun-Oct; closing-line value +3.2% vs +1.2% (0.0, 2.4). It is one
  cell of about 24 tried at this step (and 128 in the first 2026 pass).

## First-server effect against the Kaggle totals (2014-2025)
(Adds to `2026-10-21-first-server-effect.md`.) Realised totals carry the predicted server shift
relative to the books (slope 0.94 ± 0.08 Bet365, n 38,959; Ladbrokes 0.90; Unibet 0.86). The
books do not move between open and close with the server (Bet365 −0.03 ± 0.03, Ladbrokes
0.06 ± 0.04; Unibet 0.12 ± 0.04 against a placebo of 0.06). At their main lines the shift is
about 0.1 points of probability, so post-toss totals bets almost never clear the margin (0.05 to
0.25% of matches). Handicaps, where the shift is larger, cannot be tested on this file.

## Verdict
- Beating the soft-book consensus: yes, small and consistent (+0.0013 at the close). Beating
  Pinnacle in 2026: not shown (+0.0009, range includes zero). Unresolved.
- Profitable at an executable price: **Bet365 2017-2025 (+2.4 to +4.3%)**, concentrated in
  2022-25, not testable on 2026 data; **DraftKings opener 2026 (+8% at EV > 5%, positive
  closing-line value)**, decaying within the year. Both are unresolved candidates, not findings:
  next step is a forward paper run (the live-price workflow already stores DraftKings openers)
  with the model frozen now and the rule fixed in advance (EV > 5% at DraftKings' opener,
  closing-line value vs Pinnacle's close as the primary measure).
- Everything else tested here (average or Betfair prices, line-shopping, BetRivers, closes in
  2026, post-toss totals) shows no edge after the margin.
