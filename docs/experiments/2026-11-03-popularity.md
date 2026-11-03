# Popularity: is a famous player's price too short? (2026-11-03)

**Status:** exploratory (all data is before 2026-11-01).

**Test:** `research_tests/popularity/run_popularity.py`, pre-registered in its docstring before any result.

**Fame** = log(1 + English-Wikipedia page views in the month before the match). It comes from `fetch_pageviews.py`:
- 3,291 names were looked up;
- 2,284 tennis articles were found;
- 2,281 of them had views.

Match coverage, where both players have an article:

| level | coverage |
|---|---|
| ATP main | 98% |
| WTA main | 98% |
| Challenger | 89% |

**Sample:** 85,032 matches, 2016–25. Walk-forward by year, test years 2022–25.

**Checks:** swap-source, planted edge (found −0.0025 vs −0.0024 planted), market null and known answers all pass. No alarms.

## Results

| measure | value | range |
|---|---|---|
| PRIMARY: market + fame gap, minus market, log loss 2022–25 (n = 39,747) | +0.00002 | −0.00002 to +0.00006 |
| fame coefficient fitted on 2016–21 (log-odds per unit of fame gap; negative = fame overpriced) | −0.0024 | −0.0092 to +0.0062 |
| the same coefficient fitted on 2022–25 | +0.0019 | |
| fame gap × favourite added | +0.00006 | +0.00001 to +0.00011 (slightly worse) |

Log loss by level, against the market alone:

| level | change in log loss | range |
|---|---|---|
| ATP main | −0.00004 | −0.00011 to +0.00003 |
| WTA main | +0.00002 | −0.00006 to +0.00009 |
| Challenger | +0.00005 | −0.00001 to +0.00012 |

The raw residuals by fame gap bin, 2022–25, have no slope. They run from −1.65 to +0.66 pts and are symmetric: the bins from −3 to −2 and from +2 to +3 are both −1.6.

| money rule, 2022–25 | n | ROI | range |
|---|---|---|---|
| back the less famous player when the gap is ≥ 2 (about 7× the views), sportsbook close | 15,020 | −6.4% | −9.0% to −3.6% |
| the same, Bet365 close | 14,433 | −11.0% | −13.6% to −8.4% |
| the same, Bet365 open | 14,442 | −11.5% | −14.0% to −8.9% |

## Label

**Ruled out above about 1 point.** The coefficient's range of ±0.008 log-odds per unit means that even a 20× fame gap (3 units) moves the price by under 1 point at most.

The money rule loses about the book margin, plus the long-shot margin.

**What is not covered:**
- Kalshi, whose US retail flow is the most likely place for a fame bias. The live Kalshi log has only a few days of data, so that is a later forward step.
- A US-only fame measure.

**Blend:** popularity is not added. An input that is ruled out would only add noise to the blend.
