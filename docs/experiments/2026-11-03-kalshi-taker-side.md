# Kalshi tennis: YES buyers do not overpay as such; long shots look overpriced

Date: 2026-11-03. Research on data before 2026-11-01 (open for exploration under the forward-test
amendment). Script: `research_tests/kalshi_takers/run_taker_side.py`; output: `research_tests/kalshi_takers/results.json`.

## Question

The server's paper market-maker made money holding positions to settlement (+$1,134 after the
assumed maker fee, 143 matches, 95% range −$266 to +$2,488), mostly short YES sold to YES
buyers. Hypothesis (pre-registered in the script): takers who buy YES on Kalshi tennis overpay.

## Data

1,026,460 pre-start trades on 3,265 markets in 1,636 matches (ATP, WTA, ATP and WTA
Challenger), 2026-08-11 to 2026-10-17, with the taker's side, price and size, and each market's
result. 85% of contracts were bought by YES takers. Most markets are from August (the pull was
thinner later).

## Checks

Market null (results drawn from each trade's price): −0.26¢ per contract, expected −0.34¢ (the
maker fee), range includes it. Planted shift (YES wins 3 points less than priced): 2.64¢ found,
2.66¢ expected. Both pass.

## Results (per contract; 95% ranges resample whole matches)

| | Result | Range |
|---|---|---|
| **PRIMARY: maker against YES-buying takers, after maker fee** | **+0.61¢** | −0.93 to +2.13 |
| maker against NO-buying takers | −1.55¢ | −3.49 to +0.47 |
| YES-buying takers, after taker fee | −2.32¢ | −3.83 to −0.77 (mostly the fee) |

**The primary hypothesis does not hold**: no significant overpayment by YES buyers as such.

What does show up, after the fact (so a hypothesis, not a finding), is the favourite-longshot
pattern, the same one seen at every bookmaker in the Kaggle data:

- Last pre-start price against the result, one row per market (3,265 markets):
  long shots priced 0-10% won 1.6 points less than priced, 10-20% 3.7 less, 20-30% 3.7 less;
  favourites priced 70-80% won 2.4 more, 80-90% 3.4 more. No single band is significant on
  its own; the shape is consistent.
- Trades in markets where YES traded at 20% or less: takers who bought NO (backing the
  favourite) made **+7.0¢ per contract after the taker fee** (5.2 to 8.3, equal weight per
  trade, 339 matches); takers who bought YES on the long shot lost −7.0¢ (−9.6 to −3.7).
  By series (long-shot markets, last price): ATP Challenger −6.0 points (−9.4 to −2.0), WTA
  −5.2 (−10.6 to +0.5), ATP +1.4 (−7.0 to +10.8), WTA Challenger +9.9 (n=23).

## Why it could be real on Kalshi when it is not at the bookmakers

The long-shot bias is everywhere, but the bookmakers' margin (about 5%) is bigger than it.
Kalshi's taker fee is 0.07·P·(1−P): about 0.9¢ on a 15¢ contract and 1.1¢ on an 85¢ one. That is
far smaller than a bookmaker's margin on a heavy favourite. The bias may survive Kalshi's fees.

## What it means for the paper trader

Its "hold" profit is consistent with being on the right side of long-shot buyers, plus a lot of
luck; the general "fade YES buyers" story is not supported.

## Next

The long-shot rule was found by looking, across about 20 cuts, so it needs a registered forward
test: back the favourite (buy NO on the long shot) on Kalshi tennis markets whose YES trades at
20¢ or less before the start, at the executable ask with the taker fee, scored on markets that
start after the registration. The server's 5-minute pre-match quotes record the executable asks.
